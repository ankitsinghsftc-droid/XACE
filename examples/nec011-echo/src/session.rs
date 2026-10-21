//! Creator-side interactive benchmark host. Commands apply only at tick boundaries.
//! One bounded checkpoint includes world state, graph, pending events and tick identity.
use std::io::{BufRead,Write};
use std::path::Path;
use serde::Deserialize;
use serde_json::{json,Value};
use xace_nec011_echo::*;
use xace_core::runtime::world_snapshot::WorldSnapshot;
use xace_runtime_core::{component_tables::ComponentTableStore,entity_store::EntityStore,mutation_gate::MutationGate,query_engine::QueryEngine,snapshot_engine::SnapshotEngine};
use xace_runtime_core::cgs_loader::{load_and_spawn_with_plan_policy,SgcPlanPolicy};
use xace_runtime_core::event_bus::event_bus::{EventBus,EventBusRollbackSnapshot};
use xace_runtime_core::phase_orchestrator::{phase_orchestrator::PhaseOrchestrator,system_registry::SystemRegistry};
type Result<T> = std::result::Result<T,String>;
fn checked<T,E:std::fmt::Debug>(value:std::result::Result<T,E>)->Result<T>{value.map_err(|e|format!("{e:?}"))}
#[derive(Deserialize)]
#[serde(tag="action",rename_all="snake_case",deny_unknown_fields)]
enum Command { Tick {tick:u64,pulse:Option<Input>,graph:Option<GraphInput>}, Checkpoint {tick:u64}, Rewind {tick:u64}, Inspect }
pub fn run(cgs:&Path,plan:&Path,input:impl BufRead,mut output:impl Write)->Result<()> {
 let mut es=EntityStore::new();let mut ts=ComponentTableStore::new();
 let summary=checked(load_and_spawn_with_plan_policy(cgs,&mut es,&mut ts,SgcPlanPolicy::RequirePersisted,Some(plan)))?;
 let id=*summary.spawned_actors.iter().find(|a|a.actor_id=="graph").ok_or("graph actor missing")?.entity_ids.first().ok_or("graph entity missing")?;
 let mut reg=SystemRegistry::new();checked(reg.register(Box::new(EchoSystem)))?;
 for (name,access) in &summary.schedule_plan.system_access {let system=reg.get(name).ok_or("unregistered executor")?;if system.declared_reads()!=access.reads || system.declared_writes()!=access.writes{return Err("system access mismatch".into());}}
 let mut mg=MutationGate::new();let mut qe=QueryEngine::new();let mut eb=EventBus::new();
 let mut orch=PhaseOrchestrator::new(42,&summary.schema_version,summary.execution_plan_version);
 let mut se=SnapshotEngine::standard(&summary.schema_version,summary.execution_plan_version,42);
 let mut checkpoint:Option<(u64,WorldSnapshot,EventBusRollbackSnapshot)>=None;
 for line in input.lines() {
  let line=checked(line)?;if line.len()>65536{return Err("command exceeds 64KiB".into());}
  let command:Command=checked(serde_json::from_str(&line))?;
  let result=match command {
   Command::Tick{tick,pulse,graph}=>{
    if tick!=orch.current_tick(){return Err("input tick mismatch".into());}
    let value=json!({"data":{"pulse":pulse,"graph":graph}}).to_string();
    checked(mg.request_modify_component(id,INPUT,value,&es,&ts,tick))?;checked(mg.apply_all(&mut es,&mut ts,tick))?;
    let result=checked(orch.tick(&summary.phase_plan_for_runtime(),&reg,&mut es,&mut ts,&mut mg,&mut qe,&mut eb))?;
    json!({"action":"tick","tick":tick,"world_hash":result.world_hash,"events":result.emitted_events})
   },
   Command::Checkpoint{tick}=>{
    if tick!=orch.current_tick(){return Err("checkpoint tick mismatch".into());}
    checkpoint=Some((tick,checked(se.take_snapshot(tick,&es,&ts))?,eb.rollback_snapshot()));
    json!({"action":"checkpoint","tick":tick,"rewind_horizon_ticks":120})
   },
   Command::Rewind{tick}=>{
    let (saved,snapshot,events)=checkpoint.as_ref().ok_or("no checkpoint")?;
    if tick!=orch.current_tick() || tick<*saved || tick-*saved>120{return Err("rewind tick/horizon".into());}
    checked(se.restore_snapshot(snapshot,&mut es,&mut ts))?;eb.restore_rollback_snapshot(events.clone());orch.restore_tick(*saved);
    json!({"action":"rewind","from_tick":tick,"tick":saved})
   },
   Command::Inspect=>json!({"action":"inspect","tick":orch.current_tick(),"state":checked(serde_json::from_str::<Value>(ts.get_component(id,STATE).ok_or("state missing")?))?})
  };
  checked(writeln!(output,"{}",result))?;checked(output.flush())?;
 }
 Ok(())
}
