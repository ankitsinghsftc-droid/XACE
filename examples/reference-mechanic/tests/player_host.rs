use std::path::Path;
use xace_runtime_core::runtime_orchestrator::{RuntimeConfig, RuntimeOrchestrator, HostSystemRegistrar};
use xace_core::contracts::interfaces::{ISystem, ISystemContext};
use xace_core::errors::xace_error::XaceError;

fn config() -> RuntimeConfig {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("fixtures/player");
    RuntimeConfig {
        sgc_plan_path: Some(root.join("execution_plan.json")),
        world_path: Some(root.join("world.json")),
        world_manifest_path: Some(root.join("world.manifest.json")),
        ..RuntimeConfig::default()
    }
}
fn path() -> std::path::PathBuf { Path::new(env!("CARGO_MANIFEST_DIR")).join("fixtures/player/game.cgs.json") }
#[test]
fn stock_host_rejects_unregistered_package_system() {
    assert!(RuntimeOrchestrator::initialise_with_config(&path(), config()).is_err());
}
#[test]
fn ordinary_host_registration_executes_and_restores_package_world() {
    let mut cfg = config();
    cfg.register_host_systems = Some(HostSystemRegistrar(|registry| {
        registry.register(Box::new(xace_reference_mechanic::ReferenceSystem)).map_err(|e| anyhow::anyhow!("{:?}",e))
    }));
    let mut runtime = RuntimeOrchestrator::initialise_with_config(&path(), cfg).unwrap();
    let snapshot = runtime.world_snapshot().unwrap();
    let expected = runtime.tick().unwrap().world_hash;
    runtime.restore_world_snapshot(&snapshot).unwrap();
    assert_eq!(runtime.tick().unwrap().world_hash, expected);
}
struct WrongAccess;
impl ISystem for WrongAccess {
    fn system_id(&self) -> &str { xace_reference_mechanic::SYSTEM_ID }
    fn declared_reads(&self) -> &[u32] { &[] }
    fn declared_writes(&self) -> &[u32] { &[] }
    fn execute(&self, _: &mut dyn ISystemContext) -> Result<(), XaceError> { Ok(()) }
}
#[test]
fn host_access_must_match_compiled_plan_before_tick_zero() {
    let mut cfg=config();
    cfg.register_host_systems=Some(HostSystemRegistrar(|registry| registry.register(Box::new(WrongAccess)).map_err(|e|anyhow::anyhow!("{:?}",e))));
    let error=RuntimeOrchestrator::initialise_with_config(&path(),cfg).err().unwrap().to_string();
    assert!(error.contains("access contract differs"),"{}",error);
}
