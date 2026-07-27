use criterion::{black_box, criterion_group, criterion_main, Criterion};
use xace_core::schema::system_definition::{ExecutionPhase, SystemDefinition, SystemVersion};
use xace_system_graph_compiler::sgc_pipeline::SgcPipeline;

const SGC_COMPILE_100_THRESHOLD_MS: u64 = 1_000;

fn generated_systems(count: usize) -> Vec<SystemDefinition> {
    (0..count)
        .map(|index| SystemDefinition {
            id: format!("GeneratedSystem{index:03}"),
            display_name: format!("GeneratedSystem{index:03}"),
            phase: ExecutionPhase::Simulation,
            reads: vec![1000 + index as u32],
            writes: vec![2000 + index as u32],
            depends_on: if index == 0 {
                Vec::new()
            } else {
                vec![format!("GeneratedSystem{:03}", index - 1)]
            },
            deterministic: true,
            version: SystemVersion::INITIAL,
            description: String::new(),
        })
        .collect()
}

fn bench_sgc_compile_100_systems(c: &mut Criterion) {
    let systems = generated_systems(100);
    c.bench_function("sgc/compile_100_systems_threshold_1000ms", |b| {
        b.iter(|| {
            let plan = SgcPipeline::compile_and_verify(
                black_box(&systems),
                black_box("0.1.0"),
                black_box(1),
            )
            .unwrap();
            black_box(plan.plan_hash)
        })
    });
}

criterion_group! {
    name = benches;
    config = Criterion::default().measurement_time(std::time::Duration::from_millis(SGC_COMPILE_100_THRESHOLD_MS));
    targets = bench_sgc_compile_100_systems
}
criterion_main!(benches);
