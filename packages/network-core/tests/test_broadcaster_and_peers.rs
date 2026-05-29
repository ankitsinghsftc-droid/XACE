use std::collections::BTreeSet;

use xace_network_core::input::{
    DeliveryFailureReason, DeliveryKey, InputBroadcaster, InputBroadcasterConfig, InputPacket,
};
use xace_network_core::session::{ConnectionState, PeerManager};

fn peers(ids: &[u64]) -> BTreeSet<u64> {
    ids.iter().copied().collect()
}

#[test]
fn broadcaster_queues_to_other_peers_and_acks_by_key() {
    let mut broadcaster = InputBroadcaster::new();
    let packet = InputPacket::unsigned(1, 10, 5);

    broadcaster
        .queue_for_peers_result(packet.clone(), &peers(&[1, 2, 3]), 100)
        .unwrap();
    assert_eq!(broadcaster.pending_count(), 2);

    let key = DeliveryKey::new(2, &packet);
    assert!(matches!(
        broadcaster.ack_key(key),
        xace_network_core::input::DeliveryAckResult::Acked
    ));
    assert_eq!(broadcaster.pending_count(), 1);
    assert_eq!(broadcaster.stats().acked_total, 1);
}

#[test]
fn broadcaster_retransmits_with_backoff_and_fails_after_attempt_limit() {
    let mut broadcaster = InputBroadcaster::with_config(InputBroadcasterConfig {
        resend_after_ticks: 2,
        max_attempts: 2,
        expire_after_ticks: 100,
        queue_self_echo: false,
    });
    broadcaster
        .queue_for_peers_result(InputPacket::unsigned(1, 1, 1), &peers(&[2]), 0)
        .unwrap();

    let (due, failures) = broadcaster.due_for_retransmit_with_failures(2);
    assert_eq!(due.len(), 1);
    assert!(failures.is_empty());
    assert_eq!(due[0].attempts, 2);

    let (due, failures) = broadcaster.due_for_retransmit_with_failures(6);
    assert!(due.is_empty());
    assert_eq!(failures.len(), 1);
    assert_eq!(
        failures[0].reason,
        DeliveryFailureReason::MaxAttemptsExceeded
    );
    assert_eq!(broadcaster.pending_count(), 0);
}

#[test]
fn peer_manager_tracks_lifecycle_authority_and_timeouts() {
    let mut peers = PeerManager::new();
    peers.add_peer_at(10, 0).unwrap();
    peers
        .set_state_at(10, ConnectionState::Handshaking, 1)
        .unwrap();
    peers.set_state_at(10, ConnectionState::Syncing, 2).unwrap();
    peers.set_state_at(10, ConnectionState::Live, 3).unwrap();

    peers.assign_authority(10, 99).unwrap();
    assert_eq!(peers.authority_owner(99), Some(10));
    assert_eq!(peers.live_peer_ids(), btree_set([10]));

    peers.observe_heartbeat(10, 5).unwrap();
    assert!(peers.timed_out_peers(20, 10).contains(&10));

    let timed_out = peers.mark_timeouts_reconnecting(20, 10).unwrap();
    assert_eq!(timed_out, vec![10]);
    assert_eq!(
        peers.require(10).unwrap().state,
        ConnectionState::Reconnecting
    );
}

#[test]
fn peer_manager_rejects_invalid_transition() {
    let mut peers = PeerManager::new();
    peers.add_peer_at(1, 0).unwrap();
    assert!(peers.set_state_at(1, ConnectionState::Live, 1).is_err());
}

fn btree_set(values: impl IntoIterator<Item = u64>) -> BTreeSet<u64> {
    values.into_iter().collect()
}
