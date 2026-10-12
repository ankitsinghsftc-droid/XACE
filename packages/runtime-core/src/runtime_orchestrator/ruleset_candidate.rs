//! Isolated ruleset preparation. This module intentionally has no activation API.
//! Host-owned approval and configuration declarations are not package capabilities.
use super::*;
use serde::{Deserialize, Serialize};
use std::fs;
use std::io::Write;

const FILES: [&str; 4] = [
    "game.cgs.json",
    "execution_plan.json",
    "world.json",
    "world.manifest.json",
];
const PACKAGE_FILES: [&str; 2] = ["compiled_schema.json", "playable.manifest.json"];
fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn identity<T: Serialize>(value: &T) -> Result<String> {
    Ok(hash(&serde_json::to_vec(value)?))
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CandidateParent {
    pub schema: String,
    pub session: Value,
    pub cgs_hash: String,
    pub plan_hash: String,
    pub world_digest: String,
    pub tick: u64,
    pub snapshot_hash: String,
}

/// Exact immutable input bytes. Copying paths later cannot change an approved proposal.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CandidateArtifacts {
    files: BTreeMap<String, Vec<u8>>,
}
impl CandidateArtifacts {
    pub fn read(directory: &Path) -> Result<Self> {
        let mut files = BTreeMap::new();
        for name in FILES.into_iter().chain(PACKAGE_FILES.into_iter().filter(|name|directory.join(name).exists())) {
            anyhow::ensure!(
                fs::metadata(directory.join(name))?.len() <= 16 * 1024 * 1024,
                "candidate artifact too large"
            );
            files.insert(name.into(), fs::read(directory.join(name))?);
        }
        Ok(Self { files })
    }
    pub fn digest(&self) -> Result<String> {
        identity(self)
    }
    pub(super) fn materialize(&self, directory: &Path) -> Result<()> {
        anyhow::ensure!(
            FILES.iter().all(|name|self.files.contains_key(*name))
                && self.files.keys().all(|name|FILES.contains(&name.as_str()) || PACKAGE_FILES.contains(&name.as_str()))
                && (self.files.contains_key(PACKAGE_FILES[0]) == self.files.contains_key(PACKAGE_FILES[1])),
            "invalid artifact set"
        );
        fs::create_dir_all(directory)?;
        for (name, bytes) in &self.files {
            anyhow::ensure!(
                bytes.len() <= 16 * 1024 * 1024,
                "candidate artifact too large"
            );
            let path = directory.join(name);
            if path.exists() {
                anyhow::ensure!(fs::read(path)? == *bytes, "immutable artifact changed");
            } else {
                let mut f = fs::OpenOptions::new()
                    .write(true)
                    .create_new(true)
                    .open(path)?;
                f.write_all(bytes)?;
                f.sync_all()?;
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CandidateProposal {
    pub schema: String,
    pub parent: CandidateParent,
    pub artifacts: CandidateArtifacts,
    /// All other component rows are preserved from the captured runtime snapshot.
    pub replace_config_defaults: BTreeSet<u32>,
}
impl CandidateProposal {
    pub fn digest(&self) -> Result<String> {
        identity(self)
    }
}

/// Construct only at the trusted host's explicit approval boundary, never deserialize
/// approval from provider/package payloads. Bound to the full reviewed proposal.
pub struct CandidateApproval {
    digest: String,
}
impl CandidateApproval {
    pub fn approve_reviewed(proposal: &CandidateProposal) -> Result<Self> {
        Ok(Self {
            digest: proposal.digest()?,
        })
    }
}

/// A host registration declares configuration tables which gameplay systems cannot
/// write. A proposal cannot enroll new tables or executable migration hooks.
pub struct CandidatePolicy {
    pub configuration_components: BTreeSet<u32>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CandidateProof {
    pub schema: String,
    pub proposal_digest: String,
    pub parent: CandidateParent,
    pub artifact_digest: String,
    pub compatibility: String,
    pub changed_artifacts: BTreeSet<String>,
    pub replaced_configuration: BTreeSet<u32>,
    pub before_migration_hash: String,
    pub after_migration_hash: String,
    pub tick_hashes: Vec<String>,
    pub tick_events: Vec<Value>,
    pub observations: Value,
    pub world_and_capabilities_unchanged: bool,
    pub host_executable_digest: String,
}
impl CandidateProof {
    /// Keep this identity with the trusted preparation decision. Reading a stored
    /// proof requires it, so a modified result cannot certify itself.
    pub fn digest(&self) -> Result<String> {
        identity(self)
    }
}

/// No mutable runtime is retained or returned. The only durable output is a
/// digest-addressed record and exact artifacts for XP-019 to revalidate later.
pub struct CandidateStore {
    root: PathBuf,
}
impl CandidateStore {
    pub(super) fn verified_candidate(&self, digest:&str, expected_proof_digest:&str)->Result<(CandidateProposal,CandidateProof,PathBuf)> {
        let proof=self.read_proof(digest,expected_proof_digest)?;
        let directory=self.root.join(digest);
        let proposal=serde_json::from_slice(&std::fs::read(directory.join("proposal.json"))?)?;
        Ok((proposal,proof,directory))
    }
    pub fn new(root: PathBuf) -> Self {
        Self { root }
    }
    pub fn read_proof(&self, digest: &str, expected_proof_digest: &str) -> Result<CandidateProof> {
        anyhow::ensure!(
            digest.len() == 64 && digest.bytes().all(|b| b.is_ascii_hexdigit()),
            "invalid candidate digest"
        );
        let directory = self.root.join(digest);
        let proposal: CandidateProposal =
            serde_json::from_slice(&fs::read(directory.join("proposal.json"))?)?;
        anyhow::ensure!(proposal.digest()? == digest, "candidate proposal changed");
        let artifacts = CandidateArtifacts::read(&directory)?;
        anyhow::ensure!(
            artifacts.digest()? == proposal.artifacts.digest()?,
            "candidate artifact changed"
        );
        let proof: CandidateProof =
            serde_json::from_slice(&fs::read(directory.join("proof.json"))?)?;
        anyhow::ensure!(
            proof.digest()? == expected_proof_digest,
            "stored proof changed"
        );
        anyhow::ensure!(
            proof.proposal_digest == digest
                && proof.parent == proposal.parent
                && proof.artifact_digest == artifacts.digest()?,
            "candidate proof identity mismatch"
        );
        Ok(proof)
    }

    pub fn stage<F>(
        &self,
        live: &RuntimeOrchestrator,
        proposal: &CandidateProposal,
        approval: &CandidateApproval,
        policy: &CandidatePolicy,
        ticks: usize,
        observe: F,
    ) -> Result<CandidateProof>
    where
        F: Fn(&RuntimeOrchestrator) -> Result<Value>,
    {
        anyhow::ensure!(
            proposal.schema == "xace.ruleset_candidate.v1",
            "unsupported candidate schema"
        );
        anyhow::ensure!(
            approval.digest == proposal.digest()?,
            "proposal was not approved or changed after approval"
        );
        anyhow::ensure!(
            live.candidate_parent()? == proposal.parent,
            "stale candidate parent"
        );
        anyhow::ensure!(
            (1..=600).contains(&ticks),
            "isolated proof requires 1..600 ticks"
        );
        anyhow::ensure!(
            !proposal.replace_config_defaults.is_empty(),
            "changed defaults require an explicit configuration migration mapping"
        );
        anyhow::ensure!(
            proposal
                .replace_config_defaults
                .is_subset(&policy.configuration_components),
            "configuration mapping is not host registered"
        );
        let digest = proposal.digest()?;
        let directory = self.root.join(&digest);
        // Failed candidates remain unproved; no proof record is published on failure.
        proposal.artifacts.materialize(&directory)?;
        let config = isolated_config(live, &directory);
        let loaded = load_hot_swap_candidate(
            &directory.join("game.cgs.json"),
            config.clone(),
            input_ingress::PendingInput::default(),
        )?;
        let compatibility = live.classify_hot_swap_candidate(&loaded);
        anyhow::ensure!(
            compatibility.overall_class == RuntimeHotSwapCompatibilityClass::Additive
                && compatibility.issues.is_empty(),
            "unsupported migration: {}",
            compatibility.issue_summary()
        );
        for id in &proposal.replace_config_defaults {
            anyhow::ensure!(
                !live
                    .schedule_plan
                    .system_access
                    .values()
                    .chain(loaded.schedule_plan.system_access.values())
                    .any(|s| s.writes.contains(id)),
                "configuration mapping targets system-written state"
            );
        }
        // v1 supports unchanged geometry/semantic world only; other changes require
        // an explicit proven world migration hook, never an implicit reset.
        let active_world = live
            .config
            .world_path
            .as_ref()
            .ok_or_else(|| anyhow::anyhow!("compiled parent world required"))?;
        let before_world: Value = serde_json::from_slice(&fs::read(active_world)?)?;
        let after_world: Value = serde_json::from_slice(&proposal.artifacts.files["world.json"])?;
        anyhow::ensure!(
            before_world == after_world,
            "world/capability migration requires a proven hook"
        );
        let mut changed_artifacts = BTreeSet::new();
        if loaded.summary.cgs_hash != live.spawn_summary.cgs_hash {
            changed_artifacts.insert("game.cgs.json".into());
        }
        if loaded.summary.execution_plan_hash != live.spawn_summary.execution_plan_hash {
            changed_artifacts.insert("execution_plan.json".into());
        }
        if fs::read(
            live.config
                .world_manifest_path
                .as_ref()
                .ok_or_else(|| anyhow::anyhow!("parent world manifest required"))?,
        )? != proposal.artifacts.files["world.manifest.json"]
        {
            changed_artifacts.insert("world.manifest.json".into());
        }
        let mut runs = Vec::new();
        for _ in 0..2 {
            let (mut isolated, before, after) = migrate_isolated(live, proposal, &directory)?;
            let mut hashes = Vec::new();
            let mut events = Vec::new();
            for _ in 0..ticks {
                let result = isolated.tick().map_err(|e| anyhow::anyhow!("{}", e))?;
                hashes.push(result.world_hash);
                events.push(json!({"tick":result.tick,"events":result.emitted_events}));
            }
            runs.push((before, after, hashes, events, observe(&isolated)?));
        }
        anyhow::ensure!(runs[0] == runs[1], "isolated proof is nondeterministic");
        anyhow::ensure!(
            live.candidate_parent()? == proposal.parent,
            "parent changed during proof"
        );
        let (before, after, hashes, events, observations) = runs.remove(0);
        let proof = CandidateProof {
            schema: "xace.ruleset_candidate_proof.v1".into(),
            proposal_digest: digest,
            parent: proposal.parent.clone(),
            artifact_digest: proposal.artifacts.digest()?,
            compatibility: compatibility.overall_class.as_str().into(),
            changed_artifacts,
            replaced_configuration: proposal.replace_config_defaults.clone(),
            before_migration_hash: before,
            after_migration_hash: after,
            tick_hashes: hashes,
            tick_events: events,
            observations,
            world_and_capabilities_unchanged: true,
            host_executable_digest: hash(&fs::read(std::env::current_exe()?)?),
        };
        write_once(
            &directory.join("proposal.json"),
            &serde_json::to_vec(proposal)?,
        )?;
        write_once(&directory.join("proof.json"), &serde_json::to_vec(&proof)?)?;
        Ok(proof)
    }
}
fn write_once(path: &Path, bytes: &[u8]) -> Result<()> {
    if path.exists() {
        anyhow::ensure!(
            fs::read(path)? == bytes,
            "immutable candidate record changed"
        );
        return Ok(());
    }
    let mut file = fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}
fn isolated_config(live: &RuntimeOrchestrator, directory: &Path) -> RuntimeConfig {
    RuntimeConfig {
        register_host_systems: live.config.register_host_systems,
        world_seed: live.config.world_seed,
        sgc_plan_path: Some(directory.join("execution_plan.json")),
        world_path: Some(directory.join("world.json")),
        world_manifest_path: Some(directory.join("world.manifest.json")),
        ..RuntimeConfig::default()
    }
}
impl RuntimeOrchestrator {
    pub fn candidate_parent(&self) -> Result<CandidateParent> {
        let snapshot = self
            .world_snapshot()
            .map_err(|e| anyhow::anyhow!("{}", e))?;
        Ok(CandidateParent {
            schema: "xace.candidate_parent.v1".into(),
            session: self
                .live_session_controller
                .as_ref()
                .map(|s| s.candidate_identity())
                .unwrap_or(Value::Null),
            cgs_hash: self.spawn_summary.cgs_hash.clone(),
            plan_hash: self.spawn_summary.execution_plan_hash.clone(),
            world_digest: hash(&fs::read(
                self.config
                    .world_path
                    .as_ref()
                    .ok_or_else(|| anyhow::anyhow!("compiled world required"))?,
            )?),
            tick: snapshot.tick,
            snapshot_hash: snapshot.world_hash,
        })
    }
}

pub(super) fn migrate_isolated(live: &RuntimeOrchestrator, proposal: &CandidateProposal, directory: &Path) -> Result<(RuntimeOrchestrator, String, String)> {
    let config = isolated_config(live, directory);
    let original = live.world_snapshot().map_err(|e| anyhow::anyhow!("{}", e))?;
let mut isolated = RuntimeOrchestrator::initialise_with_config(
    &directory.join("game.cgs.json"),
    config.clone(),
)?;
let defaults = isolated
    .world_snapshot()
    .map_err(|e| anyhow::anyhow!("{}", e))?;
anyhow::ensure!(
    original.entity_store_snapshot == defaults.entity_store_snapshot,
    "entity migration requires a proven hook"
);
let mut transferred = original.clone();
transferred.cgs_hash = defaults.cgs_hash.clone();
transferred.schema_version = defaults.schema_version.clone();
transferred.execution_plan_version = defaults.execution_plan_version;
transferred.world_hash = WorldHasher::compute(&transferred);
isolated
    .restore_world_snapshot(&transferred)
    .map_err(|e| anyhow::anyhow!("{}", e))?;
let before = isolated
    .world_snapshot()
    .map_err(|e| anyhow::anyhow!("{}", e))?
    .world_hash;
for id in &proposal.replace_config_defaults {
    let table = defaults
        .component_tables_snapshot
        .tables
        .get(id)
        .ok_or_else(|| anyhow::anyhow!("missing candidate configuration"))?;
    let prior = original
        .component_tables_snapshot
        .tables
        .get(id)
        .ok_or_else(|| anyhow::anyhow!("missing parent configuration"))?;
    anyhow::ensure!(
        table.rows.keys().eq(prior.rows.keys()),
        "configuration topology changed"
    );
    for (entity, value) in &table.rows {
        isolated
            .mutation_gate
            .request_modify_component(
                *entity,
                *id,
                value.clone(),
                &isolated.entity_store,
                &isolated.table_store,
                original.tick,
            )
            .map_err(|e| anyhow::anyhow!("{}", e))?;
    }
}
isolated
    .mutation_gate
    .apply_all(
        &mut isolated.entity_store,
        &mut isolated.table_store,
        original.tick,
    )
    .map_err(|e| anyhow::anyhow!("{}", e))?;
let after = isolated
    .world_snapshot()
    .map_err(|e| anyhow::anyhow!("{}", e))?
    .world_hash;
anyhow::ensure!(
    before != after,
    "configuration migration changed no runtime state"
);
Ok((isolated, before, after))
}
