use std::collections::{BTreeMap, BTreeSet};

use xace_network_core::authority::AuthorityResolver;
use xace_network_core::diagnostics::{
    capture_multiplayer_diagnostics, MULTIPLAYER_DIAGNOSTICS_SCHEMA,
};
use xace_network_core::input::{InputDelayManager, InputPacket, InputSynchroniser, LatencySample};
use xace_network_core::prediction::{RollbackManager, RollbackReason};
use xace_network_core::session::{
    NetworkMode, SessionConfig, SessionManager, SessionPlayerIdentity,
};
use xace_network_core::synchronisation::{DesyncDetector, DesyncDetectorConfig, ResyncEngine};

#[test]
fn x10_042_multiplayer_diagnostics_snapshot_exposes_required_panel_fields() {
    let mut session = SessionManager::with_config(SessionConfig {
        mode: NetworkMode::Host,
        max_peers: 4,
        ..SessionConfig::default()
    })
    .unwrap();
    session.create_lobby().unwrap();
    session
        .join_peer(SessionPlayerIdentity::new(1, 101, "Host Player"))
        .unwrap();
    session
        .join_peer(SessionPlayerIdentity::new(2, 102, "Client Player"))
        .unwrap();
    session.mark_peer_ready(1).unwrap();
    session.mark_peer_ready(2).unwrap();
    session.start_live_when_ready().unwrap();
    session
        .peers_mut()
        .require_mut(1)
        .unwrap()
        .observe_latency(16, 2, 0);
    session
        .peers_mut()
        .require_mut(2)
        .unwrap()
        .observe_latency(96, 12, 25_000);
    session.observe_input(1, 10, 7).unwrap();
    session.observe_input(2, 9, 6).unwrap();
    session.peers_mut().assign_authority(1, 501).unwrap();

    let mut synchroniser = InputSynchroniser::new(peers(&[1, 2]), 0);
    synchroniser
        .submit(InputPacket::unsigned(1, 10, 7))
        .unwrap();

    let mut delay = InputDelayManager::new(60, 1);
    delay.record_sample(
        1,
        LatencySample {
            rtt_ms: 16,
            jitter_ms: 2,
            packet_loss_ppm: 0,
        },
    );
    delay.record_sample(
        2,
        LatencySample {
            rtt_ms: 96,
            jitter_ms: 12,
            packet_loss_ppm: 25_000,
        },
    );

    let mut rollback = RollbackManager::new();
    rollback
        .record_snapshot_with_hash(8, "hash-tick-8", 128)
        .unwrap();
    let _ = rollback
        .begin_rollback(9, 11, 11, RollbackReason::DesyncRecovery)
        .unwrap();
    rollback.complete_latest(11).unwrap();

    let mut desync = DesyncDetector::with_config(DesyncDetectorConfig {
        interval_ticks: 1,
        ..DesyncDetectorConfig::default()
    });
    let report = desync
        .compare_result(
            12,
            "authoritative-hash",
            BTreeMap::from([
                (1, "authoritative-hash".to_string()),
                (2, "divergent-hash".to_string()),
            ]),
            peers(&[1, 2]),
        )
        .unwrap()
        .unwrap();

    let mut resync = ResyncEngine::new();
    resync.begin_from_report(&report, 12).unwrap();
    resync.mark_snapshot_sent(2, 12).unwrap();
    resync.mark_awaiting_ack(2).unwrap();

    let mut authority = AuthorityResolver::with_server(1).unwrap();
    authority.assign_at(501, 1, 10).unwrap();
    authority.assign_at(502, 2, 10).unwrap();

    let snapshot = capture_multiplayer_diagnostics(
        &session,
        &synchroniser,
        delay.recommendation(),
        &rollback,
        &resync,
        &desync,
        &authority,
        10,
    );

    assert_eq!(snapshot.schema, MULTIPLAYER_DIAGNOSTICS_SCHEMA);
    assert_eq!(snapshot.session.peer_total, 2);
    assert_eq!(snapshot.session.live_peers, 2);
    assert_eq!(snapshot.ticks.session_tick, session.tick());
    assert_eq!(snapshot.ticks.simulation_tick, 10);
    assert_eq!(snapshot.ticks.input_tick, Some(10));
    assert_eq!(snapshot.ticks.missing_peers, vec![2]);
    assert_eq!(snapshot.input_buffers.total_packet_count, 1);
    assert_eq!(snapshot.input_buffers.per_peer.len(), 2);
    assert_eq!(snapshot.latency.worst_peer, Some(2));
    assert_eq!(snapshot.latency.max_packet_loss_ppm, 25_000);
    assert_eq!(snapshot.rollback.rollback_count, 1);
    assert_eq!(
        snapshot.rollback.latest_reason.as_deref(),
        Some("desync_recovery")
    );
    assert_eq!(snapshot.resync[0].peer_id, 2);
    assert_eq!(snapshot.resync[0].state, "AwaitingAck");
    assert_eq!(snapshot.hash_comparisons[0].tick, 12);
    assert_eq!(snapshot.hash_comparisons[0].divergent_peers[0].peer_id, 2);
    assert!(snapshot
        .authority
        .iter()
        .any(|row| row.entity_id == 501 && row.owner_peer == Some(1)));
}

fn peers(ids: &[u64]) -> BTreeSet<u64> {
    ids.iter().copied().collect()
}
