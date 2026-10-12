//! Immutable offline replay across explicitly recorded ruleset epochs.
//! No sockets, engine side effects, current-project fallbacks or gameplay names.
use super::ruleset_candidate::{migrate_isolated, CandidateArtifacts, CandidateProposal};
use super::*;
use anyhow::Context;
use serde::{Deserialize, Serialize};
use std::{fs, io::Write};
use xace_core::wire::feedback_payload::FeedbackMessage;

fn digest<T: Serialize>(value: &T) -> Result<String> {
    Ok(format!("{:x}", Sha256::digest(serde_json::to_vec(value)?)))
}
fn executable_digest() -> Result<String> {
    Ok(format!(
        "{:x}",
        Sha256::digest(fs::read(std::env::current_exe()?)?)
    ))
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReplayEpoch {
    pub tick: u64,
    pub activation_id: String,
    pub proposal: CandidateProposal,
    pub journal: Vec<u8>,
    pub migrated_snapshot_hash: String,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReplayTick {
    pub tick: u64,
    pub epoch: u64,
    pub inputs: Vec<InputPacket>,
    pub feedback: Vec<FeedbackMessage>,
    pub required_peers: BTreeSet<u64>,
    pub release_decision: String,
    pub missing_peers: Vec<u64>,
    pub waited_ticks: u64,
    pub world_hash: String,
    pub state: Value,
    pub events: Value,
    pub schedule: cgs_loader::RuntimeScheduleSnapshot,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReplayBundle {
    pub schema: String,
    pub host_executable_digest: String,
    pub world_seed: u64,
    pub apply_engine_inputs: bool,
    pub initial_artifacts: CandidateArtifacts,
    pub initial_snapshot: WorldSnapshot,
    pub epochs: Vec<ReplayEpoch>,
    pub ticks: Vec<ReplayTick>,
    #[serde(skip)]
    pub(super) pending_feedback: Vec<FeedbackMessage>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SealedReplay {
    pub schema: String,
    pub digest: String,
    pub bundle: ReplayBundle,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReplayReport {
    pub schema: String,
    pub ok: bool,
    pub verified_ticks: u64,
    pub epochs: usize,
    pub first_divergence: Option<Value>,
    pub presentation_effects_emitted: u64,
}
fn state(runtime: &RuntimeOrchestrator) -> Result<Value> {
    let s = runtime
        .world_snapshot()
        .map_err(|e| anyhow::anyhow!("{}", e))?;
    Ok(json!({"entities":s.entity_store_snapshot,"components":s.component_tables_snapshot}))
}
impl RuntimeOrchestrator {
    pub fn start_epoch_recording(&mut self, artifact_directory: &Path) -> Result<()> {
        anyhow::ensure!(
            self.epoch_recording.is_none() && self.phase_orch.current_tick() == 0,
            "recording must start before tick zero"
        );
        let artifacts = CandidateArtifacts::read(artifact_directory)?;
        // Bind captured bytes to the artifacts actually loaded by this runtime.
        let cgs: Value =
            serde_json::from_slice(&fs::read(artifact_directory.join("game.cgs.json"))?)?;
        anyhow::ensure!(
            cgs["metadata"]["cgs_hash"] == self.spawn_summary.cgs_hash,
            "recording artifacts do not match runtime"
        );
        self.epoch_recording = Some(ReplayBundle {
            schema: "xace.epoch_replay.v1".into(),
            host_executable_digest: executable_digest()?,
            world_seed: self.config.world_seed,
            apply_engine_inputs: self.config.apply_engine_input_components,
            initial_artifacts: artifacts,
            initial_snapshot: self
                .world_snapshot()
                .map_err(|e| anyhow::anyhow!("{}", e))?,
            epochs: Vec::new(),
            ticks: Vec::new(),
            pending_feedback: Vec::new(),
        });
        Ok(())
    }
    pub fn sealed_epoch_recording(&self) -> Result<SealedReplay> {
        let bundle = self
            .epoch_recording
            .as_ref()
            .ok_or_else(|| anyhow::anyhow!("epoch recording is not enabled"))?
            .clone();
        anyhow::ensure!(!bundle.ticks.is_empty(), "cannot seal empty replay");
        Ok(SealedReplay {
            schema: "xace.sealed_epoch_replay.v1".into(),
            digest: digest(&bundle)?,
            bundle,
        })
    }
    pub fn save_epoch_recording(&self, path: &Path) -> Result<()> {
        let bytes = serde_json::to_vec(&self.sealed_epoch_recording()?)?;
        anyhow::ensure!(
            bytes.len() <= 512 * 1024 * 1024,
            "replay exceeds supported bundle size"
        );
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(path)?;
        file.write_all(&bytes)?;
        file.sync_all()?;
        Ok(())
    }
    pub(super) fn capture_replay_initial_boundary(&mut self) -> Result<()> {
        if self
            .epoch_recording
            .as_ref()
            .is_some_and(|r| r.ticks.is_empty())
        {
            let snapshot = self
                .world_snapshot()
                .map_err(|e| anyhow::anyhow!("{}", e))?;
            self.epoch_recording.as_mut().unwrap().initial_snapshot = snapshot;
        }
        Ok(())
    }
    pub(super) fn record_replay_activation(
        &mut self,
        id: &str,
        proposal: &CandidateProposal,
        journal: &Path,
    ) -> Result<()> {
        if self.epoch_recording.is_none() {
            return Ok(());
        }
        let snapshot = self
            .world_snapshot()
            .map_err(|e| anyhow::anyhow!("{}", e))?;
        self.epoch_recording
            .as_mut()
            .unwrap()
            .epochs
            .push(ReplayEpoch {
                tick: snapshot.tick,
                activation_id: id.into(),
                proposal: proposal.clone(),
                journal: fs::read(journal)?,
                migrated_snapshot_hash: snapshot.world_hash,
            });
        Ok(())
    }
    pub(super) fn record_epoch_replay_tick(
        &mut self,
        result: &TickResult,
        applications: &[RuntimeEngineInputApplication],
        schedule: &cgs_loader::RuntimeScheduleSnapshot,
    ) -> Result<()> {
        if self.epoch_recording.is_none() {
            return Ok(());
        }
        let state = state(self)?;
        let recording = self.epoch_recording.as_mut().unwrap();
        anyhow::ensure!(recording.ticks.len() < 100_000, "replay tick limit reached");
        recording.ticks.push(ReplayTick {
            tick: result.tick,
            epoch: recording.epochs.len() as u64,
            inputs: applications
                .iter()
                .filter(|a| a.applied)
                .map(|a| a.packet.clone())
                .collect(),
            feedback: std::mem::take(&mut recording.pending_feedback),
            required_peers: self.config.input_sync.required_peers.clone(),
            release_decision: self.input_sync_last_trace.decision.clone(),
            missing_peers: self.input_sync_last_trace.missing_peers.clone(),
            waited_ticks: self.input_sync_last_trace.waited_ticks,
            world_hash: result.world_hash.clone(),
            state,
            events: serde_json::to_value(&result.emitted_events)?,
            schedule: schedule.clone(),
        });
        Ok(())
    }
}
impl SealedReplay {
    pub fn seal(bundle: ReplayBundle) -> Result<Self> {
        Ok(Self {
            schema: "xace.sealed_epoch_replay.v1".into(),
            digest: digest(&bundle)?,
            bundle,
        })
    }
    pub fn read(path: &Path) -> Result<Self> {
        anyhow::ensure!(
            fs::metadata(path)?.len() <= 512 * 1024 * 1024,
            "replay too large"
        );
        let sealed: Self = serde_json::from_slice(&fs::read(path)?)?;
        sealed.validate()?;
        Ok(sealed)
    }
    fn validate(&self) -> Result<()> {
        anyhow::ensure!(
            self.schema == "xace.sealed_epoch_replay.v1"
                && self.bundle.schema == "xace.epoch_replay.v1"
                && self.digest == digest(&self.bundle)?,
            "replay schema or digest mismatch"
        );
        anyhow::ensure!(
            self.bundle.host_executable_digest == executable_digest()?,
            "historical host executable is missing or incompatible"
        );
        anyhow::ensure!(
            !self.bundle.ticks.is_empty() && self.bundle.ticks.len() <= 100_000,
            "empty or oversized replay"
        );
        for (i, tick) in self.bundle.ticks.iter().enumerate() {
            anyhow::ensure!(
                tick.tick == self.bundle.initial_snapshot.tick + i as u64,
                "incomplete replay tick sequence"
            );
        }
        anyhow::ensure!(
            self.bundle.epochs.windows(2).all(|e| e[0].tick < e[1].tick),
            "unordered epoch sequence"
        );
        let last = self.bundle.ticks.last().unwrap().tick;
        anyhow::ensure!(
            self.bundle
                .epochs
                .iter()
                .all(|e| e.tick > self.bundle.initial_snapshot.tick && e.tick <= last),
            "epoch outside recorded tick range"
        );
        Ok(())
    }
    /// Each call constructs a new offline fork. Seeking backwards never rewinds
    /// a live authority, and no presentation command is sent to an engine.
    pub fn verify(
        &self,
        scratch: &Path,
        registrar: Option<HostSystemRegistrar>,
        configuration_components: &BTreeSet<u32>,
        through_tick: Option<u64>,
    ) -> Result<ReplayReport> {
        self.validate()?;
        if let Some(end) = through_tick {
            anyhow::ensure!(
                end >= self.bundle.initial_snapshot.tick
                    && end <= self.bundle.ticks.last().unwrap().tick,
                "requested tick is outside complete recording"
            );
        }
        fs::create_dir(scratch)?;
        let first = scratch.join("initial");
        self.bundle.initial_artifacts.materialize(&first)?;
        let config = RuntimeConfig {
            register_host_systems: registrar,
            world_seed: self.bundle.world_seed,
            apply_engine_input_components: self.bundle.apply_engine_inputs,
            sgc_plan_path: Some(first.join("execution_plan.json")),
            world_path: Some(first.join("world.json")),
            world_manifest_path: Some(first.join("world.manifest.json")),
            ..RuntimeConfig::default()
        };
        let mut runtime =
            RuntimeOrchestrator::initialise_with_config(&first.join("game.cgs.json"), config)?;
        anyhow::ensure!(
            runtime.spawn_summary.cgs_hash == self.bundle.initial_snapshot.cgs_hash,
            "initial historical CGS mismatch"
        );
        runtime
            .restore_world_snapshot(&self.bundle.initial_snapshot)
            .map_err(|e| anyhow::anyhow!("{}", e))?;
        let mut report = ReplayReport {
            schema: "xace.epoch_replay_report.v1".into(),
            ok: true,
            verified_ticks: 0,
            epochs: 0,
            first_divergence: None,
            presentation_effects_emitted: 0,
        };
        for expected in &self.bundle.ticks {
            if through_tick.is_some_and(|end| expected.tick > end) {
                break;
            }
            if let Some(epoch) = self.bundle.epochs.iter().find(|e| e.tick == expected.tick) {
                anyhow::ensure!(
                    epoch
                        .proposal
                        .replace_config_defaults
                        .is_subset(configuration_components),
                    "historical migration is not registered by host"
                );
                let folder = scratch.join(format!("epoch-{}", epoch.tick));
                epoch.proposal.artifacts.materialize(&folder)?;
                let journal = folder.join("activation.jsonl");
                fs::write(&journal, &epoch.journal)?;
                anyhow::ensure!(
                    ruleset_activation::ActivationJournal::inspect_recovery(&journal)?
                        == ruleset_activation::RecoveryDisposition::EndSession,
                    "historical activation lacks durable decision"
                );
                let rows = epoch
                    .journal
                    .split(|b| *b == b'\n')
                    .filter(|l| !l.is_empty())
                    .map(serde_json::from_slice::<Value>)
                    .collect::<std::result::Result<Vec<_>, _>>()?;
                let request: ruleset_activation::ActivationRequest = serde_json::from_value(
                    rows.first().context("empty activation evidence")?["record"]["prepared"]
                        ["request"]
                        .clone(),
                )?;
                anyhow::ensure!(
                    request.digest()? == epoch.activation_id
                        && request.candidate_digest == epoch.proposal.digest()?
                        && request.activation_tick == epoch.tick,
                    "activation evidence does not bind historical candidate"
                );
                let checkpoint = rows
                    .iter()
                    .find_map(|row| row["record"].get("decided"))
                    .context("missing activation checkpoint")?;
                let recorded: WorldSnapshot =
                    serde_json::from_value(checkpoint["checkpoint"].clone())?;
                let current = runtime
                    .world_snapshot()
                    .map_err(|e| anyhow::anyhow!("{}", e))?;
                anyhow::ensure!(
                    recorded.world_hash == current.world_hash,
                    "activation parent snapshot diverged at tick {}",
                    epoch.tick
                );
                let publication = rows
                    .iter()
                    .find_map(|row| row["record"].get("published"))
                    .context("activation was not published")?;
                anyhow::ensure!(
                    publication["tick"] == epoch.tick
                        && publication["world_hash"] == epoch.migrated_snapshot_hash,
                    "activation publication mismatch"
                );
                let (migrated, _, _) = migrate_isolated(&runtime, &epoch.proposal, &folder)?;
                anyhow::ensure!(
                    migrated
                        .world_snapshot()
                        .map_err(|e| anyhow::anyhow!("{}", e))?
                        .world_hash
                        == epoch.migrated_snapshot_hash,
                    "historical migration diverged at tick {}",
                    epoch.tick
                );
                runtime = migrated;
                runtime.config.apply_engine_input_components = self.bundle.apply_engine_inputs;
                report.epochs += 1;
            }
            anyhow::ensure!(
                expected.epoch == report.epochs as u64,
                "missing historical epoch at tick {}",
                expected.tick
            );
            runtime.engine_inputs.extend(expected.inputs.clone());
            for feedback in &expected.feedback {
                runtime
                    .feedback_buffer
                    .append(feedback.clone())
                    .map_err(|e| anyhow::anyhow!("{:?}", e))?;
            }
            let actual = runtime
                .tick()
                .map_err(|e| anyhow::anyhow!("replay tick {}: {}", expected.tick, e))?;
            let actual_state = state(&runtime)?;
            let actual_events = serde_json::to_value(&actual.emitted_events)?;
            let actual_schedule = runtime
                .last_schedule_snapshot()
                .context("replay schedule missing")?;
            if actual.world_hash != expected.world_hash
                || actual_state != expected.state
                || actual_events != expected.events
                || *actual_schedule != expected.schedule
            {
                report.ok = false;
                report.first_divergence = Some(
                    json!({"tick":expected.tick,"epoch":expected.epoch,"expected_hash":expected.world_hash,"actual_hash":actual.world_hash,"state_matches":actual_state==expected.state,"events_match":actual_events==expected.events,"schedule_matches":*actual_schedule==expected.schedule,"inputs":expected.inputs,"systems":actual_schedule.scheduled_system_ids}),
                );
                break;
            }
            report.verified_ticks += 1;
        }
        Ok(report)
    }
}
