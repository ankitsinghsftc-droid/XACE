use serde::{Deserialize, Serialize};

use super::NetworkMode;
use crate::NetworkError;

pub const LAUNCH_TOPOLOGY_ID: &str = "host_client_lockstep_v1";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum LaunchTopologySupport {
    LaunchMultiplayer,
    LocalOnly,
    Unsupported,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LaunchTopologyDecision {
    pub mode: NetworkMode,
    pub topology_id: &'static str,
    pub support: LaunchTopologySupport,
    pub allowed_in_launch_profile: bool,
    pub multiplayer: bool,
    pub authority_model: &'static str,
    pub tick_model: &'static str,
    pub failure_code: &'static str,
    pub reason: &'static str,
}

impl LaunchTopologyDecision {
    pub fn require_launch_supported(&self) -> Result<(), NetworkError> {
        if self.allowed_in_launch_profile {
            return Ok(());
        }
        Err(NetworkError::UnsupportedTopology {
            failure_code: self.failure_code.to_string(),
            mode: self.mode.stable_id().to_string(),
            topology_id: self.topology_id.to_string(),
            reason: self.reason.to_string(),
        })
    }
}

pub fn launch_topology_for_mode(mode: NetworkMode) -> LaunchTopologyDecision {
    match mode {
        NetworkMode::Host => LaunchTopologyDecision {
            mode,
            topology_id: LAUNCH_TOPOLOGY_ID,
            support: LaunchTopologySupport::LaunchMultiplayer,
            allowed_in_launch_profile: true,
            multiplayer: true,
            authority_model: "host_authoritative",
            tick_model: "lockstep_required_peer_inputs",
            failure_code: "",
            reason: "Host owns the authoritative simulation clock and waits for required client input packets before releasing a tick.",
        },
        NetworkMode::Client => LaunchTopologyDecision {
            mode,
            topology_id: LAUNCH_TOPOLOGY_ID,
            support: LaunchTopologySupport::LaunchMultiplayer,
            allowed_in_launch_profile: true,
            multiplayer: true,
            authority_model: "server_authoritative_client",
            tick_model: "lockstep_server_input_source",
            failure_code: "",
            reason: "Client connects to a host authority and treats host/server packets as the upstream tick authority.",
        },
        NetworkMode::Offline => LaunchTopologyDecision {
            mode,
            topology_id: "offline_local_v1",
            support: LaunchTopologySupport::LocalOnly,
            allowed_in_launch_profile: true,
            multiplayer: false,
            authority_model: "local_only",
            tick_model: "local_runtime_tick",
            failure_code: "",
            reason: "Offline mode is launch-allowed as local-only gameplay, not as a multiplayer topology.",
        },
        NetworkMode::DedicatedServer => LaunchTopologyDecision {
            mode,
            topology_id: "dedicated_server_future_v1",
            support: LaunchTopologySupport::Unsupported,
            allowed_in_launch_profile: false,
            multiplayer: true,
            authority_model: "dedicated_server_authoritative_future",
            tick_model: "unsupported_launch_profile",
            failure_code: "XACE_NETWORK_TOPOLOGY_UNSUPPORTED",
            reason: "Dedicated-server topology is reserved for a later launch profile; host/client authoritative lockstep is the only launch multiplayer topology.",
        },
        NetworkMode::PeerToPeer => LaunchTopologyDecision {
            mode,
            topology_id: "peer_to_peer_future_v1",
            support: LaunchTopologySupport::Unsupported,
            allowed_in_launch_profile: false,
            multiplayer: true,
            authority_model: "distributed_authority_future",
            tick_model: "unsupported_launch_profile",
            failure_code: "XACE_NETWORK_TOPOLOGY_UNSUPPORTED",
            reason: "Peer-to-peer topology is reserved for a later launch profile; launch does not support distributed authority or NAT traversal claims.",
        },
    }
}

pub fn require_launch_topology(mode: NetworkMode) -> Result<LaunchTopologyDecision, NetworkError> {
    let decision = launch_topology_for_mode(mode);
    decision.require_launch_supported()?;
    Ok(decision)
}

pub fn launch_topology_matrix() -> Vec<LaunchTopologyDecision> {
    NetworkMode::all()
        .iter()
        .copied()
        .map(launch_topology_for_mode)
        .collect()
}
