use crate::*;
use std::collections::BTreeMap;
use tokio::{
    io::{AsyncRead, AsyncWrite},
    net::TcpListener,
    sync::{oneshot, watch, Mutex, Semaphore},
};
type Stream = tokio_rustls::server::TlsStream<TcpStream>;
const MAX_SESSIONS: usize = 16;
const MAX_CONNECTIONS: usize = 128;
const MAX_BYTES: u64 = 2 * 1024 * 1024 * 1024;
const BYTES_PER_SECOND: u64 = 8 * 1024 * 1024;
struct Budget {
    total: u64,
    second: u64,
    bytes: u64,
}
impl Budget {
    fn charge(&mut self, n: u64, t: u64) -> Result<()> {
        if self.second != t {
            self.second = t;
            self.bytes = 0
        }
        ensure!(
            self.total + n <= MAX_BYTES && self.bytes + n <= BYTES_PER_SECOND,
            "Relay traffic limit"
        );
        self.total += n;
        self.bytes += n;
        Ok(())
    }
}
struct Lease {
    expires: u64,
    slots: Arc<Semaphore>,
}
struct Pending {
    send: oneshot::Sender<Stream>,
    service: Service,
    created: u64,
    announced: bool,
}
struct Session {
    host: String,
    expires: u64,
    seen: u64,
    invites: BTreeMap<String, u64>,
    leases: BTreeMap<String, Lease>,
    pending: BTreeMap<String, Pending>,
    stop: watch::Sender<bool>,
    budget: Arc<Mutex<Budget>>,
}
impl Drop for Session {
    fn drop(&mut self) {
        let _ = self.stop.send(true);
    }
}
struct State {
    sessions: BTreeMap<String, Session>,
    credential: String,
}
impl State {
    fn prune(&mut self) {
        let t = now();
        self.sessions
            .retain(|_, s| s.expires > t && t.saturating_sub(s.seen) <= 10);
        for s in self.sessions.values_mut() {
            s.invites.retain(|_, e| *e > t);
            s.leases.retain(|_, l| l.expires > t);
            s.pending.retain(|_, p| t.saturating_sub(p.created) < 5);
        }
    }
    fn host(&mut self, id: &str, key: &str) -> Result<&mut Session> {
        let s = self.sessions.get_mut(id).context("Unknown session")?;
        ensure!(s.host == key, "Invalid host");
        Ok(s)
    }
}
async fn pump<R: AsyncRead + Unpin, W: AsyncWrite + Unpin>(
    mut r: R,
    mut w: W,
    budget: Arc<Mutex<Budget>>,
) -> Result<()> {
    let mut buffer = [0u8; 16384];
    loop {
        let n = timeout(Duration::from_secs(15), r.read(&mut buffer)).await??;
        if n == 0 {
            return Ok(());
        }
        budget.lock().await.charge(n as u64, now())?;
        timeout(Duration::from_secs(5), w.write_all(&buffer[..n])).await??;
        timeout(Duration::from_secs(5), w.flush()).await??;
    }
}
async fn bridge(
    a: Stream,
    b: Stream,
    budget: Arc<Mutex<Budget>>,
    mut stop: watch::Receiver<bool>,
    expires: u64,
) -> Result<()> {
    let (ar, aw) = tokio::io::split(a);
    let (br, bw) = tokio::io::split(b);
    tokio::select! { r=pump(ar,bw,budget.clone())=>r,r=pump(br,aw,budget)=>r,_=stop.changed()=>Ok(()),_=tokio::time::sleep(Duration::from_secs(expires.saturating_sub(now())))=>Ok(()) }
}
async fn handle(mut stream: Stream, state: Arc<Mutex<State>>) -> Result<()> {
    let env: Envelope = receive(&mut stream).await?;
    ensure!(
        env.schema == "xace.relay.request.v1",
        "Invalid relay schema"
    );
    let mut st = state.lock().await;
    st.prune();
    let mut response = Response::ok();
    match env.request {
        Request::Register { credential } => {
            ensure!(
                valid_token(&credential)
                    && credential == st.credential
                    && st.sessions.len() < MAX_SESSIONS,
                "Registration refused"
            );
            let id = uuid::Uuid::new_v4().to_string();
            let host = token();
            let expires = now() + SESSION_SECONDS;
            let (stop, _) = watch::channel(false);
            st.sessions.insert(
                id.clone(),
                Session {
                    host: host.clone(),
                    expires,
                    seen: now(),
                    invites: BTreeMap::new(),
                    leases: BTreeMap::new(),
                    pending: BTreeMap::new(),
                    stop,
                    budget: Arc::new(Mutex::new(Budget {
                        total: 0,
                        second: now(),
                        bytes: 0,
                    })),
                },
            );
            response.session = Some(id);
            response.credential = Some(host);
            response.expires = Some(expires);
        }
        Request::Publish {
            session,
            host,
            capability,
            expires,
        } => {
            let s = st.host(&session, &host)?;
            ensure!(
                valid_token(&capability)
                    && expires > now()
                    && expires <= now() + INVITE_SECONDS
                    && expires <= s.expires
                    && s.invites.len() + s.leases.len() < 3
                    && !s.invites.contains_key(&capability),
                "Invalid invitation"
            );
            s.invites.insert(capability, expires);
        }
        Request::Exchange {
            session,
            capability,
        } => {
            let s = st.sessions.get_mut(&session).context("Unknown session")?;
            ensure!(
                s.invites.remove(&capability).is_some_and(|e| e > now()),
                "Spent or expired invitation"
            );
            let lease = token();
            s.leases.insert(
                lease.clone(),
                Lease {
                    expires: s.expires,
                    slots: Arc::new(Semaphore::new(2)),
                },
            );
            response.credential = Some(lease);
            response.expires = Some(s.expires);
        }
        Request::Poll { session, host } => {
            let s = st.host(&session, &host)?;
            s.seen = now();
            for (id, p) in &mut s.pending {
                if !p.announced {
                    p.announced = true;
                    response.incoming.push(Incoming {
                        channel: id.clone(),
                        service: p.service.clone(),
                    })
                }
            }
        }
        Request::End { session, host } => {
            st.host(&session, &host)?;
            st.sessions.remove(&session);
        }
        Request::Connect {
            session,
            lease,
            service,
        } => {
            let s = st.sessions.get_mut(&session).context("Unknown session")?;
            let l = s.leases.get(&lease).context("Invalid lease")?;
            ensure!(
                l.expires > now() && s.pending.len() < 8,
                "Expired or busy session"
            );
            let _slot = l.slots.clone().try_acquire_owned()?;
            let expires = l.expires;
            let budget = s.budget.clone();
            let stop = s.stop.subscribe();
            let id = token();
            let (tx, rx) = oneshot::channel();
            s.pending.insert(
                id.clone(),
                Pending {
                    send: tx,
                    service,
                    created: now(),
                    announced: false,
                },
            );
            drop(st);
            let paired = timeout(Duration::from_secs(4), rx).await;
            {
                let mut st = state.lock().await;
                if let Some(s) = st.sessions.get_mut(&session) {
                    s.pending.remove(&id);
                }
            }
            let host_stream = paired??;
            send(&mut stream, &response).await?;
            return bridge(stream, host_stream, budget, stop, expires).await;
        }
        Request::Attach {
            session,
            host,
            channel,
        } => {
            let s = st.host(&session, &host)?;
            let pending = s.pending.remove(&channel).context("Spent channel")?;
            drop(st);
            send(&mut stream, &response).await?;
            let _ = pending.send.send(stream);
            return Ok(());
        }
    }
    drop(st);
    send(&mut stream, &response).await
}
/// Operator-provisioned TLS endpoint. Exposes no target-address or execution API.
pub async fn serve(
    listener: TcpListener,
    cert: Vec<u8>,
    key: Vec<u8>,
    credential: String,
) -> Result<()> {
    ensure!(
        valid_token(&credential),
        "Operator credential must be 64 hex characters"
    );
    let cfg = rustls::ServerConfig::builder_with_provider(Arc::new(
        rustls::crypto::ring::default_provider(),
    ))
    .with_protocol_versions(&[&rustls::version::TLS13])?
    .with_no_client_auth()
    .with_single_cert(
        vec![rustls::pki_types::CertificateDer::from(cert)],
        rustls::pki_types::PrivateKeyDer::try_from(key).map_err(anyhow::Error::msg)?,
    )?;
    let tls = tokio_rustls::TlsAcceptor::from(Arc::new(cfg));
    let slots = Arc::new(Semaphore::new(MAX_CONNECTIONS));
    let state = Arc::new(Mutex::new(State {
        sessions: BTreeMap::new(),
        credential,
    }));
    let cleaner = state.clone();
    let cleanup = tokio::spawn(async move {
        loop {
            tokio::time::sleep(Duration::from_secs(1)).await;
            cleaner.lock().await.prune();
        }
    });
    struct Abort(tokio::task::JoinHandle<()>);
    impl Drop for Abort {
        fn drop(&mut self) {
            self.0.abort()
        }
    }
    let _cleanup = Abort(cleanup);
    loop {
        let (tcp, _) = listener.accept().await?;
        let Ok(slot) = slots.clone().try_acquire_owned() else {
            continue;
        };
        let tls = tls.clone();
        let state = state.clone();
        tokio::spawn(async move {
            let _slot = slot;
            let Ok(Ok(stream)) = timeout(Duration::from_secs(5), tls.accept(tcp)).await else {
                return;
            };
            // Bad protocol/authentication closes the channel; no credential is logged.
            // Errors before dispatch can receive no reply. Clients surface a refused/unavailable relay.
            let _ = stream.get_ref().0.set_nodelay(true);
            let _ = handle(stream, state).await;
        });
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn traffic_budget_is_aggregate_and_bounded() {
        let mut b = Budget {
            total: 0,
            second: 1,
            bytes: 0,
        };
        b.charge(BYTES_PER_SECOND, 1).unwrap();
        assert!(b.charge(1, 1).is_err());
        b.charge(1, 2).unwrap();
        b.total = MAX_BYTES;
        assert!(b.charge(1, 3).is_err());
    }
    #[test]
    fn protocol_has_no_arbitrary_target_or_control() {
        assert!(serde_json::from_str::<Request>(
            r#"{"action":"connect","session":"s","lease":"x","service":"control"}"#
        )
        .is_err());
        assert!(serde_json::from_str::<Request>(r#"{"action":"connect","session":"s","lease":"x","service":"game","target":"127.0.0.1:22"}"#).is_err());
    }
}
