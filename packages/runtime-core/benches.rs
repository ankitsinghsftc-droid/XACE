use criterion::{black_box, criterion_group, criterion_main, Criterion};
use xace_core::contracts::interfaces::{ISystem, ISystemContext};
use xace_core::entity_state::EntityState;
use xace_core::errors::determinism_error::GuardMode;
use xace_core::errors::xace_error::XaceError;
use xace_core::runtime::phase_enum::PhaseEnum;
use xace_core::runtime::world_snapshot::{ComponentTableSnapshot, EntityRecord, WorldSnapshot};
use xace_runtime_core::component_tables::component_table_store::ComponentTableStore;
use xace_runtime_core::determinism_guard::rng_interceptor::RngInterceptor;
use xace_runtime_core::determinism_guard::world_hasher::WorldHasher;
use xace_runtime_core::entity_store::entity_store::EntityStore;
use xace_runtime_core::mutation_gate::MutationGate;
use xace_runtime_core::phase_orchestrator::parallel_executor::ParallelExecutor;
use xace_runtime_core::phase_orchestrator::system_registry::SystemRegistry;
use xace_runtime_core::query_engine::QueryEngine;
use xace_runtime_core::snapshot_engine::SnapshotEngine;

struct BenchNoopSystem {
    id: String,
}

impl ISystem for BenchNoopSystem {
    fn system_id(&self) -> &str {
        &self.id
    }

    fn execute(&self, _context: &mut dyn ISystemContext) -> Result<(), XaceError> {
        Ok(())
    }

    fn declared_reads(&self) -> &[u32] {
        &[]
    }

    fn declared_writes(&self) -> &[u32] {
        &[]
    }
}

fn synthetic_snapshot(entity_count: u64) -> WorldSnapshot {
    let mut snapshot = WorldSnapshot::empty("0.1.0", 1, 42);
    snapshot.tick = 777;
    snapshot.entity_store_snapshot.next_entity_id = entity_count + 1;
    let mut table = ComponentTableSnapshot::new(1, "COMP_TRANSFORM_V1");

    for entity_id in 1..=entity_count {
        snapshot
            .entity_store_snapshot
            .entities
            .push(EntityRecord::new(entity_id, EntityState::Active, 0));
        table.set(
            entity_id,
            format!(
                r#"{{"position_x":{},"position_y":0,"position_z":{}}}"#,
                entity_id,
                entity_id % 17
            ),
        );
    }

    snapshot.component_tables_snapshot.set_table(table);
    snapshot
}

fn synthetic_world(entity_count: u64) -> (EntityStore, ComponentTableStore) {
    let mut entity_store = EntityStore::new();
    let mut table_store = ComponentTableStore::new();
    table_store.register_table(1, "COMP_TRANSFORM_V1").unwrap();

    for entity_id in 1..=entity_count {
        let created = entity_store.create_entity(0).unwrap();
        assert_eq!(created, entity_id);
        table_store
            .add_component(
                entity_id,
                1,
                format!(
                    r#"{{"position_x":{},"position_y":0,"position_z":{}}}"#,
                    entity_id,
                    entity_id % 17
                ),
                0,
            )
            .unwrap();
    }

    (entity_store, table_store)
}

fn synthetic_parallel_policy_executor(
    system_count: usize,
) -> (
    ParallelExecutor,
    SystemRegistry,
    EntityStore,
    ComponentTableStore,
    MutationGate,
    QueryEngine,
    Vec<String>,
) {
    let mut registry = SystemRegistry::new();
    let mut system_ids = Vec::with_capacity(system_count);

    for index in 0..system_count {
        let id = format!("bench_noop_{index:03}");
        registry
            .register(Box::new(BenchNoopSystem { id: id.clone() }))
            .unwrap();
        system_ids.push(id);
    }

    (
        ParallelExecutor::new(),
        registry,
        EntityStore::new(),
        ComponentTableStore::new(),
        MutationGate::new(),
        QueryEngine::new(),
        system_ids,
    )
}

fn bench_world_hash(c: &mut Criterion) {
    let snapshot = synthetic_snapshot(1_000);
    c.bench_function("determinism/world_hash_sha256_1000_entities", |b| {
        b.iter(|| WorldHasher::compute(black_box(&snapshot)))
    });
}

fn bench_snapshot_capture(c: &mut Criterion) {
    let (entity_store, table_store) = synthetic_world(1_000);
    c.bench_function("determinism/snapshot_capture_1000_entities", |b| {
        b.iter(|| {
            let mut engine = SnapshotEngine::standard("0.1.0", 1, 42);
            engine
                .take_snapshot(
                    black_box(777),
                    black_box(&entity_store),
                    black_box(&table_store),
                )
                .unwrap()
        })
    });
}

fn bench_rng_window(c: &mut Criterion) {
    let interceptor = RngInterceptor::new(42, GuardMode::Strict);
    c.bench_function("determinism/rng_window_open_request_drop", |b| {
        b.iter(|| {
            let _window = interceptor.open_window("sys_bench_rng", black_box(123));
            interceptor
                .request_rng("sys_bench_rng", black_box(123))
                .unwrap()
        })
    });
}

fn bench_mutation_snapshot_per_batch(c: &mut Criterion) {
    let (mut entity_store, mut table_store) = synthetic_world(1_000);
    let mut gate = MutationGate::new();
    c.bench_function(
        "mutation_atomicity/snapshot_per_batch_empty_1000_entities_threshold_1000ms",
        |b| {
            b.iter(|| {
                gate.apply_all(
                    black_box(&mut entity_store),
                    black_box(&mut table_store),
                    777,
                )
                .unwrap()
            })
        },
    );
}

fn bench_parallel_policy_deterministic_sequential(c: &mut Criterion) {
    let (
        executor,
        registry,
        entity_store,
        table_store,
        mut mutation_gate,
        mut query_engine,
        system_ids,
    ) = synthetic_parallel_policy_executor(32);
    c.bench_function(
        "parallel_policy/deterministic_sequential_sgc_parallel_group_32_systems",
        |b| {
            b.iter(|| {
                executor
                    .execute_parallel(
                        black_box(&system_ids),
                        black_box(&registry),
                        black_box(&entity_store),
                        black_box(&table_store),
                        black_box(&mut mutation_gate),
                        black_box(&mut query_engine),
                        black_box(777),
                        black_box(42),
                        PhaseEnum::Simulation,
                        None,
                        None,
                    )
                    .unwrap()
            })
        },
    );
}

criterion_group!(
    benches,
    bench_world_hash,
    bench_snapshot_capture,
    bench_rng_window,
    bench_mutation_snapshot_per_batch,
    bench_parallel_policy_deterministic_sequential
);
criterion_main!(benches);
