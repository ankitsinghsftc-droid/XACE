//! XP-018 real session-controller isolation proof; no engine or activation command.
use std::{collections::BTreeSet, path::PathBuf};
use serde_json::{json,Value};
use xace_runtime_core::runtime_orchestrator::{RuntimeConfig,RuntimeInputSyncConfig,RuntimeOrchestrator,HostSystemRegistrar,ruleset_candidate::*};
use xace_reference_mechanic::{ReferenceSystem,CONFIG_ID};
fn main()->anyhow::Result<()> {
    let root=PathBuf::from(std::env::args().nth(1).expect("proof root"));
    let parent=root.join("parent");let candidate=root.join("candidate");
    let config=RuntimeConfig {sgc_plan_path:Some(parent.join("execution_plan.json")),world_path:Some(parent.join("world.json")),world_manifest_path:Some(parent.join("world.manifest.json")),live_session:true,session_manifest_path:Some(parent.join("playable.manifest.json")),session_ticket_path:Some(root.join("ticket.json")),session_log_path:Some(root.join("session.jsonl")),input_sync:RuntimeInputSyncConfig::lockstep([1]),register_host_systems:Some(HostSystemRegistrar(|r|r.register(Box::new(ReferenceSystem)).map_err(|e|anyhow::anyhow!("{}",e)))),..RuntimeConfig::default()};
    let live=RuntimeOrchestrator::initialise_with_config(&parent.join("game.cgs.json"),config)?;
    let before=live.candidate_parent()?;anyhow::ensure!(!before.session.is_null(),"live session identity missing");
    let journal=std::fs::read(root.join("session.jsonl"))?;let snapshot=serde_json::to_vec(&live.world_snapshot().map_err(|e|anyhow::anyhow!("{}",e))?)?;
    let proposal=CandidateProposal {schema:"xace.ruleset_candidate.v1".into(),parent:before.clone(),artifacts:CandidateArtifacts::read(&candidate)?,replace_config_defaults:BTreeSet::from([CONFIG_ID])};
    let proof=CandidateStore::new(root.join("store")).stage(&live,&proposal,&CandidateApproval::approve_reviewed(&proposal)?,&CandidatePolicy{configuration_components:BTreeSet::from([CONFIG_ID])},2,|runtime| {
        let snap=runtime.world_snapshot().map_err(|e|anyhow::anyhow!("{}",e))?;
        for row in snap.component_tables_snapshot.tables[&CONFIG_ID].rows.values() {
            anyhow::ensure!(serde_json::from_str::<Value>(row)?["third_attempt"]=="reversal_shockwave","configuration mapping not applied");
        }
        Ok(json!({"configuration_applied_in_isolation":true}))
    })?;
    anyhow::ensure!(live.candidate_parent()?==before,"active parent changed");
    anyhow::ensure!(std::fs::read(root.join("session.jsonl"))?==journal,"active journal changed");
    anyhow::ensure!(serde_json::to_vec(&live.world_snapshot().map_err(|e|anyhow::anyhow!("{}",e))?)?==snapshot,"active snapshot changed");
    std::fs::write(root.join("live-proof.json"),serde_json::to_vec_pretty(&json!({"schema":"xace.xp018.live_isolation.v1","ok":true,"active_snapshot_unchanged":true,"active_journal_unchanged":true,"proof":proof}))?)?;
    Ok(())
}
