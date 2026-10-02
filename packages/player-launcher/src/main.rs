#![cfg_attr(windows, windows_subsystem = "windows")]
mod distribution;
mod job;
mod session;
use anyhow::{bail, ensure, Context, Result};
use distribution::{activate, materialize, verified};
use job::Job;
use serde_json::{json, Value};
use std::{
    fs,
    io::{self, BufRead, Read, Write},
    path::PathBuf,
    process::{Child, Command, Stdio},
    thread,
    time::{Duration, Instant},
};

struct Owned {
    relay: Option<xace_session_relay::client::GuestBridge>,
    child: Child,
    job: Option<Job>,
    status: PathBuf,
    gate: PathBuf,
    token: String,
    cache: Option<PathBuf>,
    cache_lease: Option<fs::File>,
}
impl Drop for Owned {
    fn drop(&mut self) {
        self.relay.take();
        self.job.take();
        let _ = self.child.kill();
        let _ = self.child.wait();
        let _ = fs::remove_file(&self.status);
        let _ = fs::remove_file(&self.gate);
        let _ = fs::remove_file(self.gate.with_extension("command.json"));
        let _ = fs::remove_file(self.gate.with_extension("view.json"));
        self.cache_lease.take();
        if let Some(cache) = &self.cache {
            if cache
                .parent()
                .is_some_and(|p| p.file_name().is_some_and(|n| n == "session-cache"))
            {
                let _ = fs::remove_dir_all(cache);
            }
        }
    }
}
struct Broker {
    root: PathBuf,
    install: PathBuf,
    digest: String,
    child: Option<Owned>,
    headless: bool,
    capability: String,
    host: Option<session::Host>,
    invite_view: Value,
}
impl Broker {
    fn status(&mut self) -> Result<Value> {
        if let Some(owned) = &mut self.child {
            if owned.child.try_wait()?.is_some() {
                self.child.take();
                self.host.take();
            }
        }
        Ok(
            json!({"state":if self.child.is_some(){"playing"}else{"stopped"},"player_pid":self.child.as_ref().map(|p|p.child.id())}),
        )
    }
    fn play(&mut self, preferred: u16) -> Result<Value> {
        let result = self.launch(preferred, None);
        if result.is_err() {
            self.child.take();
            self.host.take();
        }
        result
    }
    fn launch(&mut self, preferred: u16, joined: Option<session::Joined>) -> Result<Value> {
        let existing = self.status()?;
        if existing["state"] == "playing" {
            return Ok(existing);
        }
        verified(&self.root, &self.digest)?;
        let (package, receipt, ticket, endpoint, cache, cache_lease, relay) =
            if let Some(joined) = joined {
                let cache = joined.package.parent().unwrap().to_path_buf();
                (
                    joined.package,
                    joined.receipt,
                    joined.ticket,
                    joined.endpoint,
                    Some(cache),
                    joined.lease,
                    joined.relay,
                )
            } else {
                self.host = Some(session::Host::start(&self.root, &self.install, preferred)?);
                let host = self.host.as_ref().unwrap();
                (
                    self.root.join("package"),
                    self.root.join("admission.json"),
                    host.ticket.clone(),
                    host.engine_endpoint,
                    None,
                    None,
                    None,
                )
            };
        let port = endpoint.port();
        let token = uuid::Uuid::new_v4().to_string();
        let status = self.install.join(format!("launch-{token}.json"));
        let gate = self.install.join(format!("gate-{token}"));
        let mut command = Command::new(self.root.join("xace-player.exe"));
        command
            .current_dir(&self.root)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        if self.headless {
            command.arg("--headless");
        }
        command
            .arg("--")
            .arg(format!("--package={}", package.display()))
            .arg(format!("--admission={}", receipt.display()))
            .arg(format!("--session-ticket={}", ticket.display()))
            .arg(format!("--session-host={}", endpoint.ip()))
            .arg(format!(
                "--session-control={}",
                gate.with_extension("command.json").display()
            ))
            .arg(format!(
                "--session-view={}",
                gate.with_extension("view.json").display()
            ))
            .arg(format!("--port={port}"))
            .arg(format!("--launch-status={}", status.display()))
            .arg(format!("--launch-token={token}"))
            .arg(format!("--launch-gate={}", gate.display()));
        let started = Instant::now();
        let mut child = command
            .spawn()
            .context("Player could not start. Restore this install and retry.")?;
        let job = match Job::own(&child) {
            Ok(job) => job,
            Err(error) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(error);
            }
        };
        self.child = Some(Owned {
            relay,
            child,
            job: Some(job),
            status: status.clone(),
            gate: gate.clone(),
            token: token.clone(),
            cache,
            cache_lease,
        });
        // The launcher owns one authority; invited Players never create another.
        let result = (|| -> Result<Value> {
            fs::write(&gate, &token)?;
            while started.elapsed() < Duration::from_secs(15) {
                let owned = self.child.as_mut().unwrap();
                ensure!(
                    owned.child.try_wait()?.is_none(),
                    "Player exited before readiness. Retry or restore this install."
                );
                if let Ok(bytes) = fs::read(&status) {
                    if let Ok(value) = serde_json::from_slice::<Value>(&bytes) {
                        if value["schema"] == "xace.player.launch_status.v1"
                            && value["token"] == owned.token
                        {
                            if value["state"] == "failed" {
                                bail!(
                                    "Player could not start: {}",
                                    value["message"].as_str().unwrap_or("unknown error")
                                );
                            }
                            if value["state"] == "playing" {
                                activate(&self.install, &self.digest)?;
                                return Ok(
                                    json!({"state":"playing","player_pid":owned.child.id(),"runtime_pid":self.host.as_ref().map(|h|h.runtime_pid()),"session_mode":if self.host.is_some(){"hosting"}else{"joined"},"port":port,"startup_ms":started.elapsed().as_millis()}),
                                );
                            }
                        }
                    }
                }
                thread::sleep(Duration::from_millis(25));
            }
            bail!("Player did not become ready. Close conflicting software and retry.")
        })();
        if result.is_err() {
            self.host.take();
            self.child.take();
        }
        result
    }
    fn join(&mut self, code: &str) -> Result<Value> {
        let invite = session::Invite::parse(code)?;
        ensure!(
            !self.host.as_ref().is_some_and(|h| h.owns_invite(&invite)),
            "You already host this session. Share its invite with another Player."
        );
        verified(&self.root, &self.digest)?;
        let view = self
            .child
            .as_ref()
            .map(|c| c.gate.with_extension("view.json"));
        let child = &mut self.child;
        let joined = session::acquire(code, &self.root, &self.install, |message| {
            if let Some(owned) = child.as_mut() {
                ensure!(
                    owned.child.try_wait()?.is_none(),
                    "Join cancelled because Player was closed"
                );
            }
            if let Some(path) = &view {
                fs::write(path, json!({"message":message}).to_string())?;
            }
            Ok(())
        })?;
        self.child.take();
        self.host.take();
        self.invite_view = Value::Null;
        self.launch(0, Some(joined))
    }
    fn poll_ui(&mut self) -> Result<()> {
        let command = self
            .child
            .as_ref()
            .map(|c| (c.gate.with_extension("command.json"), c.token.clone()));
        if let Some((path, token)) = command {
            if let Ok(bytes) = fs::read(&path) {
                let _ = fs::remove_file(&path);
                let result = (|| -> Result<Value> {
                    ensure!(bytes.len() <= 8192, "Invalid session action");
                    let request: Value = serde_json::from_slice(&bytes)?;
                    ensure!(request["token"] == token, "Invalid local session control");
                    match request["action"].as_str() {
                        Some("invite") => self
                            .host
                            .as_mut()
                            .context("Only the host can invite players")?
                            .invite(),
                        Some("join") => {
                            self.join(request["code"].as_str().context("Paste an invite code")?)
                        }
                        Some("leave") => {
                            self.child.take();
                            self.host.take();
                            Ok(json!({"message":"Session closed"}))
                        }
                        _ => bail!("Unknown session action"),
                    }
                })();
                self.invite_view = match result {
                    Ok(value) => value,
                    Err(error) => json!({"message":error.to_string()}),
                };
            }
        }
        if let Some(owned) = &self.child {
            let members = if let Some(host) = &mut self.host {
                host.members()
                    .unwrap_or_else(|e| json!({"message":e.to_string()}))
            } else {
                json!({})
            };
            let value = json!({"schema":"xace.player.session_view.v1","hosting":self.host.is_some(),"invite":self.invite_view,"readiness":members});
            fs::write(
                owned.gate.with_extension("view.json"),
                serde_json::to_vec(&value)?,
            )?;
        }
        Ok(())
    }
    fn request(&mut self, value: Value) -> Result<Value> {
        ensure!(
            value["schema"] == "xace.player.broker_request.v1"
                && value["capability"] == self.capability,
            "invalid local launch capability"
        );
        match value["action"].as_str() {
            Some("play") => self.play(
                value["preferred_port"]
                    .as_u64()
                    .filter(|v| *v <= 65535)
                    .unwrap_or(0) as u16,
            ),
            Some("invite") => {
                let result = self
                    .host
                    .as_mut()
                    .context("Play your game before inviting a friend")?
                    .invite()?;
                self.invite_view = result.clone();
                Ok(result)
            }
            Some("join") => self.join(value["code"].as_str().context("Paste an invite code")?),
            Some("status") => {
                let mut value = self.status()?;
                if let Some(host) = &mut self.host {
                    value["readiness"] = host.members()?;
                }
                Ok(value)
            }
            Some("stop") => {
                self.child.take();
                self.host.take();
                self.status()
            }
            _ => bail!("unsupported launch action"),
        }
    }
}
fn emit(value: Value) -> Result<()> {
    println!("{}", value);
    io::stdout().flush()?;
    Ok(())
}
fn main() {
    if let Err(error) = run() {
        let _ = emit(json!({"ok":false,"state":"failed","message":error.to_string()}));
        #[cfg(windows)]
        if !std::env::args().any(|arg| arg == "--serve") {
            use std::os::windows::ffi::OsStrExt;
            #[link(name = "user32")]
            extern "system" {
                fn MessageBoxW(
                    window: *mut std::ffi::c_void,
                    text: *const u16,
                    title: *const u16,
                    flags: u32,
                ) -> i32;
            }
            let message: Vec<u16> = std::ffi::OsStr::new(&error.to_string())
                .encode_wide()
                .chain(Some(0))
                .collect();
            let title: Vec<u16> = "XACE Player".encode_utf16().chain(Some(0)).collect();
            unsafe {
                MessageBoxW(std::ptr::null_mut(), message.as_ptr(), title.as_ptr(), 0x10);
            }
        }
        std::process::exit(1);
    }
}
fn run() -> Result<()> {
    ensure!(
        cfg!(all(windows, target_arch = "x86_64")),
        "This release requires Windows x86_64"
    );
    let args: Vec<String> = std::env::args().skip(1).collect();
    let value = |name: &str| {
        args.windows(2)
            .find(|pair| pair[0] == name)
            .map(|pair| pair[1].clone())
    };
    let source = PathBuf::from(
        value("--source").unwrap_or(
            std::env::current_exe()?
                .parent()
                .unwrap()
                .to_string_lossy()
                .into(),
        ),
    );
    let trust: Value = serde_json::from_slice(
        &fs::read(source.join("distribution.trust.json")).unwrap_or_default(),
    )
    .unwrap_or(Value::Null);
    let digest = value("--expected")
        .or_else(|| trust["manifest_sha256"].as_str().map(str::to_owned))
        .context("Missing trusted release checksum")?;
    let install = value("--install").map(PathBuf::from).unwrap_or_else(|| {
        PathBuf::from(std::env::var_os("LOCALAPPDATA").unwrap_or_else(|| ".".into()))
            .join("XACE/Player")
    });
    let root = materialize(&source, &install, &digest)?;
    let mut broker = Broker {
        root,
        install,
        digest,
        child: None,
        headless: args.iter().any(|a| a == "--headless-player"),
        capability: uuid::Uuid::new_v4().to_string(),
        host: None,
        invite_view: Value::Null,
    };
    if !args.iter().any(|a| a == "--serve") {
        if let Some(code) = value("--join-code") {
            emit(broker.join(&code)?)?;
        } else {
            emit(broker.play(0)?)?;
        }
        while broker.status()?["state"] == "playing" {
            broker.poll_ui()?;
            thread::sleep(Duration::from_millis(100));
        }
        return Ok(());
    }
    emit(
        json!({"schema":"xace.player.broker_ready.v1","capability":broker.capability,"state":"ready"}),
    )?;
    // EOF closes the job even if the owner disappears without sending Stop.
    let (sender, receiver) = std::sync::mpsc::sync_channel(8);
    thread::spawn(move || {
        let mut stdin = io::stdin().lock();
        loop {
            let mut bytes = Vec::new();
            match (&mut stdin).take(8193).read_until(b'\n', &mut bytes) {
                Ok(0) | Err(_) => break,
                Ok(count) => {
                    if count > 8192 || bytes.last() != Some(&b'\n') {
                        break;
                    }
                    if sender.send(bytes).is_err() {
                        break;
                    }
                }
            }
        }
    });
    loop {
        match receiver.recv_timeout(Duration::from_millis(100)) {
            Ok(bytes) => {
                let result = serde_json::from_slice(&bytes)
                    .map_err(anyhow::Error::from)
                    .and_then(|v| broker.request(v));
                emit(match result {
                    Ok(value) => json!({"ok":true,"result":value}),
                    Err(error) => json!({"ok":false,"state":"failed","message":error.to_string()}),
                })?;
            }
            Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {
                broker.status()?;
                broker.poll_ui()?;
            }
            Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => break,
        }
    }
    Ok(())
}
