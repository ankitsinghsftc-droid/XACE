use std::collections::{BTreeMap, BTreeSet};

use xace_network_core::authority::{ActionLimit, AuthorityResolver, CheatGuardConfig};
use xace_network_core::input::{
    InputAction, InputPacket, InputSynchroniser, LockstepDecision, MaliciousInputGate,
    MaliciousInputGateConfig, MaliciousInputRejectionKind,
};

const SECRET: &[u8] = b"x10-041-malicious-input-secret";

#[test]
fn x10_041_malicious_packet_matrix_blocks_before_synchroniser_state() {
    assert_rejected(
        MaliciousInputRejectionKind::InvalidPacket,
        invalid_action_packet(),
        10,
        10,
    );
    assert_rejected(
        MaliciousInputRejectionKind::SignatureMissingOrInvalid,
        unsigned_valid_packet(1, 10, 1),
        10,
        10,
    );
    assert_rejected(
        MaliciousInputRejectionKind::FutureTick,
        valid_packet(1, 20, 1, InputAction::axis("move_x", 0.1)),
        10,
        10,
    );
    assert_rejected(
        MaliciousInputRejectionKind::ActionLimitExceeded,
        valid_packet(1, 10, 1, InputAction::axis("look", 0.75)),
        10,
        10,
    );
    assert_rejected(
        MaliciousInputRejectionKind::AuthorityDenied,
        target_entity_packet(1, 10, 1, 900),
        10,
        10,
    );
    assert_rejected(
        MaliciousInputRejectionKind::UnknownPeer,
        valid_packet(2, 10, 1, InputAction::axis("move_x", 0.1)),
        10,
        10,
    );

    let mut gate = gate_with_rate(16);
    let mut sync = InputSynchroniser::new(peers(&[1]), 0);
    let authority = authority();
    gate.submit_authorized(
        valid_packet(1, 10, 1, InputAction::axis("move_x", 0.1)),
        &authority,
        &mut sync,
        10,
        10,
    )
    .unwrap();
    let before_replay = sync.buffer().total_packet_count();
    assert!(gate
        .submit_authorized(
            valid_packet(1, 11, 1, InputAction::axis("move_x", 0.1)),
            &authority,
            &mut sync,
            11,
            11,
        )
        .is_err());
    assert_eq!(sync.buffer().total_packet_count(), before_replay);
    assert_eq!(
        last_rejection_kind(&gate),
        MaliciousInputRejectionKind::SequenceReplay
    );

    let mut rate_gate = gate_with_rate(1);
    let mut rate_sync = InputSynchroniser::new(peers(&[1]), 0);
    rate_gate
        .submit_authorized(
            valid_packet(1, 10, 1, InputAction::axis("move_x", 0.1)),
            &authority,
            &mut rate_sync,
            10,
            10,
        )
        .unwrap();
    let before_rate = rate_sync.buffer().total_packet_count();
    assert!(rate_gate
        .submit_authorized(
            valid_packet(1, 11, 2, InputAction::axis("move_x", 0.1)),
            &authority,
            &mut rate_sync,
            11,
            10,
        )
        .is_err());
    assert_eq!(rate_sync.buffer().total_packet_count(), before_rate);
    assert_eq!(
        last_rejection_kind(&rate_gate),
        MaliciousInputRejectionKind::RateLimitExceeded
    );
}

#[test]
fn x10_041_valid_signed_authorized_packets_release_without_desync() {
    let mut gate = gate_with_rate(16);
    let mut sync = InputSynchroniser::new(peers(&[1, 2]), 0);
    let authority = authority();

    gate.submit_authorized(
        valid_packet(1, 10, 1, InputAction::axis("move_x", 0.25)),
        &authority,
        &mut sync,
        10,
        10,
    )
    .unwrap();
    gate.submit_authorized(
        valid_packet(2, 10, 1, InputAction::button("fire", true)),
        &authority,
        &mut sync,
        10,
        10,
    )
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

    assert_eq!(gate.stats().accepted_count, 2);
    assert_eq!(gate.stats().rejected_count, 0);
    assert_eq!(sync.input_log().summary().record_count, 2);
    assert!(sync.input_log().verify_chain());
}

#[test]
fn x10_041_buffer_reject_does_not_poison_replay_sequence_state() {
    let mut gate = gate_with_rate(16);
    let mut sync = InputSynchroniser::new(peers(&[1]), 0);
    let authority = authority();

    gate.submit_authorized(
        valid_packet(1, 10, 1, InputAction::axis("move_x", 0.1)),
        &authority,
        &mut sync,
        10,
        10,
    )
    .unwrap();
    assert_eq!(sync.buffer().total_packet_count(), 1);

    assert!(gate
        .submit_authorized(
            valid_packet(1, 10, 2, InputAction::axis("move_y", 0.4)),
            &authority,
            &mut sync,
            10,
            10,
        )
        .is_err());
    assert_eq!(
        last_rejection_kind(&gate),
        MaliciousInputRejectionKind::DuplicateTick
    );
    assert_eq!(sync.buffer().total_packet_count(), 1);

    gate.submit_authorized(
        valid_packet(1, 11, 2, InputAction::axis("move_y", 0.4)),
        &authority,
        &mut sync,
        11,
        11,
    )
    .unwrap();
    assert_eq!(sync.buffer().total_packet_count(), 2);
    assert_eq!(gate.cheat_guard().last_sequence_for_peer(1), Some(2));
}

fn assert_rejected(
    expected: MaliciousInputRejectionKind,
    packet: InputPacket,
    server_tick: u64,
    ingress_tick: u64,
) {
    let mut gate = gate_with_rate(16);
    let mut sync = InputSynchroniser::new(peers(&[1]), 0);
    let authority = authority();
    let before_count = sync.buffer().total_packet_count();
    assert!(gate
        .submit_authorized(packet, &authority, &mut sync, server_tick, ingress_tick)
        .is_err());
    assert_eq!(sync.buffer().total_packet_count(), before_count);
    assert_eq!(last_rejection_kind(&gate), expected);
}

fn gate_with_rate(max_packets_per_peer_per_window: usize) -> MaliciousInputGate {
    MaliciousInputGate::new(MaliciousInputGateConfig {
        cheat_guard: strict_cheat_guard_config(),
        max_packets_per_peer_per_window,
        rate_window_ticks: 4,
        max_rejection_log_entries: 64,
    })
}

fn strict_cheat_guard_config() -> CheatGuardConfig {
    let mut allowed_devices = BTreeSet::new();
    allowed_devices.insert("keyboard".to_string());

    let mut allowed_actions = BTreeSet::new();
    for action in ["move_x", "move_y", "look", "fire", "use"] {
        allowed_actions.insert(action.to_string());
    }

    let mut per_action_limits = BTreeMap::new();
    per_action_limits.insert(
        "look".to_string(),
        ActionLimit {
            max_abs_value: 0.5,
            max_abs_secondary_value: 0.5,
            max_per_tick: 1,
        },
    );

    CheatGuardConfig {
        allowed_actions,
        allowed_devices,
        per_action_limits,
        require_player_id: true,
        allow_predicted_input: false,
        require_signature: true,
        signature_secret: Some(SECRET.to_vec()),
        max_sequence_gap: 8,
        max_future_ticks: 2,
        ..CheatGuardConfig::default()
    }
}

fn authority() -> AuthorityResolver {
    let mut authority = AuthorityResolver::with_server(100).unwrap();
    authority.assign_at(900, 2, 0).unwrap();
    authority
}

fn valid_packet(peer_id: u64, tick: u64, sequence_id: u64, action: InputAction) -> InputPacket {
    InputPacket::with_actions(peer_id, tick, sequence_id, vec![action])
        .with_player(1_000 + peer_id)
        .with_device("keyboard")
        .signed(SECRET)
}

fn unsigned_valid_packet(peer_id: u64, tick: u64, sequence_id: u64) -> InputPacket {
    InputPacket::with_actions(
        peer_id,
        tick,
        sequence_id,
        vec![InputAction::axis("move_x", 0.1)],
    )
    .with_player(1_000 + peer_id)
    .with_device("keyboard")
}

fn invalid_action_packet() -> InputPacket {
    InputPacket::with_actions(1, 10, 1, vec![InputAction::axis("move x", 0.1)])
        .with_player(1_001)
        .with_device("keyboard")
        .signed(SECRET)
}

fn target_entity_packet(peer_id: u64, tick: u64, sequence_id: u64, entity_id: u64) -> InputPacket {
    let mut action = InputAction::button("use", true);
    action.target_entity = Some(entity_id);
    valid_packet(peer_id, tick, sequence_id, action)
}

fn last_rejection_kind(gate: &MaliciousInputGate) -> MaliciousInputRejectionKind {
    gate.rejection_log().last().unwrap().kind
}

fn peers(ids: &[u64]) -> BTreeSet<u64> {
    ids.iter().copied().collect()
}
