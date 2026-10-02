//! XP-015 transport only. No game rules, engine commands or Builder access.
use anyhow::{ensure, Context, Result};
use serde::{Deserialize, Serialize};
use std::{
    net::SocketAddr,
    sync::{Arc, OnceLock},
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tokio::{
    io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt},
    net::TcpStream,
    time::timeout,
};
pub mod client;
pub mod server;
pub const FRAME: usize = 8192;
pub const SESSION_SECONDS: u64 = 7200;
pub const INVITE_SECONDS: u64 = 600;
pub fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}
pub fn token() -> String {
    format!(
        "{}{}",
        uuid::Uuid::new_v4().simple(),
        uuid::Uuid::new_v4().simple()
    )
}
pub fn valid_token(s: &str) -> bool {
    s.len() == 64 && s.bytes().all(|b| b.is_ascii_hexdigit())
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Service {
    Package,
    Game,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Route {
    pub session: String,
    pub capability: String,
}
#[derive(Serialize, Deserialize)]
#[serde(tag = "action", rename_all = "snake_case", deny_unknown_fields)]
pub enum Request {
    Register {
        credential: String,
    },
    Publish {
        session: String,
        host: String,
        capability: String,
        expires: u64,
    },
    Exchange {
        session: String,
        capability: String,
    },
    Poll {
        session: String,
        host: String,
    },
    Connect {
        session: String,
        lease: String,
        service: Service,
    },
    Attach {
        session: String,
        host: String,
        channel: String,
    },
    End {
        session: String,
        host: String,
    },
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Envelope {
    pub schema: String,
    pub request: Request,
}
impl Envelope {
    pub fn new(request: Request) -> Self {
        Self {
            schema: "xace.relay.request.v1".into(),
            request,
        }
    }
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Incoming {
    pub channel: String,
    pub service: Service,
}
#[derive(Default, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Response {
    pub schema: String,
    pub ok: bool,
    pub message: String,
    pub session: Option<String>,
    pub credential: Option<String>,
    pub expires: Option<u64>,
    pub incoming: Vec<Incoming>,
}
impl Response {
    pub fn ok() -> Self {
        Self {
            schema: "xace.relay.response.v1".into(),
            ok: true,
            ..Default::default()
        }
    }
    pub fn error() -> Self {
        Self {
            message: "Relay refused or session unavailable".into(),
            ..Self::ok_error()
        }
    }
    fn ok_error() -> Self {
        Self {
            schema: "xace.relay.response.v1".into(),
            ..Default::default()
        }
    }
    pub fn check(self) -> Result<Self> {
        ensure!(
            self.schema == "xace.relay.response.v1" && self.ok,
            "{}",
            self.message
        );
        Ok(self)
    }
}
pub async fn send<S: AsyncWrite + Unpin, T: Serialize>(s: &mut S, v: &T) -> Result<()> {
    let b = serde_json::to_vec(v)?;
    ensure!(b.len() <= FRAME, "Relay frame too large");
    timeout(Duration::from_secs(5), async {
        s.write_u32_le(b.len() as u32).await?;
        s.write_all(&b).await?;
        s.flush().await
    })
    .await??;
    Ok(())
}
pub async fn receive<S: AsyncRead + Unpin, T: serde::de::DeserializeOwned>(s: &mut S) -> Result<T> {
    timeout(Duration::from_secs(5), async {
        let n = s.read_u32_le().await? as usize;
        ensure!(n > 0 && n <= FRAME, "Invalid relay frame");
        let mut b = vec![0; n];
        s.read_exact(&mut b).await?;
        Ok(serde_json::from_slice(&b)?)
    })
    .await?
}
#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Config {
    pub schema: String,
    pub host: String,
    pub port: u16,
    pub ca_der: std::path::PathBuf,
    pub host_credential: Option<String>,
}
impl Config {
    pub fn from_env() -> Result<Option<Self>> {
        let Some(path) = std::env::var_os("XACE_RELAY_CONFIG") else {
            return Ok(None);
        };
        let bytes = std::fs::read(&path)?;
        ensure!(bytes.len() <= 16384, "Relay config too large");
        let mut c: Self = serde_json::from_slice(&bytes)?;
        ensure!(
            c.schema == "xace.relay.config.v1"
                && c.port > 0
                && !c.host.is_empty()
                && c.host.len() <= 253,
            "Invalid relay config"
        );
        if c.ca_der.is_relative() {
            c.ca_der = std::path::Path::new(&path).parent().unwrap().join(c.ca_der)
        }
        Ok(Some(c))
    }
}
pub fn runtime() -> &'static tokio::runtime::Runtime {
    static RT: OnceLock<tokio::runtime::Runtime> = OnceLock::new();
    RT.get_or_init(|| {
        tokio::runtime::Builder::new_multi_thread()
            .worker_threads(2)
            .enable_all()
            .build()
            .expect("relay executor")
    })
}
#[derive(Clone)]
pub struct Client {
    config: Config,
    tls: tokio_rustls::TlsConnector,
}
impl Client {
    pub fn new(config: Config) -> Result<Self> {
        let mut roots = rustls::RootCertStore::empty();
        roots.add(rustls::pki_types::CertificateDer::from(std::fs::read(
            &config.ca_der,
        )?))?;
        let provider = Arc::new(rustls::crypto::ring::default_provider());
        let tls = rustls::ClientConfig::builder_with_provider(provider)
            .with_protocol_versions(&[&rustls::version::TLS13])?
            .with_root_certificates(roots)
            .with_no_client_auth();
        Ok(Self {
            config,
            tls: tokio_rustls::TlsConnector::from(Arc::new(tls)),
        })
    }
    pub async fn dial(&self) -> Result<tokio_rustls::client::TlsStream<TcpStream>> {
        timeout(Duration::from_secs(5), async {
            // Race a bounded set of resolved addresses. A stalled IPv6 route must not
            // consume the package request budget when IPv4 is reachable (or vice versa).
            let addresses =
                tokio::net::lookup_host((self.config.host.as_str(), self.config.port)).await?;
            let mut attempts = tokio::task::JoinSet::new();
            for address in addresses.take(8) {
                attempts.spawn(TcpStream::connect(address));
            }
            let mut connected = None;
            while let Some(result) = attempts.join_next().await {
                if let Ok(Ok(stream)) = result {
                    connected = Some(stream);
                    break;
                }
            }
            let tcp = connected.context("No reachable relay address")?;
            drop(attempts);
            tcp.set_nodelay(true)?;
            let name = rustls::pki_types::ServerName::try_from(self.config.host.clone())?;
            Ok(self.tls.connect(name, tcp).await?)
        })
        .await
        .context("Relay unreachable")?
    }
    pub async fn request(&self, r: Request) -> Result<Response> {
        let mut s = self.dial().await?;
        send(&mut s, &Envelope::new(r)).await?;
        receive::<_, Response>(&mut s)
            .await
            .context("Relay refused the request or is unavailable")?
            .check()
    }
    pub async fn connect(&self, r: Request) -> Result<tokio_rustls::client::TlsStream<TcpStream>> {
        let mut s = self.dial().await?;
        send(&mut s, &Envelope::new(r)).await?;
        receive::<_, Response>(&mut s)
            .await
            .context("Relay refused the request or is unavailable")?
            .check()?;
        Ok(s)
    }
}
pub fn loopback(port: u16) -> SocketAddr {
    SocketAddr::from(([127, 0, 0, 1], port))
}
