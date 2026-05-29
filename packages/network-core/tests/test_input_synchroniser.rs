use std::collections::BTreeSet;

use xace_network_core::input::{
    InputAction, InputDelayConfig, InputDelayManager, InputLog, InputPacket, InputSynchroniser,
    InputSynchroniserConfig, LatencySample, LockstepDecision, TimeoutPolicy,
};

fn peers(ids: &[u64]) -> BTreeSet<u64> {
    ids.iter().copied().collect()
}

#[test]
fn lockstep_waits_until_all_peer_inputs_arrive() {
    let mut sync = InputSynchroniser::new(peers(&[1, 2]), 0);

    sync.submit(InputPacket::with_actions(
        1,
        10,
        1,
        vec![InputAction::axis("move_x", 1.0)],
    ))
    .unwrap();

    assert_eq!(
        sync.decision_for_sim_tick(10),
        LockstepDecision::Wait {
            tick: 10,
            missing_peers: vec![2],
        }
    );

    sync.submit(InputPacket::with_actions(2, 10, 1, Vec::new()))
        .unwrap();

    match sync.decision_for_sim_tick(10) {
        LockstepDecision::Release { tick, packets } => {
            assert_eq!(tick, 10);
            assert_eq!(packets.len(), 2);
            assert_eq!(packets[0].peer_id, 1);
            assert_eq!(packets[1].peer_id, 2);
        }
        other => panic!("expected release, got {other:?}"),
    }
}

#[test]
fn fixed_delay_releases_delayed_target_tick() {
    let mut sync = InputSynchroniser::new(peers(&[7]), 2);
    sync.submit(InputPacket::unsigned(7, 3, 1)).unwrap();

    match sync.decision_for_sim_tick(5) {
        LockstepDecision::Release { tick, .. } => assert_eq!(tick, 3),
        other => panic!("expected delayed release, got {other:?}"),
    }
}

#[test]
fn unknown_peer_input_is_rejected() {
    let mut sync = InputSynchroniser::new(peers(&[1]), 0);
    assert!(sync.submit(InputPacket::unsigned(99, 0, 1)).is_err());
}

#[test]
fn released_tick_is_not_released_twice() {
    let mut sync = InputSynchroniser::new(peers(&[1]), 0);
    sync.submit(InputPacket::unsigned(1, 12, 1)).unwrap();

    assert!(matches!(
        sync.decision_for_sim_tick(12),
        LockstepDecision::Release { tick: 12, .. }
    ));
    assert_eq!(
        sync.decision_for_sim_tick(12),
        LockstepDecision::AlreadyReleased { tick: 12 }
    );
}

#[test]
fn timeout_policy_can_release_synthetic_empty_input() {
    let mut sync = InputSynchroniser::with_config(
        peers(&[1, 2]),
        InputSynchroniserConfig {
            timeout_policy: TimeoutPolicy::ReleaseEmptyAfter { wait_ticks: 2 },
            ..InputSynchroniserConfig::default()
        },
    );
    sync.submit(InputPacket::unsigned(1, 4, 1)).unwrap();

    assert!(matches!(
        sync.decision_for_sim_tick(4),
        LockstepDecision::Wait { tick: 4, .. }
    ));
    assert!(matches!(
        sync.decision_for_sim_tick(5),
        LockstepDecision::Wait { tick: 4, .. }
    ));
    match sync.decision_for_sim_tick(6) {
        LockstepDecision::Release { tick, packets } => {
            assert_eq!(tick, 4);
            assert_eq!(packets.len(), 2);
            assert!(packets.iter().any(|packet| packet.peer_id == 2));
        }
        other => panic!("expected timeout release, got {other:?}"),
    }
}

#[test]
fn delay_manager_uses_worst_peer_and_clamps() {
    let mut delay = InputDelayManager::with_config(InputDelayConfig {
        tick_rate_hz: 60,
        min_delay_ticks: 1,
        max_delay_ticks: 6,
        safety_ticks: 1,
        ..InputDelayConfig::default()
    });

    delay.record_sample(
        1,
        LatencySample {
            rtt_ms: 20,
            jitter_ms: 1,
            packet_loss_ppm: 0,
        },
    );
    delay.record_sample(
        2,
        LatencySample {
            rtt_ms: 240,
            jitter_ms: 10,
            packet_loss_ppm: 20_000,
        },
    );

    let recommendation = delay.recommendation();
    assert_eq!(recommendation.worst_peer, Some(2));
    assert_eq!(recommendation.delay_ticks, 6);
}

#[test]
fn input_log_is_hash_chained_and_idempotent_for_same_packet() {
    let mut log = InputLog::new();
    let first = InputPacket::unsigned(1, 1, 1);
    let second = InputPacket::unsigned(2, 1, 1);

    log.append_result(first.clone()).unwrap();
    let head_after_first = log.deterministic_hash();
    log.append_result(first).unwrap();
    assert_eq!(log.deterministic_hash(), head_after_first);

    log.append_result(second).unwrap();
    assert!(log.verify_chain());
    assert_eq!(log.summary().record_count, 2);
    assert_ne!(log.deterministic_hash(), head_after_first);
}
