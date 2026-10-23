//! Shared shipping authority process. No gameplay, compiler or developer control port.
use crate::job::Job;
use anyhow::{ensure, Result};
use std::{net::SocketAddr, path::Path, process::{Child, Command, ExitStatus, Stdio}};

pub struct Authority {
    child: Child,
    _job: Job,
}

/// Typed launch configuration deliberately offers no arbitrary executable arguments.
pub struct Launch<'a> {
    pub package: &'a Path,
    pub ticket: &'a Path,
    pub journal: &'a Path,
    pub endpoint: SocketAddr,
    pub controllers: &'a [u64],
}
impl Launch<'_> {
    fn command(&self) -> Result<Command> {
        ensure!(!self.controllers.is_empty() && self.controllers.len() <= 4,
            "One to four controllers required");
        let mut ids = std::collections::BTreeSet::new();
        ensure!(self.controllers.iter().all(|id| *id > 0 && ids.insert(*id)),
            "Distinct positive controller identities required");
        ensure!(self.endpoint.port() > 0, "Assigned engine port required");
        let mut command = Command::new(self.package.join("runtime/xace_runtime.exe"));
        command.stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
        for (flag, file) in [
            ("--cgs", "game.cgs.json"), ("--sgc-plan", "execution_plan.json"),
            ("--world", "world.json"), ("--world-manifest", "world.manifest.json"),
            ("--package-manifest", "playable.manifest.json"),
        ] { command.arg(flag).arg(self.package.join(file)); }
        command.arg("--session-ticket-out").arg(self.ticket)
            .arg("--session-log").arg(self.journal)
            .arg("--session-controller-id").arg(self.controllers.iter().map(u64::to_string).collect::<Vec<_>>().join(","))
            .arg("--input-lockstep-peer").arg((1..=self.controllers.len()).map(|id| id.to_string()).collect::<Vec<_>>().join(","))
            .arg("--port").arg(self.endpoint.port().to_string())
            .arg("--engine-bind").arg(self.endpoint.ip().to_string())
            .args(["--no-control", "--live-session", "--no-wait", "--live-engine-accept", "--quiet"]);
        #[cfg(windows)] {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000);
        }
        Ok(command)
    }
}
impl Authority {
    // Admission belongs to the caller; this primitive is crate-private to prevent
    // exposing an unchecked native launch API. Native service must verify first.
    pub(crate) fn start(config: &Launch<'_>) -> Result<Self> {
        let mut child = config.command()?.spawn()?;
        match Job::own(&child) {
            Ok(job) => Ok(Self { child, _job: job }),
            Err(error) => { let _ = child.kill(); let _ = child.wait(); Err(error) }
        }
    }
    pub fn id(&self) -> u32 { self.child.id() }
    pub fn listening(&self, endpoint: SocketAddr) -> Result<bool> {
        owns_listener(self.id(), endpoint)
    }
    pub fn try_wait(&mut self) -> std::io::Result<Option<ExitStatus>> { self.child.try_wait() }
    pub fn stop(&mut self) { let _ = self.child.kill(); let _ = self.child.wait(); }
}
impl Drop for Authority { fn drop(&mut self) { self.stop(); } }

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn shipping_command_has_no_developer_endpoint_and_preserves_player_slots() {
        let config = Launch { package: Path::new("game"), ticket: Path::new("ticket"),
            journal: Path::new("journal"), endpoint: "127.0.0.1:42100".parse().unwrap(), controllers: &[9, 3] };
        let cmd = config.command().unwrap();
        let args: Vec<_> = cmd.get_args().map(|v| v.to_str().unwrap()).collect();
        assert!(args.contains(&"--no-control"));
        assert!(!args.contains(&"--control-port"));
        assert!(args.windows(2).any(|p| p == ["--session-controller-id", "9,3"]));
        assert!(args.windows(2).any(|p| p == ["--input-lockstep-peer", "1,2"]));
        assert_eq!(cmd.get_program(), Path::new("game").join("runtime/xace_runtime.exe"));
    }
    #[test]
    fn invalid_controller_identity_refused_before_spawn() {
        for ids in [vec![], vec![0], vec![1, 1], vec![1,2,3,4,5]] {
            let config = Launch { package: Path::new("missing"), ticket: Path::new("ticket"),
                journal: Path::new("journal"), endpoint: "127.0.0.1:42100".parse().unwrap(), controllers: &ids };
            assert!(config.command().is_err());
        }
    }
}

/// Readiness must include the actual owned listener, not just a ticket written
/// earlier during runtime initialization. This does not consume an engine slot.
#[cfg(windows)]
fn owns_listener(pid: u32, endpoint: SocketAddr) -> Result<bool> {
    #[link(name = "iphlpapi")]
    extern "system" {
        fn GetExtendedTcpTable(table: *mut std::ffi::c_void, size: *mut u32,
            order: i32, family: u32, class: u32, reserved: u32) -> u32;
    }
    let std::net::IpAddr::V4(expected_ip) = endpoint.ip() else { return Ok(false); };
    let mut length = 0u32;
    let first = unsafe { GetExtendedTcpTable(std::ptr::null_mut(), &mut length, 0, 2, 3, 0) };
    ensure!(first == 122 || first == 0, "Cannot inspect owned listener: {first}");
    for _ in 0..3 {
        ensure!(length >= 4 && length <= 16*1024*1024, "Unexpected listener table size");
        let mut bytes = vec![0u8; length as usize];
        let result = unsafe { GetExtendedTcpTable(bytes.as_mut_ptr().cast(), &mut length, 0, 2, 3, 0) };
        if result == 122 { continue; }
        ensure!(result == 0 && length as usize <= bytes.len(), "Cannot inspect owned listener: {result}");
        let count = u32::from_ne_bytes(bytes[..4].try_into().unwrap()) as usize;
        ensure!(count <= (length as usize - 4)/24, "Invalid listener table");
        for row in bytes[4..4+count*24].chunks_exact(24) {
            let fields: Vec<u32> = row.chunks_exact(4).map(|b| u32::from_ne_bytes(b.try_into().unwrap())).collect();
            if fields[5] == pid && fields[0] == 2
                && std::net::Ipv4Addr::from(fields[1].to_ne_bytes()) == expected_ip
                && u16::from_be(fields[2] as u16) == endpoint.port() { return Ok(true); }
        }
        return Ok(false);
    }
    anyhow::bail!("Listener table changed repeatedly; retry readiness")
}
#[cfg(not(windows))]
fn owns_listener(_: u32, _: SocketAddr) -> Result<bool> { anyhow::bail!("Windows native host required") }
