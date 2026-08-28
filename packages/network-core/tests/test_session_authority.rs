use xace_network_core::authority::{
    AuthorityResolver, AuthorityScope, AuthorityTransfer, AuthorityTransferReason,
    AuthorityTransferState,
};
use xace_network_core::session::{
    ConnectionState, NetworkMode, PauseReason, SessionCompatibilityMismatchKind,
    SessionCompatibilityProfile, SessionConfig, SessionLifecycleEventKind, SessionManager,
    SessionPhase, SessionPlayerIdentity,
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
fn x10_039_host_client_session_lifecycle_covers_create_join_ready_leave_reconnect_late_join_and_teardown(
) {
    let mut session = SessionManager::with_config(SessionConfig {
        mode: NetworkMode::Host,
        max_peers: 4,
        allow_late_join: true,
        ..SessionConfig::default()
    })
    .unwrap();

    session.create_lobby().unwrap();
    session
        .join_peer(
            SessionPlayerIdentity::new(1, 101, "Host Player").with_adapter("headless", "x10-039"),
        )
        .unwrap();
    session
        .join_peer(
            SessionPlayerIdentity::new(2, 102, "Client Player").with_adapter("headless", "x10-039"),
        )
        .unwrap();
    assert_eq!(session.phase(), SessionPhase::Lobby);
    assert_eq!(session.player_identities().len(), 2);

    session.mark_peer_ready(1).unwrap();
    session.mark_peer_ready(2).unwrap();
    assert!(session.all_lobby_peers_ready());
    assert_eq!(
        session.ready_peer_ids().into_iter().collect::<Vec<_>>(),
        vec![1, 2]
    );

    session.start_live_when_ready().unwrap();
    assert_eq!(session.phase(), SessionPhase::Live);
    assert_eq!(
        session
            .required_input_peers()
            .into_iter()
            .collect::<Vec<_>>(),
        vec![1, 2]
    );
    assert_eq!(session.status().peer_stats.live, 2);
    assert_eq!(session.status().peer_stats.ready, 2);
    assert!(session.can_advance_simulation());

    session.leave_peer(2).unwrap();
    assert_eq!(
        session.peers().require(2).unwrap().state,
        ConnectionState::Disconnected
    );
    assert_eq!(
        session
            .required_input_peers()
            .into_iter()
            .collect::<Vec<_>>(),
        vec![1]
    );
    assert_eq!(
        session.ready_peer_ids().into_iter().collect::<Vec<_>>(),
        vec![1]
    );

    session.reconnect_peer(2).unwrap();
    assert_eq!(
        session.peers().require(2).unwrap().state,
        ConnectionState::Syncing
    );
    session.mark_peer_ready(2).unwrap();
    session.promote_ready_peer_to_live(2).unwrap();
    assert_eq!(
        session
            .required_input_peers()
            .into_iter()
            .collect::<Vec<_>>(),
        vec![1, 2]
    );

    session
        .late_join_peer(
            SessionPlayerIdentity::new(3, 103, "Late Join Player")
                .with_adapter("headless", "x10-039"),
        )
        .unwrap();
    assert_eq!(
        session.peers().require(3).unwrap().state,
        ConnectionState::Syncing
    );
    assert_eq!(
        session
            .required_input_peers()
            .into_iter()
            .collect::<Vec<_>>(),
        vec![1, 2]
    );
    session.mark_peer_ready(3).unwrap();
    session.promote_ready_peer_to_live(3).unwrap();
    assert_eq!(
        session
            .required_input_peers()
            .into_iter()
            .collect::<Vec<_>>(),
        vec![1, 2, 3]
    );
    assert_eq!(session.status().player_identities.len(), 3);

    session.teardown().unwrap();
    let status = session.status();
    assert_eq!(status.phase, SessionPhase::Ended);
    assert_eq!(status.peer_stats.disconnected, 3);
    assert!(status.required_input_peers.is_empty());
    assert!(status.ready_peers.is_empty());

    let kinds = status
        .lifecycle_events
        .iter()
        .map(|event| event.kind)
        .collect::<Vec<_>>();
    for expected in [
        SessionLifecycleEventKind::Created,
        SessionLifecycleEventKind::LobbyCreated,
        SessionLifecycleEventKind::Joined,
        SessionLifecycleEventKind::Ready,
        SessionLifecycleEventKind::LiveStarted,
        SessionLifecycleEventKind::Left,
        SessionLifecycleEventKind::Reconnecting,
        SessionLifecycleEventKind::Reconnected,
        SessionLifecycleEventKind::LateJoined,
        SessionLifecycleEventKind::TeardownStarted,
        SessionLifecycleEventKind::Ended,
    ] {
        assert!(
            kinds.contains(&expected),
            "missing lifecycle event {expected:?}"
        );
    }
}

#[test]
fn x10_040_session_compatibility_mismatch_matrix_blocks_start() {
    for kind in [
        SessionCompatibilityMismatchKind::Schema,
        SessionCompatibilityMismatchKind::SgcPlan,
        SessionCompatibilityMismatchKind::AdapterVersion,
        SessionCompatibilityMismatchKind::Assets,
        SessionCompatibilityMismatchKind::Packages,
        SessionCompatibilityMismatchKind::ProviderFreeMetadata,
        SessionCompatibilityMismatchKind::Template,
    ] {
        let mut session = compatibility_lobby();
        let report = session
            .record_peer_compatibility(mismatched_profile(2, kind))
            .unwrap();
        assert!(!report.compatible);
        assert_eq!(report.mismatches.len(), 1);
        assert_eq!(report.mismatches[0].kind, kind);

        session.mark_peer_ready(1).unwrap();
        session.mark_peer_ready(2).unwrap();
        let err = session.start_live_when_ready().unwrap_err().to_string();

        assert!(err.contains("session compatibility check failed"));
        assert!(err.contains(kind.stable_id()));
        assert_eq!(session.phase(), SessionPhase::Lobby);
        let status = session.status();
        assert!(status.compatibility_required);
        assert!(!status.compatibility_ok);
        assert_eq!(status.compatibility_blockers[0].kind, kind);
        assert!(status
            .lifecycle_events
            .iter()
            .any(|event| event.kind == SessionLifecycleEventKind::CompatibilityFailed));
    }
}

#[test]
fn x10_040_compatible_session_profiles_allow_start_and_missing_profiles_block_start() {
    let mut compatible = compatibility_lobby();
    let report = compatible
        .record_peer_compatibility(compatibility_profile(2))
        .unwrap();
    assert!(report.compatible);
    compatible.mark_peer_ready(1).unwrap();
    compatible.mark_peer_ready(2).unwrap();
    compatible.start_live_when_ready().unwrap();
    let status = compatible.status();
    assert_eq!(status.phase, SessionPhase::Live);
    assert!(status.compatibility_required);
    assert!(status.compatibility_ok);
    assert!(status.compatibility_blockers.is_empty());

    let mut missing = compatibility_lobby();
    missing.mark_peer_ready(1).unwrap();
    missing.mark_peer_ready(2).unwrap();
    let err = missing.start_live_when_ready().unwrap_err().to_string();
    assert!(err.contains("missing_profile"));
    assert_eq!(
        missing.status().compatibility_blockers[0].kind,
        SessionCompatibilityMismatchKind::MissingProfile
    );
}

fn compatibility_lobby() -> SessionManager {
    let mut session = SessionManager::with_config(SessionConfig {
        mode: NetworkMode::Host,
        max_peers: 4,
        allow_late_join: true,
        ..SessionConfig::default()
    })
    .unwrap();
    session
        .require_compatibility_profile(compatibility_profile(1))
        .unwrap();
    session.create_lobby().unwrap();
    session
        .join_peer(
            SessionPlayerIdentity::new(1, 101, "Host Player").with_adapter("headless", "x10-040"),
        )
        .unwrap();
    session
        .join_peer(
            SessionPlayerIdentity::new(2, 102, "Client Player").with_adapter("headless", "x10-040"),
        )
        .unwrap();
    session
}

fn compatibility_profile(peer_id: u64) -> SessionCompatibilityProfile {
    SessionCompatibilityProfile::new(
        peer_id,
        "0.1.0",
        "sgc-plan-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "xace-adapter-1.0.0",
        "assets-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "packages-cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
        "provider-free-dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
        "multiplayer_lobby:v1",
    )
}

fn mismatched_profile(
    peer_id: u64,
    kind: SessionCompatibilityMismatchKind,
) -> SessionCompatibilityProfile {
    let mut profile = compatibility_profile(peer_id);
    match kind {
        SessionCompatibilityMismatchKind::Schema => profile.schema_version = "0.2.0".to_string(),
        SessionCompatibilityMismatchKind::SgcPlan => {
            profile.sgc_plan_hash = "sgc-plan-mismatch".to_string();
        }
        SessionCompatibilityMismatchKind::AdapterVersion => {
            profile.adapter_version = "xace-adapter-2.0.0".to_string();
        }
        SessionCompatibilityMismatchKind::Assets => {
            profile.asset_manifest_hash = "assets-mismatch".to_string();
        }
        SessionCompatibilityMismatchKind::Packages => {
            profile.package_set_hash = "packages-mismatch".to_string();
        }
        SessionCompatibilityMismatchKind::ProviderFreeMetadata => {
            profile.provider_free_metadata_hash = "provider-free-mismatch".to_string();
        }
        SessionCompatibilityMismatchKind::Template => {
            profile.template_id = "arena_shooter:v2".to_string();
        }
        SessionCompatibilityMismatchKind::MissingProfile => {}
    }
    profile
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
