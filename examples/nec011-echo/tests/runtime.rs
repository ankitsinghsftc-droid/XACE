use serde_json::{json,Value};
use std::path::Path;
use xace_nec011_echo::*;
use xace_runtime_core::{component_tables::ComponentTableStore,entity_store::EntityStore,mutation_gate::MutationGate,query_engine::QueryEngine,snapshot_engine::SnapshotEngine};
use xace_runtime_core::cgs_loader::{load_and_spawn_with_plan_policy,SgcPlanPolicy,SpawnSummary};
use xace_runtime_core::event_bus::event_bus::EventBus;
use xace_runtime_core::phase_orchestrator::{phase_orchestrator::{PhaseOrchestrator,TickResult},system_registry::SystemRegistry};
struct Host {es:EntityStore,ts:ComponentTableStore,mg:MutationGate,qe:QueryEngine,eb:EventBus,orch:PhaseOrchestrator,reg:SystemRegistry,summary:SpawnSummary,id:u64}
impl Host {
fn new()->Self {let root=Path::new(env!("CARGO_MANIFEST_DIR")).join("fixtures");let mut es=EntityStore::new();let mut ts=ComponentTableStore::new();let summary=load_and_spawn_with_plan_policy(&root.join("game.cgs.json"),&mut es,&mut ts,SgcPlanPolicy::RequirePersisted,Some(&root.join("execution_plan.json"))).unwrap();let id=summary.spawned_actors.iter().find(|a|a.actor_id=="graph").unwrap().entity_ids[0];let mut reg=SystemRegistry::new();reg.register(Box::new(EchoSystem)).unwrap();for (id,access) in &summary.schedule_plan.system_access {let system=reg.get(id).unwrap();assert_eq!(system.declared_reads(),access.reads);assert_eq!(system.declared_writes(),access.writes);}
Self{es,ts,mg:MutationGate::new(),qe:QueryEngine::new(),eb:EventBus::new(),orch:PhaseOrchestrator::new(42,&summary.schema_version,summary.execution_plan_version),reg,summary,id}}
fn tick(&mut self)->Result<TickResult,xace_core::errors::xace_error::XaceError>{self.orch.tick(&self.summary.phase_plan_for_runtime(),&self.reg,&mut self.es,&mut self.ts,&mut self.mg,&mut self.qe,&mut self.eb)}
fn state(&self)->Value {serde_json::from_str(self.ts.get_component(self.id,STATE).unwrap()).unwrap()}
fn set(&mut self,kind:u32,value:Value){self.mg.request_modify_component(self.id,kind,value.to_string(),&self.es,&self.ts,self.orch.current_tick()).unwrap();self.mg.apply_all(&mut self.es,&mut self.ts,self.orch.current_tick()).unwrap();}
}
#[test] fn real_sgc_execution_snapshot_rewind_and_replay_match_every_hash_and_event(){
let mut h=Host::new();let first=h.tick().unwrap();assert_eq!(first.emitted_events.len(),1);assert_eq!(h.state()["data"]["pending"][0]["due"],2);
let mut se=SnapshotEngine::standard(&h.summary.schema_version,h.summary.execution_plan_version,42);let tick=h.orch.current_tick();let snapshot=se.take_snapshot(tick,&h.es,&h.ts).unwrap();let events=h.eb.rollback_snapshot();let mut expected=Vec::new();
for _ in 0..6 {let r=h.tick().unwrap();expected.push((r.world_hash,serde_json::to_value(r.emitted_events).unwrap()));}
assert_eq!(h.state()["data"]["energy"]["3"],-1_000_000);let final_state=h.state();se.restore_snapshot(&snapshot,&mut h.es,&mut h.ts).unwrap();h.eb.restore_rollback_snapshot(events);h.orch.restore_tick(tick);
for e in &expected {let r=h.tick().unwrap();assert_eq!(&(r.world_hash,serde_json::to_value(r.emitted_events).unwrap()),e);}
assert_eq!(h.state(),final_state);println!("NEC011_ECHO_REPLAY={}",serde_json::to_string(&expected).unwrap());}
#[test] fn conflicting_duplicate_input_halts_without_publishing_state(){let mut h=Host::new();h.tick().unwrap();let before=h.state();h.set(INPUT,json!({"data":{"pulse":{"tick":0,"id":1,"node":1,"amplitude":2_000_000}}}));assert!(h.tick().is_err());assert_eq!(h.state(),before);}
