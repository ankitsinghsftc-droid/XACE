use xace_network_core::session::{
    launch_topology_matrix, require_launch_topology, LaunchTopologySupport, NetworkMode,
    SessionConfig, SessionManager, SessionPhase, LAUNCH_TOPOLOGY_ID,
};
use xace_network_core::NetworkError;

#[test]
fn launch_topology_matrix_selects_host_client_lockstep() {
    let matrix = launch_topology_matrix();
    assert_eq!(matrix.len(), NetworkMode::all().len());

    let launch_multiplayer = matrix
        .iter()
        .filter(|row| row.support == LaunchTopologySupport::LaunchMultiplayer)
        .map(|row| row.mode)
        .collect::<Vec<_>>();
    assert_eq!(
        launch_multiplayer,
        vec![NetworkMode::Host, NetworkMode::Client]
    );

    for row in matrix {
        match row.mode {
            NetworkMode::Host | NetworkMode::Client => {
                assert_eq!(row.topology_id, LAUNCH_TOPOLOGY_ID);
                assert!(row.allowed_in_launch_profile);
                assert!(row.multiplayer);
                assert!(row.failure_code.is_empty());
            }
            NetworkMode::Offline => {
                assert!(row.allowed_in_launch_profile);
                assert!(!row.multiplayer);
                assert_eq!(row.support, LaunchTopologySupport::LocalOnly);
            }
            NetworkMode::DedicatedServer | NetworkMode::PeerToPeer => {
                assert!(!row.allowed_in_launch_profile);
                assert!(row.multiplayer);
                assert_eq!(row.support, LaunchTopologySupport::Unsupported);
                assert_eq!(row.failure_code, "XACE_NETWORK_TOPOLOGY_UNSUPPORTED");
            }
        }
    }
}

#[test]
fn unsupported_launch_topologies_fail_visibly() {
    for mode in [NetworkMode::DedicatedServer, NetworkMode::PeerToPeer] {
        let err = require_launch_topology(mode).unwrap_err();
        match err {
            NetworkError::UnsupportedTopology {
                failure_code,
                mode: rejected_mode,
                topology_id,
                reason,
            } => {
                assert_eq!(failure_code, "XACE_NETWORK_TOPOLOGY_UNSUPPORTED");
                assert_eq!(rejected_mode, mode.stable_id());
                assert!(topology_id.ends_with("future_v1"));
                assert!(!reason.is_empty());
            }
            other => panic!("unexpected topology error: {other:?}"),
        }
    }
}

#[test]
fn host_client_launch_sessions_have_expected_authority_and_input_scope() {
    let host_policy = require_launch_topology(NetworkMode::Host).unwrap();
    assert_eq!(host_policy.authority_model, "host_authoritative");

    let mut host = SessionManager::new(NetworkMode::Host);
    host.add_peer(1).unwrap();
    host.add_peer(2).unwrap();
    host.mark_peer_live(1).unwrap();
    host.mark_peer_live(2).unwrap();
    host.start_live().unwrap();
    assert_eq!(host.phase(), SessionPhase::Live);
    assert_eq!(
        host.required_input_peers().into_iter().collect::<Vec<_>>(),
        vec![1, 2]
    );

    let client_policy = require_launch_topology(NetworkMode::Client).unwrap();
    assert_eq!(client_policy.authority_model, "server_authoritative_client");

    let mut client = SessionManager::with_config(SessionConfig {
        mode: NetworkMode::Client,
        local_peer_id: Some(2),
        server_peer_id: Some(1),
        require_all_live_peers_for_input: false,
        ..SessionConfig::default()
    })
    .unwrap();
    client.add_peer(1).unwrap();
    client.mark_peer_live(1).unwrap();
    client.start_live().unwrap();
    assert_eq!(
        client
            .required_input_peers()
            .into_iter()
            .collect::<Vec<_>>(),
        vec![1]
    );
}

#[test]
fn offline_is_allowed_but_not_a_multiplayer_launch_topology() {
    let decision = require_launch_topology(NetworkMode::Offline).unwrap();
    assert_eq!(decision.support, LaunchTopologySupport::LocalOnly);
    assert!(decision.allowed_in_launch_profile);
    assert!(!decision.multiplayer);
    assert_eq!(decision.authority_model, "local_only");
}
