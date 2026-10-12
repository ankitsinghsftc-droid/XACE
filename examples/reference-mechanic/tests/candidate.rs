//! Mechanic-specific assertions stay in this removable package.
use serde_json::{json, Value};
use std::{collections::BTreeSet, path::PathBuf};
use xace_core::{
    contracts::interfaces::{ISystem, ISystemContext},
    errors::xace_error::XaceError,
};
use xace_reference_mechanic::{ReferenceSystem, CONFIG_ID, STATE_ID};
use xace_runtime_core::runtime_orchestrator::{
    ruleset_candidate::*, HostSystemRegistrar, RuntimeConfig, RuntimeOrchestrator,
};

struct Recording;
impl ISystem for Recording {
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
        let tick = ctx.current_tick();
        for id in ctx.query_entities(&[STATE_ID])? {
            let mut v: Value = serde_json::from_str(ctx.get_component(id, 6)?.unwrap()).unwrap();
            let moving = v["controller_id"] == 1;
            v["move_x"] = json!(if moving { -1_000_000 } else { 0 });
            v["move_z"] = json!(if moving { 1_000_000 } else { 0 });
            v["jump_pressed"] = json!(moving && [1, 3, 7, 9].contains(&tick));
            ctx.submit_mutation(id, 6, v.to_string())?;
        }
        Ok(())
    }
}
fn setup() -> (
    RuntimeOrchestrator,
    CandidateProposal,
    CandidateStore,
    PathBuf,
) {
    let root = std::env::var_os("XACE_CANDIDATE_FIXTURE_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("fixtures"));
    let config = RuntimeConfig {
        sgc_plan_path: Some(root.join("execution_plan.json")),
        world_path: Some(root.join("world.json")),
        world_manifest_path: Some(root.join("world.manifest.json")),
        register_host_systems: Some(HostSystemRegistrar(|r| {
            r.register(Box::new(ReferenceSystem))
                .map_err(|e| anyhow::anyhow!("{}", e))?;
            r.register(Box::new(Recording))
                .map_err(|e| anyhow::anyhow!("{}", e))?;
            Ok(())
        })),
        ..RuntimeConfig::default()
    };
    let mut live =
        RuntimeOrchestrator::initialise_with_config(&root.join("game.cgs.json"), config).unwrap();
    live.tick().unwrap();
    live.tick().unwrap();
    let proposal = CandidateProposal {
        schema: "xace.ruleset_candidate.v1".into(),
        parent: live.candidate_parent().unwrap(),
        artifacts: CandidateArtifacts::read(&root.join("reversal_shockwave")).unwrap(),
        replace_config_defaults: BTreeSet::from([CONFIG_ID]),
    };
    let dir = std::env::temp_dir().join(format!("xace-xp018-{}", uuid_for_test()));
    (live, proposal, CandidateStore::new(dir.clone()), dir)
}
fn uuid_for_test() -> String {
    use std::sync::atomic::{AtomicU64, Ordering};
    static N: AtomicU64 = AtomicU64::new(0);
    format!(
        "{}-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos(),
        N.fetch_add(1, Ordering::Relaxed)
    )
}
fn policy() -> CandidatePolicy {
    CandidatePolicy {
        configuration_components: BTreeSet::from([CONFIG_ID]),
    }
}
fn observe(runtime: &RuntimeOrchestrator) -> anyhow::Result<Value> {
    let snap = runtime.world_snapshot().unwrap();
    let used = snap.component_tables_snapshot.tables[&STATE_ID]
        .rows
        .values()
        .any(|s| serde_json::from_str::<Value>(s).unwrap()["third_used"] == true);
    anyhow::ensure!(
        used,
        "candidate defaults did not change behavior in preserved state"
    );
    Ok(json!({"reference_third_attempt_executed":true}))
}
#[test]
fn approved_isolated_proof_preserves_live_and_is_digest_addressed() {
    let (live, p, store, dir) = setup();
    let before = live.candidate_parent().unwrap();
    let history = live.hash_log();
    let proof = store
        .stage(
            &live,
            &p,
            &CandidateApproval::approve_reviewed(&p).unwrap(),
            &policy(),
            8,
            observe,
        )
        .unwrap();
    let events = serde_json::to_string(&proof.tick_events).unwrap();
    assert!(events.contains("reference.shockwave.v1"));
    assert!(events.contains("reference.shockwave_hit.v1"));
    if let Some(out) = std::env::var_os("XACE_CANDIDATE_REPORT") {
        std::fs::write(out, serde_json::to_vec_pretty(&proof).unwrap()).unwrap();
    }
    assert_eq!(before, live.candidate_parent().unwrap());
    assert_eq!(history, live.hash_log());
    assert_ne!(proof.before_migration_hash, proof.after_migration_hash);
    assert_eq!(
        proof,
        store
            .read_proof(&p.digest().unwrap(), &proof.digest().unwrap())
            .unwrap()
    );
    assert!(store
        .read_proof(&p.digest().unwrap(), &"0".repeat(64))
        .is_err());
    std::fs::write(dir.join(p.digest().unwrap()).join("game.cgs.json"), b"{}").unwrap();
    assert!(store
        .read_proof(&p.digest().unwrap(), &proof.digest().unwrap())
        .is_err());
}
#[test]
fn defaults_alone_cannot_claim_changed_live_behavior() {
    let (live, mut p, store, _) = setup();
    p.replace_config_defaults.clear();
    assert!(store
        .stage(
            &live,
            &p,
            &CandidateApproval::approve_reviewed(&p).unwrap(),
            &policy(),
            8,
            observe
        )
        .is_err());
    assert_eq!(p.parent, live.candidate_parent().unwrap());
}
#[test]
fn stale_parent_and_changed_approval_fail_closed() {
    let (mut live, mut p, store, _) = setup();
    let approval = CandidateApproval::approve_reviewed(&p).unwrap();
    p.replace_config_defaults.clear();
    assert!(store
        .stage(&live, &p, &approval, &policy(), 8, observe)
        .is_err());
    p.replace_config_defaults.insert(CONFIG_ID);
    live.tick().unwrap();
    let before = live.candidate_parent().unwrap();
    assert!(store
        .stage(&live, &p, &approval, &policy(), 8, observe)
        .is_err());
    assert_eq!(before, live.candidate_parent().unwrap());
}
#[test]
fn state_migration_and_unregistered_configuration_are_denied() {
    let (live, mut p, store, _) = setup();
    assert!(store
        .stage(
            &live,
            &p,
            &CandidateApproval::approve_reviewed(&p).unwrap(),
            &CandidatePolicy {
                configuration_components: BTreeSet::new()
            },
            8,
            observe
        )
        .is_err());
    p.replace_config_defaults.insert(STATE_ID);
    assert!(store
        .stage(
            &live,
            &p,
            &CandidateApproval::approve_reviewed(&p).unwrap(),
            &CandidatePolicy {
                configuration_components: BTreeSet::from([CONFIG_ID, STATE_ID])
            },
            8,
            observe
        )
        .is_err());
    assert_eq!(p.parent, live.candidate_parent().unwrap());
}

#[test]
fn stale_plan_is_rejected_without_touching_live_history() {
    let (live, mut p, store, _) = setup();
    let before = live.candidate_parent().unwrap();
    let history = live.hash_log();
    let root = std::env::var_os("XACE_CANDIDATE_FIXTURE_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("fixtures"));
    let mut artifacts = serde_json::to_value(&p.artifacts).unwrap();
    artifacts["files"]["execution_plan.json"] =
        json!(std::fs::read(root.join("execution_plan.json")).unwrap());
    p.artifacts = serde_json::from_value(artifacts).unwrap();
    let error = store
        .stage(
            &live,
            &p,
            &CandidateApproval::approve_reviewed(&p).unwrap(),
            &policy(),
            8,
            observe,
        )
        .unwrap_err();
    assert!(error.to_string().contains("hash"), "{}", error);
    assert_eq!(before, live.candidate_parent().unwrap());
    assert_eq!(history, live.hash_log());
}

#[test]
fn arbitrary_semantic_world_changes_require_a_migration_hook() {
    let (live, mut p, store, _) = setup();
    let mut artifacts = serde_json::to_value(&p.artifacts).unwrap();
    let bytes: Vec<u8> = serde_json::from_value(artifacts["files"]["world.json"].clone()).unwrap();
    let mut world: Value = serde_json::from_slice(&bytes).unwrap();
    world["day_length_ticks"] = json!(300);
    artifacts["files"]["world.json"] = json!(serde_json::to_vec(&world).unwrap());
    p.artifacts = serde_json::from_value(artifacts).unwrap();
    let error = store
        .stage(
            &live,
            &p,
            &CandidateApproval::approve_reviewed(&p).unwrap(),
            &policy(),
            8,
            observe,
        )
        .unwrap_err();
    assert!(
        error.to_string().contains("world/capability migration"),
        "{}",
        error
    );
    assert_eq!(p.parent, live.candidate_parent().unwrap());
}

#[test]
fn activation_at_n_preserves_the_world_and_changes_only_later_behavior() {
    use xace_runtime_core::runtime_orchestrator::ruleset_activation::{ActivationJournal,RecoveryDisposition};
    let (mut live,p,store,dir)=setup();
    let old_snapshot=live.world_snapshot().unwrap();
    let proof=store.stage(&live,&p,&CandidateApproval::approve_reviewed(&p).unwrap(),&policy(),8,observe).unwrap();
    let journal=dir.join("activation.jsonl");
    let id=live.prepare_ruleset_activation(&store,&p.digest().unwrap(),&proof.digest().unwrap(),8,&journal,&policy()).unwrap();
    assert_eq!(id,live.prepare_ruleset_activation(&store,&p.digest().unwrap(),&proof.digest().unwrap(),8,&journal,&policy()).unwrap());
    let mut emitted=Vec::new();
    for tick in 2..10 {
        let result=live.tick().unwrap();assert_eq!(result.tick,tick);
        let events=serde_json::to_string(&result.emitted_events).unwrap();
        if tick<8 {assert!(!events.contains("reference.shockwave.v1"));}
        if tick==7 {assert!(events.contains("reference.jump_denied.v1"));}
        if tick==9 {assert!(events.contains("reference.shockwave.v1"));}
        emitted.push(events);
    }
    assert_eq!(live.alive_count(),4);
    let before=live.candidate_parent().unwrap();
    assert_eq!(id,live.prepare_ruleset_activation(&store,&p.digest().unwrap(),&proof.digest().unwrap(),8,&journal,&policy()).unwrap());
    assert_eq!(before,live.candidate_parent().unwrap());
    assert!(live.restore_world_snapshot(&old_snapshot).is_err());
    assert_eq!(before,live.candidate_parent().unwrap());
    assert_eq!(ActivationJournal::inspect_recovery(&journal).unwrap(),RecoveryDisposition::EndSession);
}

#[cfg(feature = "activation-fault-injection")]
#[test]
fn activation_failures_preserve_parent_or_end_without_emitting_partial_ticks() {
    use xace_runtime_core::runtime_orchestrator::ruleset_activation::{ActivationFault,ActivationJournal,RecoveryDisposition};
    for fault in [ActivationFault::DuringMigration,ActivationFault::BeforeDecision,ActivationFault::AfterDecision,ActivationFault::BeforeBroadcast] {
        let (mut live,p,store,dir)=setup();
        let proof=store.stage(&live,&p,&CandidateApproval::approve_reviewed(&p).unwrap(),&policy(),8,observe).unwrap();
        let journal=dir.join("fault.jsonl");
        live.prepare_ruleset_activation(&store,&p.digest().unwrap(),&proof.digest().unwrap(),8,&journal,&policy()).unwrap();
        for _ in 2..8 {live.tick().unwrap();}
        let before=live.candidate_parent().unwrap();let history=live.hash_log();
        live.inject_activation_fault(fault);
        if matches!(fault,ActivationFault::DuringMigration|ActivationFault::BeforeDecision) {
            assert_eq!(live.tick().unwrap().tick,8);
            assert_eq!(live.candidate_parent().unwrap().cgs_hash,before.cgs_hash);
            assert_eq!(ActivationJournal::inspect_recovery(&journal).unwrap(),RecoveryDisposition::ParentUnchanged);
            assert!(!serde_json::to_string(&live.tick().unwrap().emitted_events).unwrap().contains("reference.shockwave.v1"));
        } else {
            assert!(live.tick().is_err());assert!(live.tick().is_err());
            assert_eq!(history,live.hash_log());
            assert_eq!(live.candidate_parent().unwrap().tick,8);
            assert_eq!(ActivationJournal::inspect_recovery(&journal).unwrap(),RecoveryDisposition::EndSession);
            if fault==ActivationFault::AfterDecision {assert_eq!(before,live.candidate_parent().unwrap());}
            else {assert_ne!(before.cgs_hash,live.candidate_parent().unwrap().cgs_hash);}
        }
    }
}
