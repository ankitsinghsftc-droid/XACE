use std::collections::{BTreeMap, BTreeSet};

use xace_network_core::synchronisation::{
    BarrierState, DesyncDetector, DesyncDetectorConfig, LateJoinConfig, LateJoinHandler,
    LateJoinState, ResyncConfig, ResyncEngine, ResyncState, TickBarrier,
};

#[test]
fn desync_detection_respects_interval_and_reports_divergence() {
    let mut detector = DesyncDetector::new(30);
    let mut peer_hashes = BTreeMap::new();
    peer_hashes.insert(1, "hash_ok".to_string());
    peer_hashes.insert(2, "hash_bad".to_string());

    assert!(detector
        .compare(29, "hash_ok", peer_hashes.clone())
        .is_none());

    let report = detector.compare(30, "hash_ok", peer_hashes).unwrap();
    assert_eq!(report.tick, 30);
    assert_eq!(report.divergent_peers, vec![(2, "hash_bad".to_string())]);

    let instructions = ResyncEngine::instructions_for_report(&report);
    assert_eq!(instructions.len(), 1);
    assert_eq!(instructions[0].peer_id, 2);
    assert_eq!(instructions[0].snapshot_tick, 30);
}

#[test]
fn desync_detector_tracks_missing_peers_and_consecutive_counts() {
    let mut detector = DesyncDetector::with_config(DesyncDetectorConfig {
        interval_ticks: 10,
        consecutive_divergence_threshold: 2,
        ..DesyncDetectorConfig::default()
    });
    let expected = BTreeSet::from([1, 2, 3]);

    let mut peer_hashes = BTreeMap::new();
    peer_hashes.insert(1, "ok".to_string());
    peer_hashes.insert(2, "bad".to_string());

    let first = detector
        .compare_result(10, "ok", peer_hashes.clone(), expected.clone())
        .unwrap()
        .unwrap();
    assert_eq!(first.missing_peers, vec![3]);
    assert_eq!(detector.consecutive_divergence_for(2), 1);
    assert!(!first.is_confirmed(2));

    let second = detector
        .compare_result(20, "ok", peer_hashes, expected)
        .unwrap()
        .unwrap();
    assert!(second.is_confirmed(2));
    assert_eq!(
        detector.summary().peers_with_divergence,
        BTreeSet::from([2])
    );
}

#[test]
fn tick_barrier_opens_only_when_required_peers_are_ready_for_tick() {
    let mut barrier = TickBarrier::new(BTreeSet::from([1, 2]));
    barrier.mark_ready_result(1, 0).unwrap();
    assert_eq!(
        barrier.state(),
        BarrierState::Waiting {
            tick: 0,
            missing_peers: vec![2]
        }
    );

    barrier.mark_ready_result(2, 0).unwrap();
    assert_eq!(barrier.state(), BarrierState::Open(0));
    assert!(barrier.opened_ticks().contains(&0));

    barrier.advance();
    assert_eq!(barrier.current_tick(), 1);
    assert!(matches!(barrier.state(), BarrierState::Waiting { .. }));
}

#[test]
fn resync_engine_retries_and_acknowledges_sessions() {
    let mut detector = DesyncDetector::new(5);
    let mut peer_hashes = BTreeMap::new();
    peer_hashes.insert(9, "bad".to_string());
    let report = detector.compare(5, "good", peer_hashes).unwrap();

    let mut resync = ResyncEngine::with_config(ResyncConfig {
        max_delta_ticks: 20,
        ack_timeout_ticks: 3,
        max_attempts: 2,
    });
    let instructions = resync.begin_from_report(&report, 8).unwrap();
    assert_eq!(instructions[0].target_tick, 8);

    resync.mark_snapshot_sent(9, 8).unwrap();
    resync.mark_awaiting_ack(9).unwrap();
    let retries = resync.retry_due(12);
    assert_eq!(retries.len(), 1);
    assert_eq!(retries[0].attempt, 2);

    resync.mark_snapshot_sent(9, 12).unwrap();
    resync.acknowledge(9, 13, "good").unwrap();
    assert_eq!(resync.session(9).unwrap().state, ResyncState::Complete);
    assert_eq!(resync.remove_terminal(), 1);
}

#[test]
fn late_join_handler_batches_catchup_and_transitions_live() {
    let mut handler = LateJoinHandler::with_config(LateJoinConfig {
        max_catch_up_ticks: 16,
        batch_size: 3,
        snapshot_grace_ticks: 1,
    });

    let plan = handler.plan_for_peer(4, 10, 16).unwrap();
    assert_eq!(plan.catch_up_ticks, vec![11, 12, 13, 14, 15, 16]);
    assert_eq!(plan.batches.len(), 2);

    handler.mark_snapshot_queued(4).unwrap();
    handler.mark_catching_up(4).unwrap();
    assert_eq!(
        handler.consume_batch(4).unwrap().unwrap().ticks,
        vec![11, 12, 13]
    );
    assert_eq!(
        handler.plan_for(4).unwrap().state,
        LateJoinState::CatchingUp
    );
    assert_eq!(
        handler.consume_batch(4).unwrap().unwrap().ticks,
        vec![14, 15, 16]
    );
    assert_eq!(handler.plan_for(4).unwrap().state, LateJoinState::Live);
}
