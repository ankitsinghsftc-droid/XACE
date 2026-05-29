use xace_network_core::authority::{
    AuthorityResolver, AuthorityScope, AuthorityTransfer, AuthorityTransferReason,
    AuthorityTransferState,
};
use xace_network_core::session::{
    ConnectionState, NetworkMode, PauseReason, SessionConfig, SessionManager, SessionPhase,
};
use xace_network_core::NetworkError;

#[test]
fn session_promotes_peers_to_live_and_reports_required_inputs() {
    let mut session = SessionManager::new(NetworkMode::Host);
    session.add_peer(10).unwrap();
    session.add_peer(20).unwrap();

    session.mark_peer_live(10).unwrap();
    session.mark_peer_live(20).unwrap();
    session.start_live().unwrap();

    assert_eq!(session.phase(), SessionPhase::Live);
    assert_eq!(session.required_input_peers().len(), 2);
    assert!(session.required_input_peers().contains(&10));
    assert!(session.can_advance_simulation());
    assert_eq!(
        session.peers().require(10).unwrap().state,
        ConnectionState::Live
    );
}

#[test]
fn session_enforces_peer_limits_and_late_join_policy() {
    let mut session = SessionManager::with_config(SessionConfig {
        mode: NetworkMode::Host,
        max_peers: 1,
        allow_late_join: false,
        ..SessionConfig::default()
    })
    .unwrap();

    session.add_peer(1).unwrap();
    assert!(session.add_peer(2).is_err());

    session.mark_peer_live(1).unwrap();
    session.start_live().unwrap();
    session.peers_mut().remove_peer(1);
    assert!(session.add_peer(3).is_err());
}

#[test]
fn session_marks_timeouts_reconnecting_and_pauses() {
    let mut session = SessionManager::with_config(SessionConfig {
        mode: NetworkMode::Host,
        heartbeat_timeout_ticks: 3,
        ..SessionConfig::default()
    })
    .unwrap();
    session.add_peer(1).unwrap();
    session.mark_peer_live(1).unwrap();
    session.start_live().unwrap();
    session.observe_heartbeat(1).unwrap();

    for _ in 0..5 {
        session.advance_tick();
    }

    let timed_out = session.apply_heartbeat_timeouts().unwrap();
    assert_eq!(timed_out, vec![1]);
    assert_eq!(session.phase(), SessionPhase::Paused);
    assert_eq!(session.pause_reason(), Some(&PauseReason::PeerTimeout(1)));
}

#[test]
fn authority_resolver_uses_server_fallback_and_explicit_assignment() {
    let mut resolver = AuthorityResolver::with_server(100).unwrap();

    assert_eq!(resolver.authority_for(42), Some(100));
    resolver.require_authority(42, 100).unwrap();
    assert!(matches!(
        resolver.require_authority(42, 200),
        Err(NetworkError::AuthorityDenied { .. })
    ));

    let version = resolver.assign_at(42, 200, 5).unwrap();
    assert_eq!(version, resolver.generation());
    assert_eq!(resolver.authority_for(42), Some(200));
    resolver.require_authority(42, 200).unwrap();
    assert_eq!(
        resolver
            .entities_for_peer(200)
            .into_iter()
            .collect::<Vec<_>>(),
        vec![42]
    );
}

#[test]
fn authority_resolver_blocks_locked_transfers_and_restores_snapshots() {
    let mut resolver = AuthorityResolver::with_server(1).unwrap();
    resolver.assign_at(10, 2, 1).unwrap();
    resolver.lock_entity(10).unwrap();

    assert!(resolver.transfer(10, 2, 3, 2).is_err());
    resolver.unlock_entity(10).unwrap();
    resolver.transfer(10, 2, 3, 3).unwrap();

    let snapshot = resolver.snapshot();
    let restored = AuthorityResolver::restore(snapshot).unwrap();
    assert_eq!(restored.authority_for(10), Some(3));
    assert_eq!(restored.server_peer(), Some(1));
}

#[test]
fn authority_resolver_supports_shared_writers() {
    let mut resolver = AuthorityResolver::new();
    resolver.assign_shared(77, [4, 5], 9).unwrap();

    let record = resolver.record_for(77).unwrap();
    assert_eq!(record.scope, AuthorityScope::Shared);
    resolver.require_authority(77, 4).unwrap();
    resolver.require_authority(77, 5).unwrap();
    assert!(resolver.require_authority(77, 6).is_err());
    assert_eq!(
        resolver
            .shared_entities_for_peer(4)
            .into_iter()
            .collect::<Vec<_>>(),
        vec![77]
    );
}

#[test]
fn authority_transfer_accepts_commits_and_rejects_invalid_replays() {
    let mut transfer =
        AuthorityTransfer::request(99, 10, 20, 5, AuthorityTransferReason::PlayerPossession)
            .with_expiry(12)
            .with_pre_transfer_version(3);

    transfer.accept(20, 6).unwrap();
    assert_eq!(transfer.state, AuthorityTransferState::Accepted);
    assert_eq!(transfer.accepted_by, Some(20));

    transfer.commit(7, 4).unwrap();
    assert!(transfer.is_terminal());
    assert!(transfer.is_committed());
    assert_eq!(transfer.duration_ticks(), Some(2));
    assert!(transfer.reject("too late", 8).is_err());
}

#[test]
fn authority_transfer_expires_before_acceptance() {
    let mut transfer = AuthorityTransfer::new(1, 2, 3, 10).with_expiry(11);
    transfer.accept(3, 12).unwrap();

    assert_eq!(transfer.state, AuthorityTransferState::Expired);
    assert_eq!(transfer.completed_tick, Some(12));
}
