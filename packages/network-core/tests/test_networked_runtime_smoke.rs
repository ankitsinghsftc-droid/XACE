use std::collections::{BTreeMap, BTreeSet};

use sha2::{Digest, Sha256};
use xace_network_core::input::{InputAction, InputPacket, InputSynchroniser, LockstepDecision};
use xace_network_core::prediction::{
    ClientPredictor, PredictionInput, ReconciliationEngine, ReconciliationMode, Vec3,
};
use xace_network_core::session::{NetworkMode, SessionConfig, SessionManager, SessionPhase};
use xace_network_core::synchronisation::{DesyncDetector, DesyncDetectorConfig, TickBarrier};

#[derive(Debug, Clone, Copy, PartialEq)]
struct RuntimeEntity {
    x: f32,
    z: f32,
    health: f32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct SmokeDigest {
    session: SessionDigest,
    released_ticks: Vec<u64>,
    world_hashes: Vec<String>,
    desync_ticks: Vec<u64>,
    final_hash: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct SessionDigest {
    host_live_peers: usize,
    client_required_input_peers: Vec<u64>,
    host_can_advance: bool,
    client_can_advance: bool,
}

fn peers() -> BTreeSet<u64> {
    BTreeSet::from([1, 2])
}

fn product_session_pair() -> SessionDigest {
    let mut host = SessionManager::new(NetworkMode::Host);
    host.add_peer(1).unwrap();
    host.add_peer(2).unwrap();
    host.mark_peer_live(1).unwrap();
    host.mark_peer_live(2).unwrap();
    host.start_live().unwrap();

    let host_status = host.status();
    assert_eq!(host_status.phase, SessionPhase::Live);
    assert_eq!(host_status.required_input_peers, peers());
    assert!(host.can_advance_simulation());

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

    let client_required = client.required_input_peers();
    assert_eq!(client.phase(), SessionPhase::Live);
    assert_eq!(client_required, BTreeSet::from([1]));
    assert!(client.can_advance_simulation());

    SessionDigest {
        host_live_peers: host_status.peer_stats.live,
        client_required_input_peers: client_required.into_iter().collect(),
        host_can_advance: host.can_advance_simulation(),
        client_can_advance: client.can_advance_simulation(),
    }
}

fn packet(peer_id: u64, tick: u64) -> InputPacket {
    let axis = if peer_id == 1 {
        if tick % 3 == 0 {
            0.5
        } else {
            0.25
        }
    } else if tick % 4 == 0 {
        -0.5
    } else {
        -0.25
    };
    InputPacket::with_actions(
        peer_id,
        tick,
        tick,
        vec![
            InputAction::axis("move_x", axis),
            InputAction::axis("move_z", if peer_id == 1 { 0.125 } else { -0.125 }),
            InputAction::button("attack", tick % 8 == 0),
        ],
    )
    .with_player(100 + peer_id)
    .with_device(format!("peer_{}", peer_id))
}

fn run_smoke(arrival_flip: bool) -> SmokeDigest {
    let session = product_session_pair();
    let mut sync = InputSynchroniser::new(peers(), 0);
    let mut barrier = TickBarrier::new(peers());
    let predictor = ClientPredictor::new(60);
    let reconciler = ReconciliationEngine::new(0.5);
    let mut desync = DesyncDetector::with_config(DesyncDetectorConfig {
        interval_ticks: 12,
        require_authoritative_hash: true,
        max_reports: 8,
        consecutive_divergence_threshold: 1,
    });

    let mut world = BTreeMap::from([
        (
            101,
            RuntimeEntity {
                x: 0.0,
                z: 0.0,
                health: 100.0,
            },
        ),
        (
            102,
            RuntimeEntity {
                x: 3.0,
                z: 0.0,
                health: 100.0,
            },
        ),
    ]);
    let mut released_ticks = Vec::new();
    let mut world_hashes = Vec::new();
    let mut desync_ticks = Vec::new();

    for tick in 1..=36 {
        let order = if arrival_flip && tick % 2 == 0 {
            [2, 1]
        } else {
            [1, 2]
        };
        for peer_id in order {
            let packet = packet(peer_id, tick);
            sync.submit(packet).unwrap();
            barrier.mark_ready_result(peer_id, tick).unwrap();
        }
        assert!(barrier.readiness_for_tick(tick).is_open());
        barrier.advance_to(tick + 1);

        let packets = match sync.decision_for_sim_tick(tick) {
            LockstepDecision::Release {
                tick: released_tick,
                packets,
            } => {
                released_ticks.push(released_tick);
                packets
            }
            other => panic!("expected tick {tick} release, got {other:?}"),
        };

        for packet in packets {
            let entity_id = packet.player_id.unwrap();
            let before = world.get(&entity_id).copied().unwrap();
            let velocity = velocity_from_packet(&packet);
            let predicted = predictor
                .predict(PredictionInput {
                    entity_id,
                    base_tick: tick - 1,
                    target_tick: tick,
                    position: Vec3::new(before.x, 0.0, before.z),
                    velocity,
                    acceleration: Vec3::ZERO,
                })
                .unwrap();
            let after = RuntimeEntity {
                x: round4(before.x + velocity.x / 60.0),
                z: round4(before.z + velocity.z / 60.0),
                health: if packet
                    .actions
                    .iter()
                    .any(|a| a.action == "attack" && a.value > 0.0)
                {
                    before.health - 0.25
                } else {
                    before.health
                },
            };
            let plan = reconciler
                .plan_vec3(
                    entity_id,
                    tick,
                    predicted.position,
                    Vec3::new(after.x, 0.0, after.z),
                    ReconciliationMode::Smooth,
                )
                .unwrap();
            assert!(
                plan.error_distance < 0.01,
                "prediction drift too large: {plan:?}"
            );
            world.insert(entity_id, after);
        }

        let hash = world_hash(&world);
        if desync.should_compare(tick) {
            let mut peer_hashes = BTreeMap::from([(1, hash.clone()), (2, hash.clone())]);
            if tick == 24 {
                peer_hashes.insert(2, "intentional-divergence".to_string());
            }
            if let Some(report) = desync
                .compare_result(tick, &hash, peer_hashes, peers())
                .unwrap()
            {
                assert_eq!(report.divergent_peer_ids(), BTreeSet::from([2]));
                desync_ticks.push(report.tick);
            }
        }
        world_hashes.push(hash);
    }

    SmokeDigest {
        session,
        released_ticks,
        final_hash: world_hash(&world),
        world_hashes,
        desync_ticks,
    }
}

fn velocity_from_packet(packet: &InputPacket) -> Vec3 {
    let mut x = 0.0;
    let mut z = 0.0;
    for action in &packet.actions {
        match action.action.as_str() {
            "move_x" => x = action.value,
            "move_z" => z = action.value,
            _ => {}
        }
    }
    Vec3::new(x, 0.0, z)
}

fn world_hash(world: &BTreeMap<u64, RuntimeEntity>) -> String {
    let mut hasher = Sha256::new();
    for (entity_id, entity) in world {
        hasher.update(entity_id.to_le_bytes());
        hasher.update(entity.x.to_bits().to_le_bytes());
        hasher.update(entity.z.to_bits().to_le_bytes());
        hasher.update(entity.health.to_bits().to_le_bytes());
    }
    format!("{:x}", hasher.finalize())[..16].to_string()
}

fn round4(value: f32) -> f32 {
    (value * 10_000.0).round() / 10_000.0
}

#[test]
fn networked_runtime_smoke_is_deterministic_across_arrival_orders() {
    let normal = run_smoke(false);
    let flipped = run_smoke(true);

    assert_eq!(normal, flipped);
    assert_eq!(normal.released_ticks, (1..=36).collect::<Vec<_>>());
    assert_eq!(normal.desync_ticks, vec![24]);
}
