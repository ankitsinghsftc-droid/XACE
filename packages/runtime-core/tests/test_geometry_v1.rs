use serde_json::{json, Value};
use xace_core::contracts::interfaces::{ISystem, ISystemContext};
use xace_core::errors::xace_error::XaceError;
use xace_core::fixed_point::Fixed64;
use xace_core::geometry::*;
use xace_core::world::WORLD_COORDINATE_LIMIT as LIMIT;
use xace_runtime_core::component_tables::ComponentTableStore;
use xace_runtime_core::entity_store::EntityStore;
use xace_runtime_core::event_bus::event_bus::EventBus;
use xace_runtime_core::geometry::{GeometryBody, GeometryScene};
use xace_runtime_core::mutation_gate::MutationGate;
use xace_runtime_core::phase_orchestrator::phase_orchestrator::PhaseOrchestrator;
use xace_runtime_core::phase_orchestrator::system_context::SystemContext;
use xace_runtime_core::phase_orchestrator::system_registry::SystemRegistry;
use xace_runtime_core::query_engine::QueryEngine;
use xace_runtime_core::snapshot_engine::SnapshotEngine;

fn v(a: [i64; 3]) -> [Fixed64; 3] {
    a.map(Fixed64::from_raw)
}
fn box_at(c: [i64; 3], h: [i64; 3]) -> Aabb {
    Aabb {
        center: v(c),
        half_extents: v(h),
    }
}
fn body(id: u64, c: [i64; 3], h: [i64; 3]) -> GeometryBody {
    GeometryBody {
        entity_id: id,
        object_id: None,
        bounds: box_at(c, h),
        is_trigger: false,
        layer_mask: 1,
    }
}
fn filter() -> GeometryFilter {
    GeometryFilter::default()
}
fn sweep(s: &GeometryScene, c: [i64; 3], d: [i64; 3]) -> Vec<GeometryContact> {
    s.sweep(box_at(c, [1; 3]), v(d), filter()).unwrap()
}
#[test]
fn exact_fraction_and_conservative_travel_in_all_six_directions() {
    for axis in 0..3 {
        for sign in [-1, 1] {
            let mut c = [0; 3];
            c[axis] = 5 * sign;
            let mut d = [0; 3];
            d[axis] = 7 * sign;
            let scene = GeometryScene::new(vec![body(9, c, [1; 3])]).unwrap();
            let hits = sweep(&scene, [0; 3], d);
            assert_eq!(hits.len(), 1);
            let hit = &hits[0];
            assert_eq!((hit.time_numerator, hit.time_denominator), (3, 7));
            assert_eq!(hit.normal, AxisNormal::from_axis(axis, sign < 0).unwrap());
            let mut expected = [0; 3];
            expected[axis] = 3 * sign;
            assert_eq!(hit.travel, v(expected));
        }
    }
}
#[test]
fn corners_initial_overlap_zero_motion_and_touching_policy() {
    let scene = GeometryScene::new(vec![body(1, [5, 5, 0], [1; 3])]).unwrap();
    assert_eq!(
        sweep(&scene, [0; 3], [7, 7, 0])[0].normal,
        AxisNormal::NegativeX
    );
    let scene = GeometryScene::new(vec![body(1, [0; 3], [1; 3])]).unwrap();
    let overlap = sweep(&scene, [0; 3], [0; 3]);
    assert!(overlap[0].initial_overlap);
    assert_eq!(overlap[0].normal, AxisNormal::NegativeX);
    assert_eq!(overlap[0].time_numerator, 0);
    assert!(sweep(&scene, [-2, 0, 0], [-1, 0, 0]).is_empty());
    assert!(sweep(&scene, [-2, 0, 0], [0, 1, 0]).is_empty());
    assert!(sweep(&scene, [-2, 0, 0], [0; 3]).is_empty());
    assert_eq!(sweep(&scene, [-2, 0, 0], [1, 0, 0])[0].time_numerator, 0);
    assert!(scene
        .overlap(box_at([-2, 0, 0], [1; 3]), filter())
        .unwrap()
        .is_empty());
    assert_eq!(
        scene.overlap(box_at([-1, 0, 0], [1; 3]), filter()).unwrap(),
        vec![1]
    );
    // A corner grazed for zero duration does not block.
    assert!(sweep(&scene, [-3, 1, 0], [2, 2, 0]).is_empty());
}
#[test]
fn permutation_and_equal_hit_order_is_canonical() {
    let bodies = vec![
        body(8, [7, 0, 0], [1; 3]),
        body(3, [5, 0, 0], [1; 3]),
        body(1, [5, 0, 0], [1; 3]),
    ];
    let reference = sweep(
        &GeometryScene::new(bodies.clone()).unwrap(),
        [0; 3],
        [10, 0, 0],
    );
    assert_eq!(
        reference.iter().map(|h| h.entity_id).collect::<Vec<_>>(),
        vec![1, 3, 8]
    );
    for order in [
        [0, 1, 2],
        [0, 2, 1],
        [1, 0, 2],
        [1, 2, 0],
        [2, 0, 1],
        [2, 1, 0],
    ] {
        assert_eq!(
            sweep(
                &GeometryScene::new(order.map(|i| bodies[i].clone()).to_vec()).unwrap(),
                [0; 3],
                [10, 0, 0]
            ),
            reference
        );
    }
}
#[test]
fn no_tunneling_at_maximum_speed_through_two_micro_unit_wall() {
    let s = GeometryScene::new(vec![body(2, [8_000_000, 0, 0], [1, 100, 100])]).unwrap();
    let hit = &sweep(&s, [0; 3], [MAX_DISPLACEMENT_RAW, 0, 0])[0];
    assert_eq!(hit.travel[0].raw(), 7_999_998);
    assert_eq!(hit.normal, AxisNormal::NegativeX);
}
#[test]
fn exhaustive_axis_corpus_matches_independent_integer_gap_oracle() {
    for axis in 0..3 {
        for sign in [-1, 1] {
            for gap in 0..=30 {
                for speed in 0..=30 {
                    let mut c = [0; 3];
                    c[axis] = (gap + 2) * sign;
                    let mut d = [0; 3];
                    d[axis] = speed * sign;
                    let s = GeometryScene::new(vec![body(1, c, [1; 3])]).unwrap();
                    let hits = sweep(&s, [0; 3], d);
                    let expected = speed > 0 && gap <= speed;
                    assert_eq!(
                        !hits.is_empty(),
                        expected,
                        "axis {axis} sign {sign} gap {gap} speed {speed}"
                    );
                    if expected {
                        assert_eq!(
                            hits[0].time_numerator as i128 * speed as i128,
                            hits[0].time_denominator as i128 * gap as i128
                        );
                        assert_eq!(hits[0].travel[axis].raw(), gap * sign);
                    }
                }
            }
        }
    }
}
#[test]
fn rejects_overflow_extents_motion_and_scene_bounds_without_panics() {
    for bad in [i64::MIN, i64::MAX, 0, -1, LIMIT / 2 + 1] {
        assert!(GeometryScene::new(vec![body(1, [0; 3], [bad, 1, 1])]).is_err());
    }
    assert!(GeometryScene::new(vec![body(0, [0; 3], [1; 3])]).is_err());
    assert!(GeometryScene::new(vec![body(1, [0; 3], [1; 3]); 2]).is_err());
    assert!(GeometryScene::new((1..=4097).map(|id| body(id, [0; 3], [1; 3])).collect()).is_err());
    let s = GeometryScene::new(vec![]).unwrap();
    for d in [
        [i64::MIN, 0, 0],
        [i64::MAX, 0, 0],
        [16_000_001, 0, 0],
        [16_000_000, 1, 0],
    ] {
        assert!(s.sweep(box_at([0; 3], [1; 3]), v(d), filter()).is_err());
    }
    assert!(s
        .sweep(box_at([LIMIT - 1, 0, 0], [1; 3]), v([1, 0, 0]), filter())
        .is_err());
    assert!(s
        .sweep(box_at([-LIMIT + 1, 0, 0], [1; 3]), v([-1, 0, 0]), filter())
        .is_err());
    assert!(s
        .sweep(box_at([LIMIT - 1, 0, 0], [1; 3]), v([0; 3]), filter())
        .is_ok());
}
#[test]
fn trigger_layer_and_self_filters_are_explicit() {
    let mut a = body(1, [0; 3], [2; 3]);
    a.is_trigger = true;
    let mut b = body(2, [0; 3], [2; 3]);
    b.layer_mask = 2;
    let s = GeometryScene::new(vec![a, b]).unwrap();
    let bounds = box_at([0; 3], [1; 3]);
    assert_eq!(s.overlap(bounds, filter()).unwrap(), vec![2]);
    assert_eq!(
        s.overlap(
            bounds,
            GeometryFilter {
                selection: GeometrySelection::All,
                ..filter()
            }
        )
        .unwrap(),
        vec![1, 2]
    );
    assert_eq!(
        s.overlap(
            bounds,
            GeometryFilter {
                selection: GeometrySelection::Triggers,
                ..filter()
            }
        )
        .unwrap(),
        vec![1]
    );
    assert!(s
        .overlap(
            bounds,
            GeometryFilter {
                layer_mask: 1,
                ..filter()
            }
        )
        .unwrap()
        .is_empty());
    assert!(s
        .overlap(
            bounds,
            GeometryFilter {
                exclude: Some(2),
                ..filter()
            }
        )
        .unwrap()
        .is_empty());
}
fn transform(c: [i64; 3]) -> Value {
    json!({"position":{"x":c[0],"y":c[1],"z":c[2]},
    "rotation":{"x":0,"y":0,"z":0,"w":1000000},"scale":{"x":1000000,"y":1000000,"z":1000000},"parent_entity_id":0})
}
fn collider() -> Value {
    json!({"shape":"BOX","size":{"x":2,"y":2,"z":2},"offset":{"x":0,"y":0,"z":0},"is_trigger":false})
}
fn setup() -> (EntityStore, ComponentTableStore, MutationGate, QueryEngine) {
    let mut es = EntityStore::new();
    let mut ts = ComponentTableStore::new();
    ts.register_table(1, "COMP_TRANSFORM_V1").unwrap();
    ts.register_table(4, "COMP_COLLIDER_V1").unwrap();
    for c in [[5, 0, 0], [0, -5, 0], [-5, 0, 0]] {
        let id = es.create_entity(0).unwrap();
        ts.add_component(id, 1, transform(c).to_string(), 0)
            .unwrap();
        ts.add_component(id, 4, collider().to_string(), 0).unwrap();
    }
    (es, ts, MutationGate::new(), QueryEngine::new())
}
fn query(
    q: &GeometryQueryV1,
    reads: &[u32],
    es: &EntityStore,
    ts: &ComponentTableStore,
    mg: &mut MutationGate,
    qe: &mut QueryEngine,
) -> Result<GeometryResultV1, XaceError> {
    SystemContext::new("query", reads, &[], es, ts, mg, qe, 0, 42).geometry_query_v1(q)
}
fn right() -> GeometryQueryV1 {
    GeometryQueryV1::Probe {
        bounds: box_at([0; 3], [1; 3]),
        direction: AxisNormal::PositiveX,
        distance: Fixed64::from_raw(8),
        filter: filter(),
    }
}
#[test]
fn scheduled_context_ground_side_and_declared_access() {
    let (es, ts, mut mg, mut qe) = setup();
    for reads in [&[][..], &[1][..], &[4][..]] {
        assert!(query(&right(), reads, &es, &ts, &mut mg, &mut qe).is_err());
    }
    let result = query(&right(), &[1, 4], &es, &ts, &mut mg, &mut qe).unwrap();
    let GeometryResultV1::Contacts(hits) = result else {
        panic!()
    };
    assert_eq!(hits[0].entity_id, 1);
    let ground = GeometryQueryV1::Probe {
        bounds: box_at([0; 3], [1; 3]),
        direction: AxisNormal::NegativeY,
        distance: Fixed64::from_raw(8),
        filter: filter(),
    };
    let GeometryResultV1::Contacts(hits) =
        query(&ground, &[1, 4], &es, &ts, &mut mg, &mut qe).unwrap()
    else {
        panic!()
    };
    assert_eq!(hits[0].entity_id, 2);
    assert_eq!(hits[0].normal, AxisNormal::PositiveY);
    assert!(mg.is_empty());
}
#[test]
fn squared_distance_targeting_ties_radius_and_wide_intermediates() {
    let (es, mut ts, mut mg, mut qe) = setup();
    let nearest = |ids| GeometryQueryV1::Nearest {
        origin: v([0; 3]),
        max_distance: Fixed64::from_raw(5),
        candidates: ids,
    };
    assert_eq!(
        query(&nearest(vec![3, 2, 1]), &[1], &es, &ts, &mut mg, &mut qe).unwrap(),
        GeometryResultV1::Nearest(Some(GeometryTarget {
            entity_id: 1,
            object_id: None,
            distance_squared: 25
        }))
    );
    assert!(query(&nearest(vec![]), &[], &es, &ts, &mut mg, &mut qe).is_err());
    assert!(query(&nearest(vec![1, 1]), &[1], &es, &ts, &mut mg, &mut qe).is_err());
    assert!(query(&nearest(vec![99]), &[1], &es, &ts, &mut mg, &mut qe).is_err());
    ts.update_component(1, 1, transform([LIMIT, 0, 0]).to_string(), 0)
        .unwrap();
    let far = GeometryQueryV1::Nearest {
        origin: v([-LIMIT, 0, 0]),
        max_distance: Fixed64::from_raw(2 * LIMIT),
        candidates: vec![1],
    };
    assert_eq!(
        query(&far, &[1], &es, &ts, &mut mg, &mut qe).unwrap(),
        GeometryResultV1::Nearest(Some(GeometryTarget {
            entity_id: 1,
            object_id: None,
            distance_squared: (2 * LIMIT as u128).pow(2)
        }))
    );
    for radius in [i64::MIN, -1, 2 * LIMIT + 1, i64::MAX] {
        let q = GeometryQueryV1::Nearest {
            origin: v([0; 3]),
            max_distance: Fixed64::from_raw(radius),
            candidates: vec![],
        };
        assert!(query(&q, &[1], &es, &ts, &mut mg, &mut qe).is_err());
    }
}
#[test]
fn unsupported_shapes_transforms_and_malformed_numbers_fail_closed() {
    for (component, path, value) in [
        (4, "shape", json!("SPHERE")),
        (4, "size/x", json!(3)),
        (4, "size/x", json!(2.0)),
        (4, "offset/x", json!(i64::MAX)),
        (4, "layer_mask", json!(-1)),
        (1, "rotation/w", json!(1)),
        (1, "scale/y", json!(2)),
        (1, "parent_entity_id", json!(1)),
        (1, "position/x", json!("2")),
        (1, "position/y", json!(i64::MIN)),
    ] {
        let (es, mut ts, mut mg, mut qe) = setup();
        let mut c = if component == 1 {
            transform([5, 0, 0])
        } else {
            collider()
        };
        if path.contains('/') {
            *c.pointer_mut(&format!("/{path}")).unwrap() = value;
        } else {
            c[path] = value;
        }
        ts.update_component(1, component, c.to_string(), 0).unwrap();
        assert!(
            query(&right(), &[1, 4], &es, &ts, &mut mg, &mut qe).is_err(),
            "{component} {path}"
        );
    }
}
#[test]
fn restore_rebuilds_geometry_and_kinematic_offsets_are_authoritative() {
    let (mut es, mut ts, mut mg, mut qe) = setup();
    let before = query(&right(), &[1, 4], &es, &ts, &mut mg, &mut qe).unwrap();
    let mut snapshots = SnapshotEngine::standard("0.1.0", 1, 42);
    let snapshot = snapshots.take_snapshot(0, &es, &ts).unwrap();
    mg.request_modify_component(1, 1, transform([7, 0, 0]).to_string(), &es, &ts, 0)
        .unwrap();
    mg.apply_all(&mut es, &mut ts, 0).unwrap();
    assert_ne!(
        query(&right(), &[1, 4], &es, &ts, &mut mg, &mut qe).unwrap(),
        before
    );
    snapshots
        .restore_snapshot(&snapshot, &mut es, &mut ts)
        .unwrap();
    assert_eq!(
        query(&right(), &[1, 4], &es, &ts, &mut mg, &mut qe).unwrap(),
        before
    );
    let mut c = collider();
    c["offset"]["x"] = json!(2);
    ts.update_component(1, 4, c.to_string(), 0).unwrap();
    let GeometryResultV1::Contacts(h) =
        query(&right(), &[1, 4], &es, &ts, &mut mg, &mut qe).unwrap()
    else {
        panic!()
    };
    assert_eq!(h[0].travel[0].raw(), 5);
}
struct MoveSystem;
impl ISystem for MoveSystem {
    fn system_id(&self) -> &str {
        "move"
    }
    fn declared_reads(&self) -> &[u32] {
        &[1, 4]
    }
    fn declared_writes(&self) -> &[u32] {
        &[1]
    }
    fn execute(&self, ctx: &mut dyn ISystemContext) -> Result<(), XaceError> {
        let GeometryResultV1::Contacts(hits) = ctx.geometry_query_v1(&right())? else {
            panic!()
        };
        let x = hits.first().map_or(0, |h| h.travel[0].raw());
        ctx.submit_mutation(3, 1, transform([x, 10, 0]).to_string())
    }
}
struct InvalidSystem;
impl ISystem for InvalidSystem {
    fn system_id(&self) -> &str {
        "invalid"
    }
    fn declared_reads(&self) -> &[u32] {
        &[1, 4]
    }
    fn declared_writes(&self) -> &[u32] {
        &[1]
    }
    fn execute(&self, ctx: &mut dyn ISystemContext) -> Result<(), XaceError> {
        ctx.submit_mutation(1, 1, transform([100, 0, 0]).to_string())?;
        let bad = GeometryQueryV1::Sweep {
            bounds: box_at([0; 3], [1; 3]),
            displacement: v([i64::MAX, 0, 0]),
            filter: filter(),
        };
        let _caught_error = ctx.geometry_query_v1(&bad);
        Ok(()) // Deliberate attempt to swallow validation failure.
    }
}
#[test]
fn failed_geometry_rolls_back_prior_phases_and_queued_writes_and_halts() {
    for parallel in [false, true] {
        let (mut es, mut ts, mut mg, mut qe) = setup();
        let mut eb = EventBus::new();
        let mut snapshots = SnapshotEngine::standard("0.1.0", 1, 42);
        let before = snapshots.take_snapshot(0, &es, &ts).unwrap();
        let mut reg = SystemRegistry::new();
        reg.register(Box::new(MoveSystem)).unwrap();
        reg.register(Box::new(InvalidSystem)).unwrap();
        let plan = vec![
            ("Simulation", vec!["move".into()], false),
            ("PostSimulation", vec!["invalid".into()], parallel),
        ];
        let mut orch = PhaseOrchestrator::new(42, "0.1.0", 1);
        assert!(orch
            .tick(&plan, &reg, &mut es, &mut ts, &mut mg, &mut qe, &mut eb)
            .is_err());
        assert_eq!(
            snapshots.take_snapshot(0, &es, &ts).unwrap().world_hash,
            before.world_hash
        );
        assert!(mg.is_empty());
        assert_eq!(orch.current_tick(), 0);
        assert!(orch
            .tick(&[], &reg, &mut es, &mut ts, &mut mg, &mut qe, &mut eb)
            .is_err());
        snapshots
            .restore_snapshot(&before, &mut es, &mut ts)
            .unwrap();
        orch.restore_tick(0);
        assert!(orch
            .tick(&[], &reg, &mut es, &mut ts, &mut mg, &mut qe, &mut eb)
            .is_ok());
    }
}
#[test]
fn scheduled_query_movement_replays_identical_hashes_after_restore() {
    let (mut es, mut ts, mut mg, mut qe) = setup();
    let mut eb = EventBus::new();
    let mut snapshots = SnapshotEngine::standard("0.1.0", 1, 42);
    let before = snapshots.take_snapshot(0, &es, &ts).unwrap();
    let mut reg = SystemRegistry::new();
    reg.register(Box::new(MoveSystem)).unwrap();
    let plan = vec![("Simulation", vec!["move".into()], false)];
    let mut orch = PhaseOrchestrator::new(42, "0.1.0", 1);
    let mut hashes = Vec::new();
    for _ in 0..3 {
        hashes.push(
            orch.tick(&plan, &reg, &mut es, &mut ts, &mut mg, &mut qe, &mut eb)
                .unwrap()
                .world_hash,
        );
    }
    snapshots
        .restore_snapshot(&before, &mut es, &mut ts)
        .unwrap();
    orch.restore_tick(0);
    println!(
        "XP004_REPLAY_HASHES={}",
        serde_json::to_string(&hashes).unwrap()
    );
    for expected in hashes {
        assert_eq!(
            orch.tick(&plan, &reg, &mut es, &mut ts, &mut mg, &mut qe, &mut eb)
                .unwrap()
                .world_hash,
            expected
        );
    }
}
#[test]
fn xp003_world_contract_and_cgs_geometry_match() {
    // Authoritative actor payloads from the actual XP-003 compiler golden fixture.
    let cgs: Value = serde_json::from_str(include_str!(
        "../../core/tests/fixtures/world_contract_v2/source.cgs.json"
    ))
    .unwrap();
    let world = xace_core::world::WorldContract::from_bytes(include_bytes!(
        "../../core/tests/fixtures/world_contract_v2/world.canonical.json"
    ))
    .unwrap();
    let mut es = EntityStore::new();
    let mut ts = ComponentTableStore::new();
    ts.register_table(1, "COMP_TRANSFORM_V1").unwrap();
    ts.register_table(4, "COMP_COLLIDER_V1").unwrap();
    let mut bindings = std::collections::BTreeMap::new();
    for actor in cgs["modes"][0]["actors"].as_array().unwrap() {
        let id = es.create_entity(0).unwrap();
        bindings.insert(actor["id"].as_str().unwrap(), id);
        for c in actor["components"].as_array().unwrap() {
            let kind = c["type_id"].as_u64().unwrap() as u32;
            if [1, 4].contains(&kind) {
                ts.add_component(id, kind, c["defaults"].to_string(), 0)
                    .unwrap();
            }
        }
    }
    let mut mg = MutationGate::new();
    let mut qe = QueryEngine::new();
    for obj in world.objects {
        if let Some(h) = obj.half_extents {
            let q = GeometryQueryV1::Overlap {
                bounds: Aabb {
                    center: [obj.position.x, obj.position.y, obj.position.z],
                    half_extents: [h.x, h.y, h.z],
                },
                filter: GeometryFilter {
                    selection: GeometrySelection::All,
                    ..filter()
                },
            };
            let id = bindings[String::from(obj.actor_id).as_str()];
            assert_eq!(
                query(&q, &[1, 4], &es, &ts, &mut mg, &mut qe).unwrap(),
                GeometryResultV1::Overlaps(vec![id])
            );
        }
    }
}

#[test]
fn stable_world_id_breaks_equal_hits_independently_of_entity_assignment() {
    for reversed in [false, true] {
        let mut a = body(if reversed { 2 } else { 1 }, [5, 0, 0], [1; 3]);
        let mut b = body(if reversed { 1 } else { 2 }, [5, 0, 0], [1; 3]);
        a.object_id = Some("wall_a".to_string().try_into().unwrap());
        b.object_id = Some("wall_b".to_string().try_into().unwrap());
        let hits = sweep(&GeometryScene::new(vec![b, a]).unwrap(), [0; 3], [7, 0, 0]);
        assert_eq!(String::from(hits[0].object_id.clone().unwrap()), "wall_a");
        assert_eq!(hits[0].entity_id, if reversed { 2 } else { 1 });
    }
}

#[test]
fn validated_world_bindings_reach_the_scheduled_context_and_reject_aliases() {
    let world = xace_core::world::WorldContract::from_bytes(include_bytes!(
        "../../core/tests/fixtures/world_contract_v2/world.canonical.json"
    ))
    .unwrap();
    let (es, ts, mut mg, mut qe) = setup();
    let actors = world
        .objects
        .iter()
        .enumerate()
        .map(|(i, o)| (o.actor_id.clone(), i as u64 + 1))
        .collect();
    qe.bind_world_geometry(&world, &actors).unwrap();
    let GeometryResultV1::Contacts(hits) =
        query(&right(), &[1, 4], &es, &ts, &mut mg, &mut qe).unwrap()
    else {
        panic!()
    };
    assert_eq!(hits[0].object_id, Some(world.objects[0].id.clone()));
    let invalid = world
        .objects
        .iter()
        .map(|o| (o.actor_id.clone(), 1))
        .collect();
    assert!(qe.bind_world_geometry(&world, &invalid).is_err());
    assert!(qe
        .bind_world_geometry(&world, &std::collections::BTreeMap::new())
        .is_err());
    let GeometryResultV1::Contacts(hits) =
        query(&right(), &[1, 4], &es, &ts, &mut mg, &mut qe).unwrap()
    else {
        panic!()
    };
    assert_eq!(hits[0].object_id, Some(world.objects[0].id.clone()));
}

struct RandomEventSystem;
impl ISystem for RandomEventSystem {
    fn system_id(&self) -> &str {
        "random_event"
    }
    fn declared_reads(&self) -> &[u32] {
        &[]
    }
    fn declared_writes(&self) -> &[u32] {
        &[]
    }
    fn execute(&self, ctx: &mut dyn ISystemContext) -> Result<(), XaceError> {
        ctx.next_random()?;
        ctx.emit_event(xace_core::events::event_struct::Event::broadcast(
            1,
            xace_core::events::event_type::EventType::Domain("geometry.proof".into()),
            ctx.current_tick(),
            xace_core::runtime::phase_enum::PhaseEnum::Simulation,
        ))
    }
}
#[test]
fn guarded_geometry_failure_restores_rng_events_and_world() {
    use xace_core::errors::determinism_error::GuardMode;
    use xace_runtime_core::determinism_guard::{
        determinism_guard::DeterminismGuard, rng_interceptor::RngInterceptor,
    };
    let (mut es, mut ts, mut mg, mut qe) = setup();
    let mut eb = EventBus::new();
    let mut reg = SystemRegistry::new();
    reg.register(Box::new(RandomEventSystem)).unwrap();
    reg.register(Box::new(InvalidSystem)).unwrap();
    let mut guard = DeterminismGuard::new(GuardMode::Strict, "0.1.0", 1);
    guard.register_systems(&["random_event", "invalid"]);
    let rng = RngInterceptor::new(42, GuardMode::Strict);
    let mut orch = PhaseOrchestrator::new(42, "0.1.0", 1);
    let plan = vec![
        ("Simulation", vec!["random_event".into()], false),
        ("PostSimulation", vec!["invalid".into()], false),
    ];
    assert!(orch
        .tick_with_guard(
            &plan, &reg, &mut es, &mut ts, &mut mg, &mut qe, &mut eb, &mut guard, &rng, ""
        )
        .is_err());
    assert_eq!(eb.total_emitted(), 0);
    assert_eq!(eb.total_dispatched(), 0);
    assert!(eb.dispatch_log().is_empty());
    assert!(rng.accesses_for_system("random_event").is_empty());
    assert_eq!(rng.violation_count(), 0);
    assert_eq!(
        ts.get_component(1, 1).unwrap(),
        transform([5, 0, 0]).to_string().as_str()
    );
    assert!(mg.is_empty());
}
#[test]
fn bound_target_ties_and_probe_validation_are_deterministic() {
    let world = xace_core::world::WorldContract::from_bytes(include_bytes!(
        "../../core/tests/fixtures/world_contract_v2/world.canonical.json"
    ))
    .unwrap();
    let (es, ts, mut mg, mut qe) = setup();
    let mut actors: std::collections::BTreeMap<_, _> = world
        .objects
        .iter()
        .enumerate()
        .map(|(i, o)| (o.actor_id.clone(), i as u64 + 1))
        .collect();
    actors.insert(world.objects[0].actor_id.clone(), 3);
    actors.insert(world.objects[2].actor_id.clone(), 1);
    qe.bind_world_geometry(&world, &actors).unwrap();
    let q = GeometryQueryV1::Nearest {
        origin: v([0; 3]),
        max_distance: Fixed64::from_raw(5),
        candidates: vec![1, 2, 3],
    };
    let GeometryResultV1::Nearest(Some(target)) =
        query(&q, &[1], &es, &ts, &mut mg, &mut qe).unwrap()
    else {
        panic!()
    };
    assert_eq!(target.entity_id, 3);
    assert_eq!(target.object_id, Some(world.objects[0].id.clone()));
    for distance in [-1, i64::MIN, i64::MAX, MAX_DISPLACEMENT_RAW + 1] {
        let q = GeometryQueryV1::Probe {
            bounds: box_at([0; 3], [1; 3]),
            direction: AxisNormal::NegativeY,
            distance: Fixed64::from_raw(distance),
            filter: filter(),
        };
        assert!(query(&q, &[1, 4], &es, &ts, &mut mg, &mut qe).is_err());
    }
}

#[test]
fn semantic_v3_compound_bindings_and_profile_selection() {
    use std::collections::BTreeMap;
    use xace_core::world::v3::WorldContractV3;
    let world = WorldContractV3::from_bytes(include_bytes!(
        "../../core/tests/fixtures/world_contract_v3/world.canonical.json"
    ))
    .unwrap();
    let mut instances = BTreeMap::new();
    for o in &world.objects {
        let next = instances.len() as u64 + 1;
        instances
            .entry((o.actor_id.clone(), o.instance_index))
            .or_insert(next);
    }
    let ship = instances[&("spaceship".to_string().try_into().unwrap(), 1)];
    let (es, mut ts, mut mg, mut qe) = setup();
    qe.bind_world_v3(&world, &instances).unwrap();
    let ctx = SystemContext::new("semantics", &[], &[], &es, &ts, &mut mg, &mut qe, 0, 42);
    let objects = ctx.world_objects_v3(ship).unwrap();
    assert_eq!(objects.len(), 2);
    assert_eq!(
        ctx.world_capabilities_v1(ship).unwrap(),
        vec!["project.observable.v1"]
    );
    let mut exotic = collider();
    exotic["shape"] = json!("SPHERE");
    ts.update_component(1, 4, exotic.to_string(), 0).unwrap();
    // No members of the AABB profile: unrelated colliders are not interpreted.
    assert_eq!(
        query(&right(), &[1, 4], &es, &ts, &mut mg, &mut qe).unwrap(),
        GeometryResultV1::Contacts(vec![])
    );
    assert!(qe.bind_world_v3(&world, &BTreeMap::new()).is_err());
    // Failed replacement leaves the previous immutable binding installed.
    assert_eq!(
        SystemContext::new("semantics", &[], &[], &es, &ts, &mut mg, &mut qe, 0, 42)
            .world_objects_v3(ship)
            .unwrap(),
        objects
    );
}
#[test]
fn nearest_accepts_rotation_scale_and_filtered_geometry_is_not_validated() {
    let (es, mut ts, mut mg, mut qe) = setup();
    let mut t = transform([5, 0, 0]);
    t["rotation"]["y"] = json!(1000000);
    t["scale"]["x"] = json!(2000000);
    ts.update_component(1, 1, t.to_string(), 0).unwrap();
    let nearest = GeometryQueryV1::Nearest {
        origin: v([0; 3]),
        max_distance: Fixed64::from_raw(10),
        candidates: vec![1],
    };
    assert!(matches!(
        query(&nearest, &[1], &es, &ts, &mut mg, &mut qe).unwrap(),
        GeometryResultV1::Nearest(Some(_))
    ));
    let mut c = collider();
    c["shape"] = json!("SPHERE");
    c["layer_mask"] = json!(2);
    ts.update_component(1, 4, c.to_string(), 0).unwrap();
    let mut f = filter();
    f.layer_mask = 1;
    let q = GeometryQueryV1::Overlap {
        bounds: box_at([0; 3], [1; 3]),
        filter: f,
    };
    assert!(query(&q, &[1, 4], &es, &ts, &mut mg, &mut qe).is_ok());
}
