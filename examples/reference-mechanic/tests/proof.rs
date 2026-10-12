use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::path::Path;
use std::sync::{Arc, Mutex};
use xace_core::contracts::interfaces::{ISystem, ISystemContext};
use xace_core::errors::xace_error::XaceError;
use xace_core::world::{WorldContract, WorldManifest};
use xace_reference_mechanic::*;
use xace_runtime_core::cgs_loader::{load_and_spawn_with_plan_policy, SgcPlanPolicy, SpawnSummary};
use xace_runtime_core::event_bus::event_bus::EventBus;
use xace_runtime_core::phase_orchestrator::{
    phase_orchestrator::{PhaseOrchestrator, TickResult},
    system_registry::SystemRegistry,
};
use xace_runtime_core::{
    component_tables::ComponentTableStore, entity_store::EntityStore, mutation_gate::MutationGate,
    query_engine::QueryEngine, snapshot_engine::SnapshotEngine,
};

#[derive(Debug, Clone, Copy, Default)]
struct Frame {
    x: i64,
    z: i64,
    jump: bool,
}
struct RecordedInput {
    frames: Arc<Mutex<Vec<Frame>>>,
    player: u64,
}
impl ISystem for RecordedInput {
    fn system_id(&self) -> &str {
        "reference.recorded_input.v1"
    }
    fn declared_reads(&self) -> &[u32] {
        &[6, STATE_ID]
    }
    fn declared_writes(&self) -> &[u32] {
        &[6]
    }
    fn execute(&self, ctx: &mut dyn ISystemContext) -> Result<(), XaceError> {
        let frame = self
            .frames
            .lock()
            .unwrap()
            .get(ctx.current_tick() as usize)
            .copied()
            .unwrap_or_default();
        for id in ctx.query_entities(&[STATE_ID])? {
            let f = if id == self.player {
                frame
            } else {
                Frame::default()
            };
            let mut value: Value =
                serde_json::from_str(ctx.get_component(id, 6)?.unwrap()).unwrap();
            value["move_x"] = json!(f.x);
            value["move_z"] = json!(f.z);
            value["jump_pressed"] = json!(f.jump);
            ctx.submit_mutation(id, 6, value.to_string())?;
        }
        Ok(())
    }
}
struct Host {
    es: EntityStore,
    ts: ComponentTableStore,
    mg: MutationGate,
    qe: QueryEngine,
    eb: EventBus,
    orch: PhaseOrchestrator,
    reg: SystemRegistry,
    summary: SpawnSummary,
    frames: Arc<Mutex<Vec<Frame>>>,
    player: u64,
    target: u64,
    world: WorldContract,
    bindings: BTreeMap<xace_core::wire::session_contract::ContractId, u64>,
}
impl Host {
    fn new(third: ThirdAttempt) -> Self {
        let root = std::env::var_os("XACE_REFERENCE_FIXTURE_ROOT")
            .map(std::path::PathBuf::from)
            .unwrap_or_else(|| Path::new(env!("CARGO_MANIFEST_DIR")).join("fixtures"));
        let root = if third == ThirdAttempt::Disabled {
            root
        } else {
            root.join("reversal_shockwave")
        };
        let mut es = EntityStore::new();
        let mut ts = ComponentTableStore::new();
        let summary = load_and_spawn_with_plan_policy(
            &root.join("game.cgs.json"),
            &mut es,
            &mut ts,
            SgcPlanPolicy::RequirePersisted,
            Some(&root.join("execution_plan.json")),
        )
        .unwrap();
        let world =
            WorldContract::from_bytes(&std::fs::read(root.join("world.json")).unwrap()).unwrap();
        let manifest: WorldManifest =
            serde_json::from_slice(&std::fs::read(root.join("world.manifest.json")).unwrap())
                .unwrap();
        manifest
            .verify(
                &world,
                &summary.cgs_hash.clone().try_into().unwrap(),
                &summary.schema_version.clone().try_into().unwrap(),
            )
            .unwrap();
        let bindings: BTreeMap<_, _> = summary
            .spawned_actors
            .iter()
            .map(|a| (a.actor_id.clone().try_into().unwrap(), a.entity_ids[0]))
            .collect();
        let lookup = |name: &str| bindings[&name.to_string().try_into().unwrap()];
        let player = lookup("player");
        let target = lookup("target");
        let mut qe = QueryEngine::new();
        qe.bind_world_geometry(&world, &bindings).unwrap();
        let frames = Arc::new(Mutex::new(Vec::new()));
        let mut reg = SystemRegistry::new();
        reg.register(Box::new(RecordedInput {
            frames: frames.clone(),
            player,
        }))
        .unwrap();
        reg.register(Box::new(ReferenceSystem)).unwrap();
        // The persisted SGC schedule and ordinary ISystem contract agree exactly.
        for (id, access) in &summary.schedule_plan.system_access {
            let system = reg.get(id).unwrap();
            assert_eq!(system.declared_reads(), access.reads);
            assert_eq!(system.declared_writes(), access.writes);
        }
        assert_eq!(
            summary
                .schedule_plan
                .system_access
                .iter()
                .filter(|(_, a)| a.writes.contains(&1))
                .count(),
            1
        );
        let orch =
            PhaseOrchestrator::new(42, &summary.schema_version, summary.execution_plan_version);
        let host = Self {
            es,
            ts,
            mg: MutationGate::new(),
            qe,
            eb: EventBus::new(),
            orch,
            reg,
            summary,
            frames,
            player,
            target,
            world,
            bindings,
        };

        host
    }
    fn value(&self, id: u64, kind: u32) -> Value {
        serde_json::from_str(self.ts.get_component(id, kind).unwrap()).unwrap()
    }
    fn state(&self) -> State {
        serde_json::from_value(self.value(self.player, STATE_ID)).unwrap()
    }
    fn set(&mut self, id: u64, kind: u32, value: Value) {
        self.mg
            .request_modify_component(
                id,
                kind,
                value.to_string(),
                &self.es,
                &self.ts,
                self.orch.current_tick(),
            )
            .unwrap();
        self.mg
            .apply_all(&mut self.es, &mut self.ts, self.orch.current_tick())
            .unwrap();
    }
    fn step(&mut self, f: Frame) -> Result<TickResult, XaceError> {
        self.frames.lock().unwrap().push(f);
        self.tick()
    }
    fn tick(&mut self) -> Result<TickResult, XaceError> {
        self.orch.tick(
            &self.summary.phase_plan_for_runtime(),
            &self.reg,
            &mut self.es,
            &mut self.ts,
            &mut self.mg,
            &mut self.qe,
            &mut self.eb,
        )
    }
}
fn script() -> Vec<Frame> {
    [
        true, false, true, false, false, false, true, false, true, true,
    ]
    .into_iter()
    .map(|jump| Frame {
        x: -1_000_000,
        z: 1_000_000,
        jump,
    })
    .collect()
}
fn event_names(r: &TickResult) -> Vec<String> {
    r.emitted_events
        .iter()
        .map(|e| serde_json::to_string(&e.event_type).unwrap())
        .collect()
}
#[test]
fn endurance_route_stays_on_fixture_floor_past_previous_failure_tick() {
    // XP-022's 60-frame route is deliberately closed. The old short golden
    // recording drifted off the finite arena when repeated for a long soak.
    for (third, direction) in [(ThirdAttempt::Disabled, 1), (ThirdAttempt::ReversalShockwave, -1)] {
        let mut host = Host::new(third);
        let initial_z = host.value(host.player, 1)["position"]["z"].as_i64().unwrap();
        for tick in 0..50_040 {
            let z = direction * if tick % 60 < 30 { 250_000 } else { -250_000 };
            host.step(Frame { x:0, z, jump:false }).unwrap();
            let position = host.value(host.player,1)["position"].clone();
            assert!((position["z"].as_i64().unwrap()-initial_z).abs() <= 2_000_000, "tick {tick}: {position}");
            assert!(position["y"].as_i64().unwrap().abs() <= 3_000_000, "tick {tick}: {position}");
        }
        assert_eq!(host.value(host.player,1)["position"]["z"].as_i64().unwrap(),initial_z);
    }
}
#[test]
fn two_chained_jumps_and_disabled_third_attempt_are_real_state_transitions() {
    let mut h = Host::new(ThirdAttempt::Disabled);
    let mut events = Vec::new();
    for f in script() {
        let result = h.step(f).unwrap();
        events.extend(event_names(&result));
    }
    assert_eq!(
        events.iter().filter(|s| s.contains("wall_jump")).count(),
        2,
        "{events:?}"
    );
    assert!(
        events.iter().any(|s| s.contains("jump_denied")),
        "{events:?}"
    );
    assert!(!events.iter().any(|s| s.contains("shockwave")));
    assert_eq!(h.state().chain, 2);
    assert!(!h.state().third_used);
}
#[test]
fn configured_third_attempt_reverses_and_shockwave_changes_other_actor_once() {
    let mut h = Host::new(ThirdAttempt::ReversalShockwave);
    let mut events = Vec::new();
    let mut reversed = false;
    for f in script() {
        let r = h.step(f).unwrap();
        let names = event_names(&r);
        if names.iter().any(|s| s.contains("third_attempt")) {
            reversed = true;
            assert!(h.value(h.player, 5)["linear"]["z"].as_i64().unwrap() < 0);
            assert!(h.value(h.target, 5)["linear"]["x"].as_i64().unwrap() > 0);
        }
        events.extend(names);
    }
    assert!(reversed, "{events:?}");
    assert_eq!(
        events
            .iter()
            .filter(|s| s.contains("third_attempt"))
            .count(),
        1
    );
    assert_eq!(
        events
            .iter()
            .filter(|s| s.contains("shockwave_hit"))
            .count(),
        1
    );
    assert_eq!(h.state().chain, 2);
    assert!(h.state().third_used);
}
#[test]
fn untagged_surface_never_enables_wall_run_or_jump() {
    let mut h = Host::new(ThirdAttempt::Disabled);
    for o in &mut h.world.objects {
        o.capabilities.clear();
    }
    h.qe.bind_world_geometry(&h.world, &h.bindings).unwrap();
    for f in script() {
        let r = h.step(f).unwrap();
        assert!(!event_names(&r).iter().any(|n| n.contains("wall_jump")));
        assert_ne!(h.state().mode, "wall_running");
    }
    assert_eq!(h.state().chain, 0);
}
#[test]
fn contact_loss_does_not_reset_chain_but_landing_does() {
    let mut h = Host::new(ThirdAttempt::ReversalShockwave);
    for f in script() {
        h.step(f).unwrap();
    }
    assert_eq!(h.state().chain, 2);
    let mut t = h.value(h.player, 1);
    t["position"] = json!({"x":5_000_000,"y":2_000_000,"z":0});
    h.set(h.player, 1, t);
    let mut vel = h.value(h.player, 5);
    vel["linear"] = json!({"x":0,"y":0,"z":0});
    h.set(h.player, 5, vel);
    h.step(Frame::default()).unwrap();
    assert_eq!(h.state().wall_entity, 0);
    assert_eq!(h.state().chain, 2);
    for _ in 0..100 {
        h.step(Frame::default()).unwrap();
        if h.state().grounded {
            break;
        }
    }
    assert!(h.state().grounded);
    assert_eq!(h.state().chain, 0);
    assert!(!h.state().third_used);
}
#[test]
fn jump_hold_is_not_a_second_edge_and_contact_drives_wall_running() {
    let mut h = Host::new(ThirdAttempt::Disabled);
    h.step(Frame {
        x: 0,
        z: 1_000_000,
        jump: false,
    })
    .unwrap();
    assert_eq!(h.state().mode, "wall_running");
    h.step(Frame {
        x: -1_000_000,
        z: 0,
        jump: true,
    })
    .unwrap();
    assert_eq!(h.state().chain, 1);
    for _ in 0..5 {
        h.step(Frame {
            x: -1_000_000,
            z: 0,
            jump: true,
        })
        .unwrap();
    }
    assert_eq!(h.state().chain, 1);
}
#[test]
fn recorded_inputs_replay_identical_hashes_and_events_for_both_configurations() {
    for third in [ThirdAttempt::Disabled, ThirdAttempt::ReversalShockwave] {
        let mut h = Host::new(third);
        let mut snapshots = SnapshotEngine::standard(
            &h.summary.schema_version,
            h.summary.execution_plan_version,
            42,
        );
        let snapshot = snapshots.take_snapshot(0, &h.es, &h.ts).unwrap();
        let events = h.eb.rollback_snapshot();
        let mut expected = Vec::new();
        for f in script() {
            let r = h.step(f).unwrap();
            expected.push((
                r.world_hash.clone(),
                serde_json::to_value(&r.emitted_events).unwrap(),
            ));
        }
        snapshots
            .restore_snapshot(&snapshot, &mut h.es, &mut h.ts)
            .unwrap();
        h.eb.restore_rollback_snapshot(events);
        h.orch.restore_tick(0);
        for e in &expected {
            let r = h.tick().unwrap();
            assert_eq!(
                &(
                    r.world_hash.clone(),
                    serde_json::to_value(&r.emitted_events).unwrap()
                ),
                e
            );
        }
        println!(
            "XP005_REPLAY_{third:?}={}",
            serde_json::to_string(&expected).unwrap()
        );
    }
}
#[test]
fn invalid_config_rolls_back_input_and_movement_and_removal_needs_no_core_change() {
    let mut h = Host::new(ThirdAttempt::Disabled);
    let mut cfg = h.value(h.player, CONFIG_ID);
    cfg["jump_speed"] = json!(i64::MAX);
    h.set(h.player, CONFIG_ID, cfg);
    let mut se = SnapshotEngine::standard(
        &h.summary.schema_version,
        h.summary.execution_plan_version,
        42,
    );
    let before = se.take_snapshot(0, &h.es, &h.ts).unwrap();
    assert!(h.step(Frame::default()).is_err());
    assert_eq!(
        se.take_snapshot(0, &h.es, &h.ts).unwrap().world_hash,
        before.world_hash
    );
    assert!(h.mg.is_empty());
    let mut fresh = Host::new(ThirdAttempt::Disabled);
    fresh.reg = SystemRegistry::new();
    // Removing package + its plan entries leaves the standard runtime operational.
    assert!(fresh
        .orch
        .tick(
            &[],
            &fresh.reg,
            &mut fresh.es,
            &mut fresh.ts,
            &mut fresh.mg,
            &mut fresh.qe,
            &mut fresh.eb
        )
        .is_ok());
    assert!(!fresh.reg.has_system(SYSTEM_ID));
    assert!(fresh
        .reg
        .validate_execution_plan_systems(&[SYSTEM_ID])
        .is_err());
}

#[test]
fn fixture_uses_any_declared_capability_without_a_core_name_branch() {
    let mut h = Host::new(ThirdAttempt::Disabled);
    let capability = "custom.surface_17.v9";
    h.world.capability_declarations[0].id = capability.to_string().try_into().unwrap();
    for object in &mut h.world.objects {
        if !object.capabilities.is_empty() {
            object.capabilities = vec![capability.into()];
        }
    }
    h.qe.bind_world_geometry(&h.world, &h.bindings).unwrap();
    let mut cfg = h.value(h.player, CONFIG_ID);
    cfg["surface_capability"] = json!(capability);
    h.set(h.player, CONFIG_ID, cfg);
    let mut jumps = 0;
    for f in script() {
        jumps += event_names(&h.step(f).unwrap())
            .iter()
            .filter(|e| e.contains("wall_jump"))
            .count();
    }
    assert_eq!(jumps, 2);
}
#[test]
fn corner_contact_uses_stable_world_id_and_only_one_jump() {
    let mut h = Host::new(ThirdAttempt::Disabled);
    let wall = h.bindings[&"wall".to_string().try_into().unwrap()];
    let mut t = h.value(wall, 1);
    t["position"] = json!({"x":0,"y":5_000_000,"z":-750_000});
    let mut c = h.value(wall, 4);
    c["size"] = json!({"x":20_000_000,"y":10_000_000,"z":1_000_000});
    h.mg.request_spawn(
        "corner",
        BTreeMap::from([
            (1, t.to_string()),
            (2, json!({"entity_name":"corner"}).to_string()),
            (4, c.to_string()),
        ]),
        &h.ts,
        0,
    )
    .unwrap();
    h.mg.apply_all(&mut h.es, &mut h.ts, 0).unwrap();
    let corner = *h.es.get_all_present().last().unwrap();
    let mut object = h
        .world
        .objects
        .iter()
        .find(|o| String::from(o.id.clone()) == "wall")
        .unwrap()
        .clone();
    object.id = "corner".to_string().try_into().unwrap();
    object.actor_id = object.id.clone();
    object.position.x = xace_core::fixed_point::Fixed64::ZERO;
    object.position.z = xace_core::fixed_point::Fixed64::from_raw(-750_000);
    object.half_extents.as_mut().unwrap().x = xace_core::fixed_point::Fixed64::from_raw(10_000_000);
    object.half_extents.as_mut().unwrap().z = xace_core::fixed_point::Fixed64::from_raw(500_000);
    h.bindings.insert(object.actor_id.clone(), corner);
    h.world.objects.push(object);
    h.world.objects.sort_by(|a, b| a.id.cmp(&b.id));
    h.qe.bind_world_geometry(&h.world, &h.bindings).unwrap();
    let r = h
        .step(Frame {
            x: 0,
            z: 0,
            jump: true,
        })
        .unwrap();
    assert_eq!(h.state().wall_entity, corner);
    assert_eq!(h.state().chain, 1);
    assert_eq!(
        event_names(&r)
            .iter()
            .filter(|e| e.contains("wall_jump"))
            .count(),
        1
    );
    assert!(h.value(h.player, 5)["linear"]["z"].as_i64().unwrap() > 0);
}

#[test]
fn migrated_semantic_world_uses_the_same_reference_system_and_tick_results() {
    let world = xace_core::world::v3::WorldContractV3::from_bytes(include_bytes!(
        "../../../packages/core/tests/fixtures/world_contract_v3/migrated_reference.world.json"
    ))
    .unwrap();
    for third in [ThirdAttempt::Disabled, ThirdAttempt::ReversalShockwave] {
        let mut legacy = Host::new(third);
        let mut generic = Host::new(third);
        let instances = generic
            .bindings
            .iter()
            .map(|(actor, entity)| ((actor.clone(), 0), *entity))
            .collect();
        generic.qe.bind_world_v3(&world, &instances).unwrap();
        for frame in script() {
            let a = legacy.step(frame).unwrap();
            let b = generic.step(frame).unwrap();
            assert_eq!(a.world_hash, b.world_hash);
            assert_eq!(
                serde_json::to_value(a.emitted_events).unwrap(),
                serde_json::to_value(b.emitted_events).unwrap()
            );
        }
    }
}
