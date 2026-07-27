use std::collections::BTreeSet;

use xace_network_core::input::{
    InputAction, InputPacket, InputSynchroniser, LockstepDecision,
};

fn peers(ids: &[u64]) -> BTreeSet<u64> {
    ids.iter().copied().collect()
}

fn packet(peer_id: u64, tick: u64, sequence_id: u64) -> InputPacket {
    let axis = if peer_id == 1 { 0.25 } else { -0.25 };
    InputPacket::with_actions(
        peer_id,
        tick,
        sequence_id,
        vec![
            InputAction::axis("move_x", axis),
            InputAction::button("fire", tick % 5 == 0),
        ],
    )
    .with_player(100 + peer_id)
    .with_device(format!("peer_{}", peer_id))
}

fn run_lockstep(arrival_flip: bool) -> Vec<(u64, Vec<(u64, String)>)> {
    let mut sync = InputSynchroniser::new(peers(&[1, 2]), 0);
    let mut released = Vec::new();

    for tick in 1..=48 {
        let first = if arrival_flip && tick % 2 == 0 { 2 } else { 1 };
        let second = if first == 1 { 2 } else { 1 };

        sync.submit(packet(first, tick, tick)).unwrap();
        assert!(matches!(
            sync.decision_for_sim_tick(tick),
            LockstepDecision::Wait { .. }
        ));

        sync.submit(packet(second, tick, tick)).unwrap();
        match sync.decision_for_sim_tick(tick) {
            LockstepDecision::Release { tick, packets } => {
                let digests = packets
                    .into_iter()
                    .map(|packet| (packet.peer_id, packet.deterministic_digest()))
                    .collect::<Vec<_>>();
                released.push((tick, digests));
            }
            other => panic!("expected lockstep release, got {other:?}"),
        }
    }

    released
}

#[test]
fn multiplayer_lockstep_release_is_independent_of_arrival_order() {
    let a = run_lockstep(false);
    let b = run_lockstep(true);
    assert_eq!(a, b);
    assert_eq!(a.len(), 48);
}

#[test]
fn multiplayer_lockstep_never_advances_with_missing_peer_input() {
    let mut sync = InputSynchroniser::new(peers(&[1, 2]), 0);
    sync.submit(packet(1, 7, 1)).unwrap();

    assert_eq!(
        sync.decision_for_sim_tick(7),
        LockstepDecision::Wait {
            tick: 7,
            missing_peers: vec![2],
        }
    );
}
