//! Local native-host owner protocol over inherited stdin/stdout only.
use crate::{lifecycle::{Authority, Launch}, native_release};
use anyhow::{ensure, Context, Result};
use serde_json::{json, Value};
use std::{fs, io::{self, BufRead, Read, Write}, net::TcpListener, path::Path, sync::mpsc, thread, time::{Duration, Instant}};

fn emit(value: Value) -> Result<()> { println!("{value}"); io::stdout().flush()?; Ok(()) }
/// Only a local parent with the inherited pipe can issue lifecycle commands.
/// There is no socket control server or network configuration in this service.
pub fn serve(root: &Path, expected: &str, history: &Path, controller: u64) -> Result<()> {
    let initial = native_release::admit(root, expected)?;
    let local_data = std::env::var_os("LOCALAPPDATA").context("Per-user LocalAppData directory required")?;
    let save_root = crate::native_storage::namespace(Path::new(&local_data), &initial.receipt.game_id)?;

    ensure!(controller > 0 && history.is_absolute(), "Absolute persistent history and controller required");
    fs::create_dir_all(history)?;
    let (tx, rx) = mpsc::sync_channel(8);
    thread::spawn(move || {
        let mut input = io::stdin().lock();
        loop {
            let mut bytes = Vec::new();
            match (&mut input).take(8193).read_until(b'\n', &mut bytes) {
                Ok(n) if n > 0 && n <= 8192 && bytes.last() == Some(&b'\n') => { if tx.send(bytes).is_err() { break; } }
                _ => break,
            }
        }
    });
    let mut authority: Option<Authority> = None;
    let mut ready = Value::Null;
    emit(json!({"schema":"xace.native_host.ready.v1","release":expected,"state":"stopped","save_root":save_root,"save_identity":initial.save_identity()?}))?;
    loop {
        if let Some(process) = &mut authority {
            if process.try_wait()?.is_some() {
                authority.take(); ready = Value::Null;
                emit(json!({"ok":false,"state":"authority_lost","native_fallback":false}))?;
            }
        }
        match rx.recv_timeout(Duration::from_millis(50)) {
            Ok(bytes) => {
                let response = (|| -> Result<Value> {
                    let request: Value = serde_json::from_slice(&bytes)?;
                    match request["action"].as_str() {
                        Some("check-save") => {
                            let slot = request["slot"].as_str().context("Save slot required")?;
                            ensure!(!slot.is_empty() && slot.len() <= 64 && slot.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_'), "Invalid save slot");
                            crate::distribution::plain(&save_root)?;
                            let path = save_root.join(format!("slot-{slot}.json"));
                            crate::distribution::plain(&path)?;
                            ensure!(fs::metadata(&path)?.len() <= 65*1024*1024, "Save size limit");
                            let admitted = native_release::admit(root, expected)?;
                            crate::native_storage::admit(&fs::read(path)?, &admitted.save_identity()?)?;
                            Ok(json!({"state":"save_compatible","restored":false}))
                        }
                        Some("verify") => { native_release::admit(root, expected)?; Ok(json!({"state":"verified","release":expected})) }
                        Some("stop") => { authority.take(); ready = Value::Null; Ok(json!({"state":"stopped"})) }
                        Some("status") => Ok(if authority.is_some() { ready.clone() } else { json!({"state":"stopped"}) }),
                        Some("play") => {
                            if authority.is_some() { return Ok(ready.clone()); }
                            let admitted = native_release::admit(root, expected)?;
                            let preferred = request.get("preferred_port").map(|v| v.as_u64().filter(|n| *n <= 65535).context("Invalid engine port")).transpose()?.unwrap_or(0) as u16;
                            let reserve = TcpListener::bind(("127.0.0.1", preferred)).or_else(|_| TcpListener::bind(("127.0.0.1", 0)))?;
                            let endpoint = reserve.local_addr()?;
                            let directory = history.join(format!("native-session-{}", uuid::Uuid::new_v4()));
                            fs::create_dir(&directory)?;
                            let ticket = directory.join("ticket.json");
                            let journal = directory.join("authority.jsonl");
                            drop(reserve);
                            let mut process = Authority::start(&Launch { package: &admitted.package, ticket: &ticket, journal: &journal, endpoint, controllers: &[controller] })?;
                            let start = Instant::now();
                            while start.elapsed() < Duration::from_secs(8) && !(ticket.exists() && process.listening(endpoint)?) {
                                ensure!(process.try_wait()?.is_none(), "Authority exited before readiness");
                                thread::sleep(Duration::from_millis(20));
                            }
                            ensure!(process.try_wait()?.is_none() && ticket.exists() && process.listening(endpoint)?, "Authority readiness timed out");
                            let mut contents: Value = serde_json::from_slice(&fs::read(&ticket)?)?;
                            let original_offer: Value = serde_json::from_str(contents["offer_json"].as_str().context("Missing original offer")?)?;
                            ensure!(original_offer == contents["offer"], "Original authority offer encodings disagree");
                            // Runtime supplies the authoritative contract; the pinned host
                            // selects only the client engine claim for the native adapter.
                            contents["offer"]["client"]["adapter"]["engine"] = admitted.receipt.engine.to_lowercase().into();
                            contents["offer_json"] = serde_json::to_string(&contents["offer"])?.into();
                            admitted.verify_ticket(&contents, controller)?;
                            native_release::admit(root, expected)?;
                            let client_ticket = directory.join("native-ticket.json");
                            let mut ticket_file = fs::OpenOptions::new().write(true).create_new(true).open(&client_ticket)?;
                            ticket_file.write_all(&serde_json::to_vec(&contents)?)?;
                            ticket_file.sync_all()?;
                            crate::native_storage::activate(&save_root.parent().context("Missing game data root")?.join("release-state"), root, expected)?;
                            ready = json!({"state":"ready","runtime_pid":process.id(),"endpoint":endpoint.to_string(),"ticket":client_ticket,"release":admitted.identity,"game_id":admitted.receipt.game_id,"native_fallback":false});
                            authority = Some(process);
                            Ok(ready.clone())
                        }
                        _ => anyhow::bail!("Unsupported native lifecycle action"),
                    }
                })();
                emit(match response { Ok(value) => json!({"ok":true,"result":value}), Err(error) => json!({"ok":false,"state":"refused","message":error.to_string()}) })?;
            }
            Err(mpsc::RecvTimeoutError::Timeout) => (),
            Err(mpsc::RecvTimeoutError::Disconnected) => break,
        }
    }
    // Dropping the owned process on EOF closes its Job. No process enumeration.
    drop(authority);
    Ok(())
}
