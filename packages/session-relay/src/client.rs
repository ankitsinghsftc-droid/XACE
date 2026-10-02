use crate::*;
use std::sync::atomic::{AtomicU8, Ordering};
use tokio::{
    net::TcpListener,
    sync::{watch, Semaphore},
    task::JoinSet,
};
pub struct HostBridge {
    client: Client,
    pub session: String,
    host: String,
    stop: watch::Sender<bool>,
    healthy: Arc<AtomicU8>,
}
impl Drop for HostBridge {
    fn drop(&mut self) {
        let _ = self.stop.send(true);
        let c = self.client.clone();
        let session = self.session.clone();
        let host = self.host.clone();
        runtime().spawn(async move {
            let _ = c.request(Request::End { session, host }).await;
        });
    }
}
impl HostBridge {
    pub fn start(config: Config, package: SocketAddr, game: SocketAddr) -> Result<Self> {
        ensure!(
            package.ip().is_loopback() && game.ip().is_loopback(),
            "Relay targets must be loopback"
        );
        let credential = config
            .host_credential
            .clone()
            .context("This Player has no relay hosting credential")?;
        let client = Client::new(config)?;
        let response = runtime().block_on(client.request(Request::Register { credential }))?;
        let session = response.session.context("Missing relay session")?;
        let host = response.credential.context("Missing host credential")?;
        let expires = response.expires.context("Missing relay expiry")?;
        let (stop, mut cancelled) = watch::channel(false);
        let healthy = Arc::new(AtomicU8::new(0));
        let c = client.clone();
        let s = session.clone();
        let h = host.clone();
        let health = healthy.clone();
        runtime().spawn(async move {
            let work = async {
                let mut tasks = JoinSet::new();
                let mut interrupted = None;
                loop {
                    ensure!(now() < expires, "Relay session expired");
                    let response = c
                        .request(Request::Poll {
                            session: s.clone(),
                            host: h.clone(),
                        })
                        .await;
                    let response = match response {
                        Ok(response) => {
                            interrupted = None;
                            health.store(0, Ordering::Release);
                            response
                        }
                        Err(error) => {
                            health.store(1, Ordering::Release);
                            let since = interrupted.get_or_insert_with(std::time::Instant::now);
                            if since.elapsed() >= Duration::from_secs(8) {
                                return Err(error);
                            }
                            tokio::time::sleep(Duration::from_millis(200)).await;
                            continue;
                        }
                    };
                    ensure!(response.incoming.len() <= 8, "Invalid relay queue");
                    for incoming in response.incoming {
                        ensure!(tasks.len() < 8, "Relay host busy");
                        let c = c.clone();
                        let s = s.clone();
                        let h = h.clone();
                        let target = match incoming.service {
                            Service::Package => package,
                            Service::Game => game,
                        };
                        tasks.spawn(async move {
                            let mut remote = c
                                .connect(Request::Attach {
                                    session: s,
                                    host: h,
                                    channel: incoming.channel,
                                })
                                .await?;
                            let mut local =
                                timeout(Duration::from_secs(3), TcpStream::connect(target))
                                    .await??;
                            local.set_nodelay(true)?;
                            tokio::io::copy_bidirectional(&mut local, &mut remote).await?;
                            Ok::<(), anyhow::Error>(())
                        });
                    }
                    while tasks.try_join_next().is_some() {}
                    tokio::time::sleep(Duration::from_millis(100)).await;
                }
                #[allow(unreachable_code)]
                Ok::<(), anyhow::Error>(())
            };
            tokio::select! {_=work=>{},_=cancelled.changed()=>{}}
            health.store(2, Ordering::Release);
            // Dropping the JoinSet fences all tunnels; the local authority is never replaced.
        });
        Ok(Self {
            client,
            session,
            host,
            stop,
            healthy,
        })
    }
    pub fn healthy(&self) -> bool {
        self.healthy.load(Ordering::Acquire) == 0
    }
    pub fn health_message(&self) -> &'static str {
        match self.healthy.load(Ordering::Acquire) {
            0 => "connected",
            1 => "Relay connection interrupted. Reconnecting...",
            _ => "Relay connection lost. End this session and retry.",
        }
    }
    pub fn publish(&self, expires: u64) -> Result<Route> {
        ensure!(
            self.healthy(),
            "Relay connection lost. End this session and retry."
        );
        let capability = token();
        runtime().block_on(self.client.request(Request::Publish {
            session: self.session.clone(),
            host: self.host.clone(),
            capability: capability.clone(),
            expires,
        }))?;
        Ok(Route {
            session: self.session.clone(),
            capability,
        })
    }
}
pub struct GuestBridge {
    pub package: SocketAddr,
    pub game: SocketAddr,
    stop: watch::Sender<bool>,
}
impl Drop for GuestBridge {
    fn drop(&mut self) {
        let _ = self.stop.send(true);
    }
}
impl GuestBridge {
    pub fn start(config: Config, route: Route) -> Result<Self> {
        let client = Client::new(config)?;
        let response = runtime().block_on(client.request(Request::Exchange {
            session: route.session.clone(),
            capability: route.capability,
        }))?;
        let lease = response.credential.context("Missing relay lease")?;
        let expires = response.expires.context("Missing relay expiry")?;
        let (a, b) = runtime().block_on(async {
            Ok::<_, anyhow::Error>((
                TcpListener::bind(loopback(0)).await?,
                TcpListener::bind(loopback(0)).await?,
            ))
        })?;
        let package = a.local_addr()?;
        let game = b.local_addr()?;
        let (stop, rx) = watch::channel(false);
        for (listener, service) in [(a, Service::Package), (b, Service::Game)] {
            let c = client.clone();
            let session = route.session.clone();
            let lease = lease.clone();
            let mut cancelled = rx.clone();
            runtime().spawn(async move{
                let work=async {
                    let slots=Arc::new(Semaphore::new(2));let mut tasks=JoinSet::new();
                    loop {
                        let (mut local,_)=listener.accept().await?;let Ok(slot)=slots.clone().try_acquire_owned() else{continue};
                        let c=c.clone();let session=session.clone();let lease=lease.clone();let service=service.clone();
                        tasks.spawn(async move{
                            let _slot=slot;local.set_nodelay(true)?;
                            let mut remote=c.connect(Request::Connect{session,lease,service}).await?;
                            tokio::io::copy_bidirectional(&mut local,&mut remote).await?;Ok::<(),anyhow::Error>(())
                        });
                        while tasks.try_join_next().is_some(){}
                    }
                    #[allow(unreachable_code)] Ok::<(),anyhow::Error>(())
                };
                tokio::select!{_=work=>{},_=cancelled.changed()=>{},_=tokio::time::sleep(Duration::from_secs(expires.saturating_sub(now())))=>{}}
            });
        }
        Ok(Self {
            package,
            game,
            stop,
        })
    }
}
