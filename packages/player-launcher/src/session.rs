//! Reachable private-network invitation and data-only acquisition. No gameplay logic.
use crate::distribution::{digest, safe_path, FileRecord};
use crate::lifecycle::{Authority, Launch};
use anyhow::{bail, ensure, Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    collections::BTreeSet,
    fs,
    io::{Read, Seek, SeekFrom, Write},
    net::{IpAddr, Ipv4Addr, SocketAddr, TcpListener, TcpStream, UdpSocket},
    path::{Path, PathBuf},
    
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        Arc, Mutex,
    },
    thread,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
const MAX_FRAME: usize = 1024 * 1024;
const CHUNK: usize = 64 * 1024;
const MAX_PACKAGE: u64 = 512 * 1024 * 1024;
const INVITE_SECONDS: u64 = 600;
fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}
fn private(ip: IpAddr) -> bool {
    matches!(ip, IpAddr::V4(v) if v.is_private() || v.is_loopback() || v.is_link_local())
}
pub fn local_address() -> Result<IpAddr> {
    if let Ok(value) = std::env::var("XACE_SESSION_ADDRESS") {
        let ip: IpAddr = value.parse()?;
        ensure!(private(ip), "Choose a private-network address");
        return Ok(ip);
    }
    let socket = UdpSocket::bind((Ipv4Addr::UNSPECIFIED, 0))?;
    // Route selection only; connect sends no datagram.
    if socket.connect("192.0.2.1:9").is_ok() {
        let ip = socket.local_addr()?.ip();
        if private(ip) {
            return Ok(ip);
        }
    }
    Ok(IpAddr::V4(Ipv4Addr::LOCALHOST))
}
fn send(stream: &mut TcpStream, value: &Value) -> Result<()> {
    let bytes = serde_json::to_vec(value)?;
    ensure!(
        bytes.len() <= MAX_FRAME,
        "Session message exceeds size limit"
    );
    stream.write_all(&(bytes.len() as u32).to_le_bytes())?;
    stream.write_all(&bytes)?;
    Ok(())
}
fn receive(stream: &mut TcpStream, limit: usize) -> Result<Value> {
    fn exact(stream: &mut TcpStream, mut bytes: &mut [u8], deadline: Instant) -> Result<()> {
        while !bytes.is_empty() {
            let remaining = deadline
                .checked_duration_since(Instant::now())
                .context("Session request timed out")?;
            stream.set_read_timeout(Some(remaining))?;
            let count = stream.read(bytes)?;
            ensure!(count > 0, "Session connection closed");
            bytes = &mut bytes[count..];
        }
        Ok(())
    }
    let deadline = Instant::now() + Duration::from_secs(5);
    let mut prefix = [0; 4];
    exact(stream, &mut prefix, deadline)?;
    let len = u32::from_le_bytes(prefix) as usize;
    ensure!(len > 0 && len <= limit, "Invalid session message size");
    let mut bytes = vec![0; len];
    exact(stream, &mut bytes, deadline)?;
    Ok(serde_json::from_slice(&bytes)?)
}
fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}
fn unhex(raw: &str, limit: usize) -> Result<Vec<u8>> {
    ensure!(
        raw.len() % 2 == 0 && raw.len() / 2 <= limit && raw.is_ascii(),
        "Invalid invite or download encoding"
    );
    (0..raw.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&raw[i..i + 2], 16).map_err(Into::into))
        .collect()
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Invite {
    pub schema: String,
    pub endpoint: SocketAddr,
    pub token: String,
    pub descriptor_sha256: String,
    pub expires_at: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub relay: Option<xace_session_relay::Route>,
}
impl Invite {
    pub fn parse(code: &str) -> Result<Self> {
        ensure!(code.len() <= 4096, "Invite is too long");
        let value: Self = serde_json::from_slice(&unhex(
            code.trim()
                .strip_prefix("XACE1-")
                .context("Paste a complete XACE invite code")?,
            2048,
        )?)?;
        ensure!(
            ((value.schema == "xace.invite.v1" && value.relay.is_none())
                || (value.schema == "xace.invite.v2" && value.relay.is_some()))
                && private(value.endpoint.ip())
                && value.endpoint.port() > 0,
            "Invite requires a reachable private network"
        );
        ensure!(
            value.token.len() == 64 && value.descriptor_sha256.len() == 64,
            "Invalid invite"
        );
        ensure!(
            now() < value.expires_at,
            "This invite has expired. Ask the host for a new one."
        );
        if let Some(route) = &value.relay {
            ensure!(
                uuid::Uuid::parse_str(&route.session).is_ok()
                    && xace_session_relay::valid_token(&route.capability),
                "Invalid relay invitation"
            );
        }
        Ok(value)
    }
    fn code(&self) -> Result<String> {
        Ok(format!("XACE1-{}", hex(&serde_json::to_vec(self)?)))
    }
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Descriptor {
    schema: String,
    files: Vec<FileRecord>,
    receipt: Value,
    runtime_sha256: String,
    session_id: String,
    authority_incarnation: String,
}
struct Grant {
    token: String,
    expires: u64,
    ticket: Value,
    spent: bool,
}
struct Shared {
    grants: Vec<Grant>,
    descriptor: String,
    root: PathBuf,
}
struct PendingDirectory(Option<PathBuf>);
impl Drop for PendingDirectory {
    fn drop(&mut self) {
        if let Some(path) = &self.0 {
            if path.file_name().is_some_and(|n| {
                n.to_string_lossy()
                    .strip_prefix("session-")
                    .is_some_and(|v| uuid::Uuid::parse_str(v).is_ok())
            }) {
                let _ = fs::remove_dir_all(path);
            }
        }
    }
}

pub struct Host {
    relay: Option<xace_session_relay::client::HostBridge>,
    runtime: Authority,
    stop: Arc<AtomicBool>,
    shared: Arc<Mutex<Shared>>,
    endpoint: SocketAddr,
    pub engine_endpoint: SocketAddr,
    pub ticket: PathBuf,
    log: PathBuf,
    directory: PathBuf,
    log_offset: u64,
    member_states: std::collections::BTreeMap<u64, String>,
}
impl Drop for Host {
    fn drop(&mut self) {
        self.relay.take();
        self.stop.store(true, Ordering::Release);
        self.runtime.stop();
        if self
            .directory
            .file_name()
            .is_some_and(|n| n.to_string_lossy().starts_with("session-"))
        {
            let _ = fs::remove_dir_all(&self.directory);
        }
    }
}
fn controllers(root: &Path) -> Result<Vec<u64>> {
    let cgs: Value = serde_json::from_slice(&fs::read(root.join("package/game.cgs.json"))?)?;
    let settings: Value = serde_json::from_slice(&fs::read(
        root.join("package/presentation/player/settings.json"),
    )?)?;
    let owner = settings["controller_id"]
        .as_u64()
        .context("Missing local player controller")?;
    let modes = cgs["modes"].as_array().context("Missing game modes")?;
    let mode = modes
        .iter()
        .find(|m| m["is_default"] == true)
        .or_else(|| modes.first())
        .context("Missing game mode")?;
    let mut ids = BTreeSet::new();
    for actor in mode["actors"].as_array().context("Missing actors")? {
        for comp in actor["components"]
            .as_array()
            .context("Missing components")?
        {
            if comp["name"] == "COMP_INPUT_V1" && comp["defaults"]["control_type"] == "HUMAN" {
                let id = comp["defaults"]["controller_id"]
                    .as_u64()
                    .context("Missing controller identity")?;
                ensure!(
                    id > 0 && actor["spawn_count"].as_u64().unwrap_or(1) == 1 && ids.insert(id),
                    "Each player needs a distinct controller"
                );
            }
        }
    }
    ensure!(
        ids.remove(&owner),
        "Local player controller is not in this game"
    );
    ensure!(
        ids.len() < 4,
        "This session profile supports up to four players"
    );
    let mut result = vec![owner];
    result.extend(ids);
    Ok(result)
}
impl Host {
    pub fn start(root: &Path, install: &Path, preferred: u16) -> Result<Self> {
        let ip = if xace_session_relay::Config::from_env()?.is_some() {
            IpAddr::V4(Ipv4Addr::LOCALHOST)
        } else {
            local_address()?
        };
        let reserve = TcpListener::bind((ip, preferred)).or_else(|_| TcpListener::bind((ip, 0)))?;
        let engine_endpoint = reserve.local_addr()?;
        let listener = TcpListener::bind((ip, 0))?;
        let endpoint = listener.local_addr()?;
        listener.set_nonblocking(true)?;
        let directory = install.join(format!("session-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&directory)?;
        let mut pending_directory = PendingDirectory(Some(directory.clone()));
        let ticket = directory.join("ticket.json");
        // Keep the authoritative journal after End; only ephemeral tickets are removed.
        let history = install.join("session-history");
        fs::create_dir_all(&history)?;
        let log = history.join(format!(
            "{}.jsonl",
            directory.file_name().unwrap().to_string_lossy()
        ));
        let ids = controllers(root)?;
        let pkg = root.join("package");
        drop(reserve);
        let mut runtime = Authority::start(&Launch {
            package: &pkg, ticket: &ticket, journal: &log,
            endpoint: engine_endpoint, controllers: &ids,
        })?;
        let result = (|| -> Result<(Vec<Grant>, String)> {
            let started = Instant::now();
            let tickets_ready = || {
                ticket.exists()
                    && (2..=ids.len())
                        .all(|peer| directory.join(format!("ticket.peer{peer}.json")).exists())
            };
            while started.elapsed() < Duration::from_secs(8) && !tickets_ready() {
                ensure!(
                    runtime.try_wait()?.is_none(),
                    "Game authority stopped before readiness"
                );
                thread::sleep(Duration::from_millis(20));
            }
            ensure!(
                tickets_ready(),
                "Game authority did not finish preparing player slots. Retry."
            );
            let owner: Value = serde_json::from_slice(
                &fs::read(&ticket).context("Game authority did not become ready")?,
            )?;
            let mut grants = Vec::new();
            for peer in 2..=ids.len() {
                let path = directory.join(format!("ticket.peer{peer}.json"));
                let mut t: Value = serde_json::from_slice(&fs::read(path)?)?;
                t["endpoint_port"] = engine_endpoint.port().into();
                grants.push(Grant {
                    token: String::new(),
                    expires: 0,
                    ticket: t,
                    spent: false,
                });
            }
            let receipt: Value = serde_json::from_slice(
                &fs::read(root.join("admission.json"))
                    .context("Update your Player install to enable invitations")?,
            )?;
            let manifest: Value =
                serde_json::from_slice(&fs::read(pkg.join("playable.manifest.json"))?)?;
            let mut files: Vec<FileRecord> = serde_json::from_value(manifest["files"].clone())?;
            let bytes = fs::read(pkg.join("playable.manifest.json"))?;
            files.push(FileRecord {
                path: "playable.manifest.json".into(),
                size: bytes.len() as u64,
                sha256: digest(&bytes),
            });
            let descriptor = Descriptor {
                schema: "xace.session_package.v1".into(),
                files,
                receipt,
                runtime_sha256: digest(&fs::read(pkg.join("runtime/xace_runtime.exe"))?),
                session_id: owner["offer"]["contract"]["epoch"]["session_id"]
                    .as_str()
                    .context("Missing session")?
                    .into(),
                authority_incarnation: owner["offer"]["contract"]["epoch"]["authority_incarnation"]
                    .as_str()
                    .context("Missing incarnation")?
                    .into(),
            };
            validate_descriptor(&descriptor)?;
            Ok((grants, serde_json::to_string(&descriptor)?))
        })();
        let (grants, descriptor) = match result {
            Ok(r) => r,
            Err(e) => {
                runtime.stop();
                return Err(e);
            }
        };
        let shared = Arc::new(Mutex::new(Shared {
            grants,
            descriptor,
            root: pkg,
        }));
        let stop = Arc::new(AtomicBool::new(false));
        let thread_shared = shared.clone();
        let thread_stop = stop.clone();
        thread::spawn(move || serve(listener, thread_shared, thread_stop));
        pending_directory.0.take();
        Ok(Self {
            relay: None,
            runtime,
            stop,
            shared,
            endpoint,
            engine_endpoint,
            ticket,
            log,
            directory,
            log_offset: 0,
            member_states: Default::default(),
        })
    }
    pub fn runtime_pid(&self) -> u32 {
        self.runtime.id()
    }
    pub fn owns_invite(&self, invite: &Invite) -> bool {
        match &invite.relay {
            Some(route) => self
                .relay
                .as_ref()
                .is_some_and(|r| r.session == route.session),
            None => self.endpoint == invite.endpoint,
        }
    }
    pub fn invite(&mut self) -> Result<Value> {
        if self.relay.is_none() {
            if let Some(config) = xace_session_relay::Config::from_env()? {
                self.relay = Some(xace_session_relay::client::HostBridge::start(
                    config,
                    self.endpoint,
                    self.engine_endpoint,
                )?);
            }
        }
        let mut shared = self
            .shared
            .lock()
            .map_err(|_| anyhow::anyhow!("Session unavailable"))?;
        let descriptor_sha256 = digest(shared.descriptor.as_bytes());
        let grant=shared.grants.iter_mut().find(|g|!g.spent && (g.token.is_empty() || g.expires<=now())).context("No player slots are available. Let an unused invite expire, or end this session and start a new one.")?;
        let token = format!(
            "{}{}",
            uuid::Uuid::new_v4().simple(),
            uuid::Uuid::new_v4().simple()
        );
        let expires = now() + INVITE_SECONDS;
        let relay = self
            .relay
            .as_ref()
            .map(|r| r.publish(expires))
            .transpose()?;
        // Failed relay publication must not reserve a local gameplay slot.
        grant.token = token;
        grant.expires = expires;
        let invite = Invite {
            schema: if relay.is_some() {
                "xace.invite.v2"
            } else {
                "xace.invite.v1"
            }
            .into(),
            relay,
            endpoint: self.endpoint,
            token: grant.token.clone(),
            descriptor_sha256,
            expires_at: grant.expires,
        };
        Ok(
            json!({"code":invite.code()?,"expires_at":invite.expires_at,"message":if self.relay.is_some(){"Share this code with a friend using the same trusted relay service. It expires in 10 minutes."}else{"Share this code with a friend on the same private network. It expires in 10 minutes."}}),
        )
    }
    pub fn members(&mut self) -> Result<Value> {
        ensure!(
            self.runtime.try_wait()?.is_none(),
            "The host stopped. End this session and Play again."
        );
        if let Ok(mut file) = fs::File::open(&self.log) {
            if file.metadata()?.len() < self.log_offset {
                self.log_offset = 0;
                self.member_states.clear();
            }
            file.seek(SeekFrom::Start(self.log_offset))?;
            let mut bytes = Vec::new();
            file.take(1024 * 1024).read_to_end(&mut bytes)?;
            if let Some(end) = bytes.iter().rposition(|b| *b == b'\n') {
                for line in bytes[..=end].split(|b| *b == b'\n') {
                    if let Ok(v) = serde_json::from_slice::<Value>(line) {
                        if let Some(peer) = v["peer_id"].as_u64() {
                            if v["kind"] == "baseline_verified" {
                                self.member_states.insert(peer, "Playing".into());
                            }
                            if v["kind"] == "membership" {
                                if v["action"] == "admitted" {
                                    self.member_states.insert(peer, "Joining".into());
                                } else if v["action"] == "disconnected" {
                                    self.member_states.insert(peer, "Disconnected".into());
                                }
                            }
                        }
                    }
                }
                self.log_offset += end as u64 + 1;
            }
        }
        Ok(
            json!({"members":self.member_states.iter().map(|(peer,state)|json!({"player":peer,"state":state})).collect::<Vec<_>>(),"scope":if self.relay.is_some(){"relay"}else{"private_network"},"transport_health":self.relay.as_ref().map(|r|r.health_message()),"session_directory":self.directory}),
        )
    }
}
fn validate_descriptor(d: &Descriptor) -> Result<()> {
    ensure!(
        d.schema == "xace.session_package.v1" && !d.files.is_empty() && d.files.len() <= 4096,
        "Unsupported game download"
    );
    let mut names = BTreeSet::new();
    let mut total = 0u64;
    for file in &d.files {
        safe_path(&file.path)?;
        ensure!(
            names.insert(file.path.to_lowercase()),
            "Duplicate game path"
        );
        let suffix = Path::new(&file.path)
            .extension()
            .and_then(|x| x.to_str())
            .unwrap_or("")
            .to_lowercase();
        ensure!(
            file.path == "runtime/xace_runtime.exe"
                || ["json", "png", "wav", "bin"].contains(&suffix.as_str()),
            "Game download contains executable or unsupported content"
        );
        total = total
            .checked_add(file.size)
            .context("Download size overflow")?;
        ensure!(
            file.size <= 128 * 1024 * 1024 && total <= MAX_PACKAGE,
            "Game download exceeds this Player's size limit"
        );
        ensure!(
            file.sha256.len() == 64 && file.sha256.bytes().all(|b| b.is_ascii_hexdigit()),
            "Invalid game checksum"
        );
    }
    for required in [
        "playable.manifest.json",
        "game.cgs.json",
        "execution_plan.json",
        "world.json",
        "world.manifest.json",
        "runtime/xace_runtime.exe",
        "presentation/player/settings.json",
    ] {
        ensure!(names.contains(required), "Game download is incomplete");
    }
    ensure!(
        d.receipt["schema"] == "xace.player.admission.v1"
            && d.receipt["runtime_sha256"] == d.runtime_sha256,
        "Invalid game admission receipt"
    );
    if let Some(catalog) = d.receipt["presentation"]["catalog"].as_str() {
        safe_path(catalog)?;
        ensure!(
            names.contains(&catalog.to_lowercase()),
            "Missing presentation catalog"
        );
    }
    Ok(())
}
fn serve(listener: TcpListener, shared: Arc<Mutex<Shared>>, stop: Arc<AtomicBool>) {
    let active = Arc::new(AtomicUsize::new(0));
    while !stop.load(Ordering::Acquire) {
        match listener.accept() {
            Ok((mut stream, addr)) => {
                if !private(addr.ip()) || active.load(Ordering::Acquire) >= 4 {
                    continue;
                }
                active.fetch_add(1, Ordering::AcqRel);
                let active = active.clone();
                let shared = shared.clone();
                let stop = stop.clone();
                thread::spawn(move || {
                    let _ = stream.set_nonblocking(false);
                    let _ = stream.set_read_timeout(Some(Duration::from_secs(3)));
                    let _ = stream.set_write_timeout(Some(Duration::from_secs(3)));
                    let result = receive(&mut stream, 8192).and_then(|request| {
                        ensure!(!stop.load(Ordering::Acquire), "Host ended this session");
                        let mut state = shared
                            .lock()
                            .map_err(|_| anyhow::anyhow!("Session unavailable"))?;
                        ensure!(
                            request["schema"] == "xace.invite_request.v1",
                            "Unsupported invite protocol"
                        );
                        let token = request["token"].as_str().context("Missing invite")?;
                        let index = state
                            .grants
                            .iter()
                            .position(|g| g.token == token && !g.token.is_empty())
                            .context("Invite not found")?;
                        ensure!(
                            !state.grants[index].spent,
                            "This invite was already used. Reconnect through the original Player."
                        );
                        ensure!(
                            now() < state.grants[index].expires,
                            "This invite has expired. Ask for a new one."
                        );
                        match request["action"].as_str() {
                            Some("describe") => Ok(json!({"descriptor":state.descriptor})),
                            Some("file") => {
                                let name = request["path"].as_str().context("Missing file")?;
                                ensure!(
                                    name != "runtime/xace_runtime.exe",
                                    "Executable download is forbidden"
                                );
                                let d: Descriptor = serde_json::from_str(&state.descriptor)?;
                                let record = d
                                    .files
                                    .iter()
                                    .find(|f| f.path == name)
                                    .context("File is not in this game")?;
                                let offset =
                                    request["offset"].as_u64().context("Missing offset")?;
                                ensure!(offset <= record.size, "Invalid download offset");
                                let mut file = fs::File::open(state.root.join(safe_path(name)?))?;
                                file.seek(SeekFrom::Start(offset))?;
                                let mut bytes = vec![0; CHUNK.min((record.size - offset) as usize)];
                                file.read_exact(&mut bytes)?;
                                Ok(json!({"offset":offset,"data":hex(&bytes)}))
                            }
                            Some("redeem") => {
                                ensure!(
                                    request["descriptor_sha256"]
                                        == digest(state.descriptor.as_bytes()),
                                    "Game verification did not match"
                                );
                                state.grants[index].spent = true;
                                Ok(json!({"ticket":state.grants[index].ticket}))
                            }
                            _ => bail!("Unsupported session request"),
                        }
                    });
                    let value = match result {
                        Ok(v) => json!({"schema":"xace.invite_response.v1","ok":true,"result":v}),
                        Err(e) => {
                            json!({"schema":"xace.invite_response.v1","ok":false,"message":e.to_string()})
                        }
                    };
                    let _ = send(&mut stream, &value);
                    active.fetch_sub(1, Ordering::AcqRel);
                });
            }
            Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                thread::sleep(Duration::from_millis(10))
            }
            Err(_) => break,
        }
    }
}
fn call(invite: &Invite, mut request: Value) -> Result<Value> {
    ensure!(
        now() < invite.expires_at,
        "This invite expired before joining finished"
    );
    request["token"] = invite.token.clone().into();
    request["schema"] = "xace.invite_request.v1".into();
    let mut stream = TcpStream::connect_timeout(&invite.endpoint, Duration::from_secs(3))
        .context("Host is unreachable. Check that you are on the same private network.")?;
    stream.set_read_timeout(Some(Duration::from_secs(5)))?;
    stream.set_write_timeout(Some(Duration::from_secs(5)))?;
    send(&mut stream, &request)?;
    let response = receive(&mut stream, MAX_FRAME).with_context(|| {
        format!(
            "Host reply failed during {}",
            request["action"].as_str().unwrap_or("join")
        )
    })?;
    ensure!(
        response["schema"] == "xace.invite_response.v1",
        "Unsupported invite response"
    );
    ensure!(
        response["ok"] == true,
        "{}",
        response["message"]
            .as_str()
            .unwrap_or("Host refused the join")
    );
    Ok(response["result"].clone())
}
fn open_cache_lease(path: &Path, create: bool) -> Result<fs::File> {
    let mut options = fs::OpenOptions::new();
    options.write(true).create_new(create);
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        options.share_mode(0);
    }
    Ok(options.open(path)?)
}

pub struct Joined {
    pub relay: Option<xace_session_relay::client::GuestBridge>,
    pub lease: Option<fs::File>,
    pub package: PathBuf,
    pub receipt: PathBuf,
    pub ticket: PathBuf,
    pub endpoint: SocketAddr,
}
pub fn acquire(
    code: &str,
    trusted_root: &Path,
    install: &Path,
    mut progress: impl FnMut(&str) -> Result<()>,
) -> Result<Joined> {
    let mut invite = Invite::parse(code)?;
    progress("Contacting host...")?;
    let mut relay = if let Some(route) = invite.relay.clone() {
        progress("Connecting securely through relay...")?;
        let config = xace_session_relay::Config::from_env()?.context(
            "Install the trusted relay service configuration to join this Internet session",
        )?;
        Some(xace_session_relay::client::GuestBridge::start(
            config, route,
        )?)
    } else {
        None
    };
    if let Some(bridge) = &relay {
        invite.endpoint = bridge.package;
    }

    let response = call(&invite, json!({"action":"describe"}))?;
    let raw = response["descriptor"]
        .as_str()
        .context("Missing game descriptor")?;
    ensure!(
        digest(raw.as_bytes()) == invite.descriptor_sha256,
        "Game package changed. Ask for a new invite."
    );
    let d: Descriptor = serde_json::from_str(raw)?;
    validate_descriptor(&d)?;
    let runtime = trusted_root.join("package/runtime/xace_runtime.exe");
    ensure!(digest(&fs::read(&runtime)?)==d.runtime_sha256,"This game needs a different trusted Player runtime. Install its verified Player release first.");
    let cache = install.join("session-cache");
    fs::create_dir_all(&cache)?;
    let cache_lock = crate::distribution::InstallLock::acquire(&cache)?;
    // Only our UUID directories are candidates; an exclusive lease protects live Players.
    for entry in fs::read_dir(&cache)? {
        let entry = entry?;
        if uuid::Uuid::parse_str(&entry.file_name().to_string_lossy()).is_err()
            || !entry.file_type()?.is_dir()
        {
            continue;
        }
        let path = entry.path();
        if let Ok(lease) = open_cache_lease(&path.join("lease"), false) {
            drop(lease);
            ensure!(
                path.parent() == Some(cache.as_path()),
                "Invalid cache cleanup path"
            );
            fs::remove_dir_all(path)?;
        }
    }
    ensure!(
        fs::read_dir(&cache)?
            .filter_map(Result::ok)
            .filter(|e| e.file_type().is_ok_and(|t| t.is_dir()))
            .count()
            < 8,
        "Downloaded game storage is busy. Close other Player windows and retry."
    );
    let stage = cache.join(uuid::Uuid::new_v4().to_string());
    fs::create_dir(&stage)?;
    let mut lease = Some(open_cache_lease(&stage.join("lease"), true)?);
    drop(cache_lock);
    let result = (|| -> Result<Joined> {
        let package = stage.join("package");
        fs::create_dir(&package)?;
        let deadline = Instant::now();
        for (index, file) in d.files.iter().enumerate() {
            ensure!(
                deadline.elapsed() < Duration::from_secs(120),
                "Game download timed out. Retry with a new invite."
            );
            progress(&format!(
                "Getting game files: {} of {}",
                index + 1,
                d.files.len()
            ))?;
            let path = package.join(safe_path(&file.path)?);
            fs::create_dir_all(path.parent().unwrap())?;
            if file.path == "runtime/xace_runtime.exe" {
                fs::copy(&runtime, &path)?;
            } else {
                let mut output = fs::OpenOptions::new()
                    .write(true)
                    .create_new(true)
                    .open(&path)?;
                let mut offset = 0;
                while offset < file.size {
                    progress(&format!(
                        "Getting game files: {} of {}",
                        index + 1,
                        d.files.len()
                    ))?;
                    ensure!(
                        deadline.elapsed() < Duration::from_secs(120),
                        "Game download timed out"
                    );
                    let chunk = call(
                        &invite,
                        json!({"action":"file","path":file.path,"offset":offset}),
                    )?;
                    ensure!(
                        chunk["offset"].as_u64() == Some(offset),
                        "Download offset mismatch"
                    );
                    let bytes = unhex(
                        chunk["data"].as_str().context("Missing download data")?,
                        CHUNK,
                    )?;
                    ensure!(
                        !bytes.is_empty() && offset + bytes.len() as u64 <= file.size,
                        "Invalid game download length"
                    );
                    output.write_all(&bytes)?;
                    offset += bytes.len() as u64;
                }
                output.sync_all()?;
            }
            ensure!(
                fs::metadata(&path)?.len() == file.size && digest(&fs::read(&path)?) == file.sha256,
                "Game file failed verification: {}",
                file.path
            );
        }
        progress("Verifying game...")?;
        let manifest_bytes = fs::read(package.join("playable.manifest.json"))?;
        ensure!(
            d.receipt["manifest_sha256"] == digest(&manifest_bytes),
            "Game admission checksum mismatch"
        );
        let manifest: Value = serde_json::from_slice(&manifest_bytes)?;
        let records: Vec<FileRecord> = serde_json::from_value(manifest["files"].clone())?;
        ensure!(
            records.len() + 1 == d.files.len(),
            "Game file inventory mismatch"
        );
        for record in records {
            ensure!(
                d.files.iter().any(|f| f.path == record.path
                    && f.sha256 == record.sha256
                    && f.size == record.size),
                "Game inventory differs from download"
            );
        }
        let receipt = stage.join("admission.json");
        fs::write(&receipt, serde_json::to_vec(&d.receipt)?)?;
        progress("Joining session...")?;
        let redeemed = call(
            &invite,
            json!({"action":"redeem","descriptor_sha256":invite.descriptor_sha256}),
        )?;
        let ticket_value = &redeemed["ticket"];
        let epoch = &ticket_value["offer"]["contract"]["epoch"];
        ensure!(
            epoch["session_id"] == d.session_id
                && epoch["authority_incarnation"] == d.authority_incarnation,
            "Session changed during join"
        );
        let port = ticket_value["endpoint_port"]
            .as_u64()
            .context("Invite is missing the host port")?;
        ensure!(port > 0 && port <= 65535, "Invalid host port");
        let mut ticket_value = ticket_value.clone();
        ticket_value
            .as_object_mut()
            .unwrap()
            .remove("endpoint_port");
        let ticket = stage.join("ticket.json");
        fs::write(&ticket, serde_json::to_vec(&ticket_value)?)?;
        Ok(Joined {
            lease: lease.take(),
            package,
            receipt,
            ticket,
            endpoint: relay
                .as_ref()
                .map(|r| r.game)
                .unwrap_or_else(|| SocketAddr::new(invite.endpoint.ip(), port as u16)),
            relay: relay.take(),
        })
    })();
    if result.is_err() && stage.parent() == Some(cache.as_path()) {
        lease.take();
        let _ = fs::remove_dir_all(&stage);
    }
    result
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn relay_invites_are_versioned_and_validate_routes() {
        let mut invite = Invite {
            schema: "xace.invite.v2".into(),
            endpoint: "127.0.0.1:1234".parse().unwrap(),
            token: "a".repeat(64),
            descriptor_sha256: "b".repeat(64),
            expires_at: now() + 600,
            relay: Some(xace_session_relay::Route {
                session: uuid::Uuid::new_v4().to_string(),
                capability: "c".repeat(64),
            }),
        };
        assert!(Invite::parse(&invite.code().unwrap()).is_ok());
        invite.schema = "xace.invite.v1".into();
        assert!(Invite::parse(&invite.code().unwrap()).is_err());
        invite.schema = "xace.invite.v2".into();
        invite.relay.as_mut().unwrap().capability = "invalid".into();
        assert!(Invite::parse(&invite.code().unwrap()).is_err());
        invite.relay = None;
        assert!(Invite::parse(&invite.code().unwrap()).is_err());
    }
    #[test]
    fn rejects_expired_public_or_malformed_invites() {
        let mut invite = Invite {
            relay: None,
            schema: "xace.invite.v1".into(),
            endpoint: "127.0.0.1:1234".parse().unwrap(),
            token: "a".repeat(64),
            descriptor_sha256: "b".repeat(64),
            expires_at: now() + 60,
        };
        assert!(Invite::parse(&invite.code().unwrap()).is_ok());
        invite.expires_at = 0;
        assert!(Invite::parse(&invite.code().unwrap()).is_err());
        invite.expires_at = now() + 60;
        invite.endpoint = "8.8.8.8:1234".parse().unwrap();
        assert!(Invite::parse(&invite.code().unwrap()).is_err());
        assert!(Invite::parse("XACE1-zz").is_err());
    }
    fn descriptor() -> Descriptor {
        let files = [
            "playable.manifest.json",
            "game.cgs.json",
            "execution_plan.json",
            "world.json",
            "world.manifest.json",
            "runtime/xace_runtime.exe",
            "presentation/player/settings.json",
        ]
        .into_iter()
        .map(|p| FileRecord {
            path: p.into(),
            sha256: "a".repeat(64),
            size: 0,
        })
        .collect();
        Descriptor {
            schema: "xace.session_package.v1".into(),
            files,
            receipt: json!({"schema":"xace.player.admission.v1","runtime_sha256":"a".repeat(64)}),
            runtime_sha256: "a".repeat(64),
            session_id: "session".into(),
            authority_incarnation: "incarnation".into(),
        }
    }
    #[test]
    fn data_only_inventory_is_bounded_and_extensible() {
        let mut value = descriptor();
        validate_descriptor(&value).unwrap();
        value.files.push(FileRecord {
            path: "presentation/resources/arbitrary_new_concept.json".into(),
            sha256: "b".repeat(64),
            size: 10,
        });
        validate_descriptor(&value).unwrap();
        for path in [
            "../escape.json",
            "scripts/logic.gd",
            "extra.pck",
            "plugin.dll",
            "game.cgs.json",
        ] {
            let mut candidate = value.clone();
            candidate.files.last_mut().unwrap().path = path.into();
            assert!(validate_descriptor(&candidate).is_err(), "{path}");
        }
        value.files.last_mut().unwrap().size = 129 * 1024 * 1024;
        assert!(validate_descriptor(&value).is_err());
    }
    #[test]
    fn redemption_is_atomic_scoped_expiring_and_has_no_control_api() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let endpoint = listener.local_addr().unwrap();
        listener.set_nonblocking(true).unwrap();
        let raw = serde_json::to_string(&descriptor()).unwrap();
        let hash = digest(raw.as_bytes());
        let shared = Arc::new(Mutex::new(Shared {
            root: PathBuf::new(),
            descriptor: raw,
            grants: vec![Grant {
                token: "a".repeat(64),
                expires: now() + 60,
                ticket: json!({"peer_id":2}),
                spent: false,
            }],
        }));
        let stop = Arc::new(AtomicBool::new(false));
        let signal = stop.clone();
        let state = shared.clone();
        let worker = thread::spawn(move || serve(listener, state, signal));
        let invite = Invite {
            relay: None,
            schema: "xace.invite.v1".into(),
            endpoint,
            token: "a".repeat(64),
            descriptor_sha256: hash.clone(),
            expires_at: now() + 60,
        };
        assert!(call(&invite, json!({"action":"shutdown"})).is_err());
        assert!(call(
            &invite,
            json!({"action":"redeem","descriptor_sha256":"wrong"})
        )
        .is_err());
        shared.lock().unwrap().grants[0].expires = now() - 1;
        assert!(call(&invite, json!({"action":"describe"})).is_err());
        shared.lock().unwrap().grants[0].expires = now() + 60;
        let redeemed = call(&invite, json!({"action":"redeem","descriptor_sha256":hash})).unwrap();
        assert_eq!(redeemed["ticket"]["peer_id"], 2);
        assert!(call(
            &invite,
            json!({"action":"redeem","descriptor_sha256":invite.descriptor_sha256})
        )
        .is_err());
        stop.store(true, Ordering::Release);
        worker.join().unwrap();
    }
    #[cfg(windows)]
    #[test]
    fn live_cache_lease_cannot_be_reclaimed_until_owner_releases_it() {
        let root = std::env::temp_dir().join(format!("xace-cache-lease-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&root).unwrap();
        let path = root.join("lease");
        let lease = open_cache_lease(&path, true).unwrap();
        assert!(open_cache_lease(&path, false).is_err());
        drop(lease);
        let reclaimed = open_cache_lease(&path, false).unwrap();
        drop(reclaimed);
        fs::remove_file(path).unwrap();
        fs::remove_dir(root).unwrap();
    }
}
