//! Runtime orchestrator for the standalone bridge runtime.

use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};

use anyhow::Result;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use xace_core::errors::determinism_error::GuardMode;
use xace_core::errors::xace_error::XaceError;
use xace_core::runtime::state_delta::{ComponentChange, StateDelta};
use xace_engine_feedback::feedback_buffer::FeedbackBuffer;
use xace_engine_feedback::feedback_log::FeedbackLog;
use xace_engine_feedback::feedback_router::{FeedbackRouter, RouteBatchReport};
use xace_engine_feedback::feedback_validator::FeedbackValidator;

use crate::component_tables::component_table::ComponentTable;
use crate::component_tables::component_table_store::ComponentTableStore;
use crate::determinism_guard::determinism_guard::DeterminismGuard;
use crate::determinism_guard::rng_interceptor::{RngAccessRecord, RngInterceptor};
use crate::determinism_guard::world_hasher::WorldHasher;
use crate::determinism_guard::GoldenLog;
use crate::engine_bridge::{
    build_entity_states, EngineBridge, EngineBridgeConfig, EngineBridgeStats,
};
use crate::engine_protocol::{EnginePlaybackCommand, TickSnapshot};
use crate::entity_store::entity_store::EntityStore;
use crate::event_bus::event_bus::EventBus;
use crate::mutation_gate::mutation_gate::MutationGate;
use crate::phase_orchestrator::parallel_executor::ParallelGroupExecutionPolicy;
use crate::phase_orchestrator::phase_orchestrator::{PhaseOrchestrator, TickResult};
use crate::phase_orchestrator::system_registry::SystemRegistry;
use crate::query_engine::QueryEngine;
use crate::snapshot_engine::{validate_restorable_snapshot, SnapshotEngine};
use crate::state_printer::{print_state, PrinterOpts};
use crate::{builtin_systems, cgs_loader, tcp_server};
use xace_core::events::event_struct::Event;
use xace_core::runtime::world_snapshot::WorldSnapshot;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeConfig {
    pub world_seed: u64,
    pub execution_plan_version: u32,
    pub sgc_plan_policy: cgs_loader::SgcPlanPolicy,
    pub sgc_plan_path: Option<PathBuf>,
    pub determinism_guard_mode: GuardMode,
    pub bridge: EngineBridgeConfig,
    pub apply_engine_input_components: bool,
}

impl Default for RuntimeConfig {
    fn default() -> Self {
        Self {
            world_seed: 42,
            execution_plan_version: 1,
            sgc_plan_policy: cgs_loader::SgcPlanPolicy::RequirePersisted,
            sgc_plan_path: None,
            determinism_guard_mode: GuardMode::Strict,
            bridge: EngineBridgeConfig::default(),
            apply_engine_input_components: true,
        }
    }
}

impl RuntimeConfig {
    pub fn development_with_cgs_derived_plan() -> Self {
        Self {
            sgc_plan_policy: cgs_loader::SgcPlanPolicy::DeriveFromCgs,
            ..Self::default()
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeStatus {
    pub tick: u64,
    pub alive_count: usize,
    pub engine_connected: bool,
    pub adapter_type: String,
    pub engine_connections: Vec<RuntimeEngineConnectionStatus>,
    pub engine_snapshots_sent: u64,
    pub engine_input_packets_received: u64,
    pub engine_feedback_payloads_received: u64,
    pub engine_feedback_messages_received: u64,
    pub engine_malformed_messages: u64,
    pub engine_dropped_inputs: u64,
    pub pending_engine_inputs: usize,
    pub pending_engine_feedback: usize,
    pub registered_systems: usize,
    pub phase_count: usize,
    pub last_engine_feedback_processed: usize,
    pub last_engine_feedback_invalid: usize,
    pub last_engine_feedback_errors: usize,
    pub latest_world_hash: String,
    pub cgs_hash: String,
    pub schema_version: String,
    pub execution_plan_version: String,
    pub parallel_group_execution_policy: String,
    pub parallel_group_worker_threads: bool,
    pub hash_log: Vec<RuntimeHashRecord>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeHashRecord {
    pub tick: u64,
    pub world_hash: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeHotSwapReport {
    pub schema: String,
    pub previous_cgs_hash: String,
    pub new_cgs_hash: String,
    pub previous_schema_version: String,
    pub new_schema_version: String,
    pub previous_execution_plan_version: u32,
    pub new_execution_plan_version: u32,
    pub previous_plan_hash: String,
    pub new_plan_hash: String,
    pub requested_tick: u64,
    pub applied_tick: u64,
    pub safe_tick_boundary: bool,
    pub preserved_entity_ids: Vec<u64>,
    pub preserved_component_rows: usize,
    pub added_component_tables: Vec<u32>,
    pub previous_system_ids: Vec<String>,
    pub new_system_ids: Vec<String>,
    pub newly_active_system_ids: Vec<String>,
    pub compatibility: RuntimeHotSwapCompatibilityReport,
    pub migration: Option<RuntimeHotSwapMigrationReport>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RuntimeComponentMigrationOperation {
    BackfillFromCandidateDefaults,
}

impl RuntimeComponentMigrationOperation {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::BackfillFromCandidateDefaults => "backfill_from_candidate_defaults",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeComponentMigrationHook {
    pub hook_id: String,
    pub from_schema_version: String,
    pub to_schema_version: String,
    pub component_type_id: u32,
    pub operation: RuntimeComponentMigrationOperation,
}

impl RuntimeComponentMigrationHook {
    pub fn backfill_from_candidate_defaults(
        hook_id: impl Into<String>,
        from_schema_version: impl Into<String>,
        to_schema_version: impl Into<String>,
        component_type_id: u32,
    ) -> Self {
        Self {
            hook_id: hook_id.into(),
            from_schema_version: from_schema_version.into(),
            to_schema_version: to_schema_version.into(),
            component_type_id,
            operation: RuntimeComponentMigrationOperation::BackfillFromCandidateDefaults,
        }
    }

    fn supports_issue(
        &self,
        from_schema_version: &str,
        to_schema_version: &str,
        issue: &RuntimeHotSwapCompatibilityIssue,
    ) -> bool {
        self.from_schema_version == from_schema_version
            && self.to_schema_version == to_schema_version
            && issue.component_type_id == Some(self.component_type_id)
            && matches!(
                (self.operation, issue.code.as_str()),
                (
                    RuntimeComponentMigrationOperation::BackfillFromCandidateDefaults,
                    "component_added_requires_backfill"
                )
            )
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeComponentMigrationRecord {
    pub hook_id: String,
    pub operation: String,
    pub component_type_id: u32,
    pub entity_ids: Vec<u64>,
    pub rows_written: usize,
    pub old_component_hash: String,
    pub new_component_hash: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeHotSwapMigrationReport {
    pub schema: String,
    pub from_schema_version: String,
    pub to_schema_version: String,
    pub requested_tick: u64,
    pub old_world_hash: String,
    pub migrated_world_hash: String,
    pub records: Vec<RuntimeComponentMigrationRecord>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum RuntimeHotSwapCompatibilityClass {
    Additive,
    Migratable,
    StateTransforming,
    ResetRequired,
}

impl RuntimeHotSwapCompatibilityClass {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Additive => "additive",
            Self::Migratable => "migratable",
            Self::StateTransforming => "state_transforming",
            Self::ResetRequired => "reset_required",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeHotSwapCompatibilityIssue {
    pub class: RuntimeHotSwapCompatibilityClass,
    pub code: String,
    pub message: String,
    pub component_type_id: Option<u32>,
    pub system_id: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeHotSwapCompatibilityReport {
    pub schema: String,
    pub overall_class: RuntimeHotSwapCompatibilityClass,
    pub live_compatible: bool,
    pub migration_required: bool,
    pub reset_required: bool,
    pub added_component_tables: Vec<u32>,
    pub backfill_component_tables: Vec<u32>,
    pub removed_component_tables: Vec<u32>,
    pub added_system_ids: Vec<String>,
    pub removed_system_ids: Vec<String>,
    pub changed_system_ids: Vec<String>,
    pub previous_system_ids: Vec<String>,
    pub new_system_ids: Vec<String>,
    pub issues: Vec<RuntimeHotSwapCompatibilityIssue>,
}

impl RuntimeHotSwapCompatibilityReport {
    pub fn issue_summary(&self) -> String {
        if self.issues.is_empty() {
            return "no compatibility issues".to_string();
        }
        self.issues
            .iter()
            .map(|issue| format!("{}:{}:{}", issue.class.as_str(), issue.code, issue.message))
            .collect::<Vec<_>>()
            .join("; ")
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeReplayValidation {
    pub passed: bool,
    pub compared_ticks: usize,
    pub first_mismatch: Option<RuntimeReplayMismatch>,
    pub schedule_snapshots_compared: usize,
    pub first_schedule_mismatch: Option<RuntimeScheduleReplayMismatch>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeReplayMismatch {
    pub tick: u64,
    pub expected_hash: String,
    pub actual_hash: String,
    pub diagnosis: RuntimeReplayDivergenceDiagnosis,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeReplayDivergenceDiagnosis {
    pub tick: u64,
    pub summary: String,
    pub suspected_sgc_group: Option<RuntimeReplayGroupTrace>,
    pub candidate_systems: Vec<String>,
    pub component_changes: Vec<RuntimeReplayComponentTrace>,
    pub emitted_events: Vec<RuntimeReplayEventTrace>,
    pub rng_calls: Vec<RuntimeReplayRngCallTrace>,
    pub mutation: RuntimeReplayMutationTrace,
    pub input_packets: Vec<RuntimeReplayInputPacketTrace>,
    pub expected_trace: Option<RuntimeTickReplayTrace>,
    pub actual_trace: Option<RuntimeTickReplayTrace>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeTickReplayTrace {
    pub tick: u64,
    pub world_hash: String,
    pub sgc_groups: Vec<RuntimeReplayGroupTrace>,
    pub candidate_systems: Vec<String>,
    pub component_access: BTreeMap<String, cgs_loader::RuntimeComponentAccess>,
    pub component_changes: Vec<RuntimeReplayComponentTrace>,
    pub emitted_events: Vec<RuntimeReplayEventTrace>,
    pub rng_calls: Vec<RuntimeReplayRngCallTrace>,
    pub mutation: RuntimeReplayMutationTrace,
    pub input_packets: Vec<RuntimeReplayInputPacketTrace>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeReplayGroupTrace {
    pub group_id: String,
    pub phase: String,
    pub execution_index: u32,
    pub parallel: bool,
    pub systems: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeReplayComponentTrace {
    pub operation: String,
    pub entity_id: u64,
    pub component_type_id: u32,
    pub component_type_name: String,
    pub field_names: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeReplayEventTrace {
    pub event_id: u64,
    pub event_type: String,
    pub creation_tick: u64,
    pub creation_phase: String,
    pub source_entity_id: u64,
    pub target_entity_id: u64,
    pub payload_keys: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeReplayRngCallTrace {
    pub system_id: String,
    pub tick: u64,
    pub deterministic: bool,
    pub seed: Option<u64>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct RuntimeReplayMutationTrace {
    pub mutations_applied: usize,
    pub state_changes: usize,
    pub spawned_entities: usize,
    pub destroyed_entities: usize,
    pub added_components: usize,
    pub removed_components: usize,
    pub updated_components: usize,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeReplayInputPacketTrace {
    pub peer_id: u64,
    pub tick: u64,
    pub sequence_id: u64,
    pub player_id: Option<u64>,
    pub device_id: String,
    pub action_count: usize,
    pub action_names: Vec<String>,
    pub digest: String,
    pub applied: bool,
    pub status: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeScheduleReplayMismatch {
    pub tick: u64,
    pub expected: cgs_loader::RuntimeScheduleSnapshot,
    pub actual: Option<cgs_loader::RuntimeScheduleSnapshot>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeEngineConnectionStatus {
    pub adapter_type: String,
    pub connected: bool,
    pub snapshots_sent: u64,
    pub input_packets_received: u64,
    pub feedback_payloads_received: u64,
    pub feedback_messages_received: u64,
    pub malformed_messages: u64,
    pub dropped_inputs: u64,
    pub queued_inputs: usize,
    pub queued_feedback: usize,
}

pub struct RuntimeOrchestrator {
    config: RuntimeConfig,
    phase_orch: PhaseOrchestrator,
    determinism_guard: DeterminismGuard,
    rng_interceptor: RngInterceptor,
    registry: SystemRegistry,
    entity_store: EntityStore,
    table_store: ComponentTableStore,
    mutation_gate: MutationGate,
    query_engine: QueryEngine,
    event_bus: EventBus,
    spawn_summary: cgs_loader::SpawnSummary,
    phase_plan: cgs_loader::RuntimePhasePlan,
    schedule_plan: cgs_loader::RuntimeSchedulePlan,
    schedule_identity: cgs_loader::RuntimeScheduleIdentity,
    schedule_snapshots: Vec<cgs_loader::RuntimeScheduleSnapshot>,
    replay_traces: BTreeMap<u64, RuntimeTickReplayTrace>,
    bridges: Vec<EngineBridge>,
    engine_inputs: Vec<xace_network_core::input::InputPacket>,
    feedback_buffer: FeedbackBuffer,
    feedback_validator: FeedbackValidator,
    feedback_router: FeedbackRouter,
    feedback_log: FeedbackLog,
    last_tick_result: Option<RuntimeTickSummary>,
    last_playback_commands: Vec<EnginePlaybackCommand>,
    replay_golden_log: Option<GoldenLog>,
    migration_hooks: Vec<RuntimeComponentMigrationHook>,
    migration_log: Vec<RuntimeHotSwapMigrationReport>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeTickSummary {
    pub tick: u64,
    pub mutations_applied: usize,
    pub events_dispatched: usize,
    pub engine_inputs_applied: usize,
    pub engine_feedback_processed: usize,
    pub engine_feedback_invalid: usize,
    pub engine_feedback_errors: usize,
    pub state_changes: usize,
    pub spawned_ids: Vec<u64>,
    pub destroyed_ids: Vec<u64>,
    pub world_hash: String,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
struct RuntimeFeedbackDrainReport {
    handled: usize,
    invalid: usize,
    errors: usize,
}

impl RuntimeFeedbackDrainReport {
    fn from_route_report(report: RouteBatchReport, invalid: usize, errors: usize) -> Self {
        Self {
            handled: report.handled,
            invalid: invalid.saturating_add(report.parse_failures),
            errors: errors.saturating_add(report.handler_errors),
        }
    }
}

#[derive(Debug, Clone)]
struct RuntimeEngineInputApplication {
    packet: xace_network_core::input::InputPacket,
    applied: bool,
    status: String,
}

impl RuntimeOrchestrator {
    pub fn initialise(cgs_path: &Path) -> Result<Self> {
        Self::initialise_with_config(cgs_path, RuntimeConfig::default())
    }

    pub fn initialise_with_config(cgs_path: &Path, mut config: RuntimeConfig) -> Result<Self> {
        let mut entity_store = EntityStore::new();
        let mut table_store = ComponentTableStore::new();
        let mutation_gate = MutationGate::new();
        let query_engine = QueryEngine::new();
        let event_bus = EventBus::new();
        let feedback_buffer = FeedbackBuffer::new();

        let spawn_summary = cgs_loader::load_and_spawn_with_plan_policy(
            cgs_path,
            &mut entity_store,
            &mut table_store,
            config.sgc_plan_policy,
            config.sgc_plan_path.as_deref(),
        )?;
        config.execution_plan_version = spawn_summary.execution_plan_version;
        let phase_plan = spawn_summary.phase_plan.clone();
        let schedule_plan = spawn_summary.schedule_plan.clone();
        let schedule_identity = schedule_plan.identity();
        let mut registry = builtin_systems::build_default_registry()?;
        register_runtime_executor_systems(&mut registry, &spawn_summary.runtime_systems)?;
        validate_phase_plan(&phase_plan, &registry)?;
        let determinism_guard = build_determinism_guard(
            config.determinism_guard_mode,
            &spawn_summary.schema_version,
            config.execution_plan_version,
            &phase_plan,
        );
        let rng_interceptor = RngInterceptor::new(config.world_seed, config.determinism_guard_mode);

        let phase_orch = PhaseOrchestrator::new(
            config.world_seed,
            spawn_summary.schema_version.clone(),
            config.execution_plan_version,
        );
        let feedback_log_schema_version = spawn_summary.schema_version.clone();
        let feedback_log_execution_plan_version = config.execution_plan_version;

        Ok(Self {
            config,
            phase_orch,
            determinism_guard,
            rng_interceptor,
            registry,
            entity_store,
            table_store,
            mutation_gate,
            query_engine,
            event_bus,
            spawn_summary,
            phase_plan,
            schedule_plan,
            schedule_identity,
            schedule_snapshots: Vec::new(),
            replay_traces: BTreeMap::new(),
            bridges: Vec::new(),
            engine_inputs: Vec::new(),
            feedback_buffer,
            feedback_validator: FeedbackValidator::with_defaults(),
            feedback_router: FeedbackRouter::with_default_handlers(),
            feedback_log: FeedbackLog::new(
                feedback_log_schema_version,
                feedback_log_execution_plan_version,
            ),
            last_tick_result: None,
            last_playback_commands: Vec::new(),
            replay_golden_log: None,
            migration_hooks: Vec::new(),
            migration_log: Vec::new(),
        })
    }

    pub fn connect_engine(&mut self, port: u16) -> Result<()> {
        self.connect_engines(port, 1)
    }

    pub fn connect_engines(&mut self, port: u16, expected_connections: usize) -> Result<()> {
        let connections = tcp_server::wait_for_connections(port, expected_connections)?;
        self.handshake_engine_connections(connections)?;
        Ok(())
    }

    pub fn try_connect_engine(&mut self, port: u16, timeout_secs: u64) -> Result<bool> {
        Ok(self.try_connect_engines(port, 1, timeout_secs)? > 0)
    }

    pub fn try_connect_engines(
        &mut self,
        port: u16,
        expected_connections: usize,
        timeout_secs: u64,
    ) -> Result<usize> {
        let connections =
            tcp_server::try_connect_connections(port, expected_connections, timeout_secs)?;
        let connected = connections.len();
        self.handshake_engine_connections(connections)?;
        Ok(connected)
    }

    pub fn accept_engine_connection(
        &mut self,
        connection: tcp_server::EngineConnection,
    ) -> Result<()> {
        self.handshake_engine_connections(vec![connection])
    }

    pub fn tick(&mut self) -> Result<TickResult, XaceError> {
        self.pump_engine_inbound();
        self.collect_engine_inputs_from_bridge();
        let feedback_report = self.process_engine_feedback_at_tick_start();
        let input_applications = if self.config.apply_engine_input_components {
            self.apply_pending_engine_inputs()?
        } else {
            Vec::new()
        };
        let applied_inputs = input_applications
            .iter()
            .filter(|application| application.applied)
            .count();
        let schedule_snapshot = self
            .schedule_plan
            .snapshot_for_tick(self.phase_orch.current_tick());
        self.validate_schedule_snapshot_for_tick(&schedule_snapshot)?;
        let phase_plan = schedule_snapshot.phase_plan_for_runtime();

        let result = self.phase_orch.tick_with_guard(
            &phase_plan,
            &self.registry,
            &mut self.entity_store,
            &mut self.table_store,
            &mut self.mutation_gate,
            &mut self.query_engine,
            &mut self.event_bus,
            &mut self.determinism_guard,
            &self.rng_interceptor,
            &self.spawn_summary.cgs_hash,
        )?;

        let spawned_ids = result
            .state_delta
            .spawned_entities
            .iter()
            .map(|entity| entity.entity_id)
            .collect::<Vec<_>>();
        let destroyed_ids = result
            .state_delta
            .destroyed_entities
            .iter()
            .map(|entity| entity.entity_id)
            .collect::<Vec<_>>();
        let playback_commands = self.playback_commands_for_events(&result.emitted_events);
        let replay_trace =
            self.build_replay_trace(&result, &schedule_snapshot, &input_applications);
        self.send_tick_to_engine(&result, &playback_commands);
        self.last_tick_result = Some(RuntimeTickSummary {
            tick: result.tick,
            mutations_applied: result.mutations_applied,
            events_dispatched: result.events_dispatched,
            engine_inputs_applied: applied_inputs,
            engine_feedback_processed: feedback_report.handled,
            engine_feedback_invalid: feedback_report.invalid,
            engine_feedback_errors: feedback_report.errors,
            state_changes: result.state_delta.change_count(),
            spawned_ids,
            destroyed_ids,
            world_hash: result.world_hash.clone(),
        });
        self.last_playback_commands = playback_commands;
        self.replay_traces.insert(result.tick, replay_trace);
        self.schedule_snapshots.push(schedule_snapshot);
        Ok(result)
    }

    fn validate_schedule_snapshot_for_tick(
        &self,
        snapshot: &cgs_loader::RuntimeScheduleSnapshot,
    ) -> Result<(), XaceError> {
        self.schedule_identity
            .validate_snapshot(snapshot)
            .map_err(|reason| XaceError::FatalError {
                message: format!(
                    "Runtime schedule identity drift before tick {}: {}",
                    snapshot.tick, reason
                ),
                context: xace_core::errors::xace_error::ErrorContext::new(
                    "RuntimeOrchestrator",
                    "validate_schedule_snapshot_for_tick",
                )
                .with_tick(snapshot.tick),
                snapshot_recovery_possible: true,
            })
    }

    fn build_replay_trace(
        &self,
        result: &TickResult,
        schedule_snapshot: &cgs_loader::RuntimeScheduleSnapshot,
        input_applications: &[RuntimeEngineInputApplication],
    ) -> RuntimeTickReplayTrace {
        RuntimeTickReplayTrace {
            tick: result.tick,
            world_hash: result.world_hash.clone(),
            sgc_groups: schedule_snapshot
                .groups
                .iter()
                .map(Self::group_trace)
                .collect(),
            candidate_systems: schedule_snapshot.scheduled_system_ids.clone(),
            component_access: schedule_snapshot.system_access.clone(),
            component_changes: self.component_traces(&result.state_delta),
            emitted_events: result
                .emitted_events
                .iter()
                .map(Self::event_trace)
                .collect(),
            rng_calls: self
                .rng_interceptor
                .accesses_for_tick(result.tick)
                .iter()
                .map(Self::rng_call_trace)
                .collect(),
            mutation: Self::mutation_trace(&result.state_delta, result.mutations_applied),
            input_packets: input_applications
                .iter()
                .map(Self::input_packet_trace)
                .collect(),
        }
    }

    fn diagnose_replay_mismatch(
        &self,
        tick: u64,
        expected_hash: &str,
        actual_hash: &str,
        actual_trace: Option<RuntimeTickReplayTrace>,
    ) -> RuntimeReplayDivergenceDiagnosis {
        let expected_trace = self.replay_trace_at_tick(tick).cloned();
        let candidate_systems =
            Self::diagnosis_candidate_systems(expected_trace.as_ref(), actual_trace.as_ref());
        let component_changes =
            Self::diagnosis_component_changes(expected_trace.as_ref(), actual_trace.as_ref());
        let emitted_events = Self::diagnosis_events(expected_trace.as_ref(), actual_trace.as_ref());
        let rng_calls = Self::diagnosis_rng_calls(expected_trace.as_ref(), actual_trace.as_ref());
        let mutation = Self::diagnosis_mutation(expected_trace.as_ref(), actual_trace.as_ref());
        let input_packets =
            Self::diagnosis_input_packets(expected_trace.as_ref(), actual_trace.as_ref());
        let suspected_sgc_group = Self::suspected_sgc_group(
            expected_trace.as_ref(),
            actual_trace.as_ref(),
            &candidate_systems,
            &component_changes,
            &rng_calls,
        );
        let summary = Self::diagnosis_summary(
            tick,
            expected_hash,
            actual_hash,
            suspected_sgc_group.as_ref(),
            &candidate_systems,
            &component_changes,
            &emitted_events,
            &rng_calls,
            &mutation,
            &input_packets,
        );

        RuntimeReplayDivergenceDiagnosis {
            tick,
            summary,
            suspected_sgc_group,
            candidate_systems,
            component_changes,
            emitted_events,
            rng_calls,
            mutation,
            input_packets,
            expected_trace,
            actual_trace,
        }
    }

    fn group_trace(group: &cgs_loader::RuntimeScheduleGroup) -> RuntimeReplayGroupTrace {
        RuntimeReplayGroupTrace {
            group_id: group.group_id.clone(),
            phase: group.phase.clone(),
            execution_index: group.execution_index,
            parallel: group.parallel,
            systems: group.systems.clone(),
        }
    }

    fn component_traces(&self, delta: &StateDelta) -> Vec<RuntimeReplayComponentTrace> {
        let mut traces = Vec::new();
        for spawned in &delta.spawned_entities {
            for (component_type_id, component_json) in &spawned.initial_components {
                traces.push(RuntimeReplayComponentTrace {
                    operation: "spawn_component".to_string(),
                    entity_id: spawned.entity_id,
                    component_type_id: *component_type_id,
                    component_type_name: self.component_type_name(*component_type_id),
                    field_names: json_field_names(component_json),
                });
            }
        }
        for added in &delta.added_components {
            traces.push(RuntimeReplayComponentTrace {
                operation: "add_component".to_string(),
                entity_id: added.entity_id,
                component_type_id: added.component_type_id,
                component_type_name: added.component_type_name.clone(),
                field_names: json_field_names(&added.component_json),
            });
        }
        for (entity_id, components) in &delta.updated_components {
            for (component_type_id, change) in components {
                traces.push(RuntimeReplayComponentTrace {
                    operation: "update_component".to_string(),
                    entity_id: *entity_id,
                    component_type_id: *component_type_id,
                    component_type_name: self.component_type_name(*component_type_id),
                    field_names: component_update_field_names(change),
                });
            }
        }
        for removed in &delta.removed_components {
            traces.push(RuntimeReplayComponentTrace {
                operation: "remove_component".to_string(),
                entity_id: removed.entity_id,
                component_type_id: removed.component_type_id,
                component_type_name: removed.component_type_name.clone(),
                field_names: Vec::new(),
            });
        }
        for destroyed in &delta.destroyed_entities {
            traces.push(RuntimeReplayComponentTrace {
                operation: "destroy_entity".to_string(),
                entity_id: destroyed.entity_id,
                component_type_id: 0,
                component_type_name: "ENTITY".to_string(),
                field_names: Vec::new(),
            });
        }
        traces
    }

    fn component_type_name(&self, component_type_id: u32) -> String {
        self.table_store
            .get_table(component_type_id)
            .map(|table| table.component_type_name().to_string())
            .unwrap_or_else(|| format!("component_type_{}", component_type_id))
    }

    fn event_trace(event: &Event) -> RuntimeReplayEventTrace {
        RuntimeReplayEventTrace {
            event_id: event.event_id,
            event_type: format!("{:?}", event.event_type),
            creation_tick: event.creation_tick,
            creation_phase: format!("{:?}", event.creation_phase),
            source_entity_id: event.source_entity_id,
            target_entity_id: event.target_entity_id,
            payload_keys: event.payload.keys().cloned().collect(),
        }
    }

    fn rng_call_trace(record: &RngAccessRecord) -> RuntimeReplayRngCallTrace {
        RuntimeReplayRngCallTrace {
            system_id: record.system_id.clone(),
            tick: record.tick,
            deterministic: record.is_deterministic,
            seed: record.seed,
        }
    }

    fn mutation_trace(delta: &StateDelta, mutations_applied: usize) -> RuntimeReplayMutationTrace {
        RuntimeReplayMutationTrace {
            mutations_applied,
            state_changes: delta.change_count(),
            spawned_entities: delta.spawned_entities.len(),
            destroyed_entities: delta.destroyed_entities.len(),
            added_components: delta.added_components.len(),
            removed_components: delta.removed_components.len(),
            updated_components: delta
                .updated_components
                .values()
                .map(|components| components.len())
                .sum(),
        }
    }

    fn input_packet_trace(
        application: &RuntimeEngineInputApplication,
    ) -> RuntimeReplayInputPacketTrace {
        RuntimeReplayInputPacketTrace {
            peer_id: application.packet.peer_id,
            tick: application.packet.tick,
            sequence_id: application.packet.sequence_id,
            player_id: application.packet.player_id,
            device_id: application.packet.device_id.clone(),
            action_count: application.packet.actions.len(),
            action_names: application
                .packet
                .actions
                .iter()
                .map(|action| action.action.clone())
                .collect(),
            digest: application.packet.deterministic_digest(),
            applied: application.applied,
            status: application.status.clone(),
        }
    }

    fn diagnosis_candidate_systems(
        expected: Option<&RuntimeTickReplayTrace>,
        actual: Option<&RuntimeTickReplayTrace>,
    ) -> Vec<String> {
        let mut systems = BTreeSet::new();
        for trace in [expected, actual].into_iter().flatten() {
            systems.extend(trace.candidate_systems.iter().cloned());
            for group in &trace.sgc_groups {
                systems.extend(group.systems.iter().cloned());
            }
        }
        systems.into_iter().collect()
    }

    fn diagnosis_component_changes(
        expected: Option<&RuntimeTickReplayTrace>,
        actual: Option<&RuntimeTickReplayTrace>,
    ) -> Vec<RuntimeReplayComponentTrace> {
        Self::merge_trace_field(
            expected.map(|trace| trace.component_changes.as_slice()),
            actual.map(|trace| trace.component_changes.as_slice()),
        )
    }

    fn diagnosis_events(
        expected: Option<&RuntimeTickReplayTrace>,
        actual: Option<&RuntimeTickReplayTrace>,
    ) -> Vec<RuntimeReplayEventTrace> {
        Self::merge_trace_field(
            expected.map(|trace| trace.emitted_events.as_slice()),
            actual.map(|trace| trace.emitted_events.as_slice()),
        )
    }

    fn diagnosis_rng_calls(
        expected: Option<&RuntimeTickReplayTrace>,
        actual: Option<&RuntimeTickReplayTrace>,
    ) -> Vec<RuntimeReplayRngCallTrace> {
        Self::merge_trace_field(
            expected.map(|trace| trace.rng_calls.as_slice()),
            actual.map(|trace| trace.rng_calls.as_slice()),
        )
    }

    fn diagnosis_input_packets(
        expected: Option<&RuntimeTickReplayTrace>,
        actual: Option<&RuntimeTickReplayTrace>,
    ) -> Vec<RuntimeReplayInputPacketTrace> {
        Self::merge_trace_field(
            expected.map(|trace| trace.input_packets.as_slice()),
            actual.map(|trace| trace.input_packets.as_slice()),
        )
    }

    fn diagnosis_mutation(
        expected: Option<&RuntimeTickReplayTrace>,
        actual: Option<&RuntimeTickReplayTrace>,
    ) -> RuntimeReplayMutationTrace {
        match (expected, actual) {
            (Some(expected), Some(actual)) if expected.mutation != actual.mutation => {
                actual.mutation.clone()
            }
            (Some(expected), _) => expected.mutation.clone(),
            (_, Some(actual)) => actual.mutation.clone(),
            _ => RuntimeReplayMutationTrace::default(),
        }
    }

    fn merge_trace_field<T: Clone + PartialEq>(
        expected: Option<&[T]>,
        actual: Option<&[T]>,
    ) -> Vec<T> {
        match (expected, actual) {
            (Some(expected), Some(actual)) if expected == actual => expected.to_vec(),
            (Some(expected), Some(actual)) => merge_distinct(expected, actual),
            (Some(expected), None) => expected.to_vec(),
            (None, Some(actual)) => actual.to_vec(),
            (None, None) => Vec::new(),
        }
    }

    fn suspected_sgc_group(
        expected: Option<&RuntimeTickReplayTrace>,
        actual: Option<&RuntimeTickReplayTrace>,
        candidate_systems: &[String],
        component_changes: &[RuntimeReplayComponentTrace],
        rng_calls: &[RuntimeReplayRngCallTrace],
    ) -> Option<RuntimeReplayGroupTrace> {
        let component_ids = component_changes
            .iter()
            .map(|component| component.component_type_id)
            .collect::<BTreeSet<_>>();
        for trace in [actual, expected].into_iter().flatten() {
            for group in &trace.sgc_groups {
                if group.systems.iter().any(|system| {
                    trace
                        .component_access
                        .get(system)
                        .map(|access| {
                            access
                                .writes
                                .iter()
                                .any(|component_id| component_ids.contains(component_id))
                        })
                        .unwrap_or(false)
                }) {
                    return Some(group.clone());
                }
            }
        }
        for rng_call in rng_calls {
            if let Some(group) =
                Self::first_group_containing_system(expected, actual, &rng_call.system_id)
            {
                return Some(group);
            }
        }
        for system_id in candidate_systems {
            if let Some(group) = Self::first_group_containing_system(expected, actual, system_id) {
                return Some(group);
            }
        }
        [actual, expected]
            .into_iter()
            .flatten()
            .find_map(|trace| trace.sgc_groups.first().cloned())
    }

    fn first_group_containing_system(
        expected: Option<&RuntimeTickReplayTrace>,
        actual: Option<&RuntimeTickReplayTrace>,
        system_id: &str,
    ) -> Option<RuntimeReplayGroupTrace> {
        [actual, expected].into_iter().flatten().find_map(|trace| {
            trace
                .sgc_groups
                .iter()
                .find(|group| group.systems.iter().any(|system| system == system_id))
                .cloned()
        })
    }

    fn diagnosis_summary(
        tick: u64,
        expected_hash: &str,
        actual_hash: &str,
        suspected_sgc_group: Option<&RuntimeReplayGroupTrace>,
        candidate_systems: &[String],
        component_changes: &[RuntimeReplayComponentTrace],
        emitted_events: &[RuntimeReplayEventTrace],
        rng_calls: &[RuntimeReplayRngCallTrace],
        mutation: &RuntimeReplayMutationTrace,
        input_packets: &[RuntimeReplayInputPacketTrace],
    ) -> String {
        let sgc_group = suspected_sgc_group
            .map(|group| {
                format!(
                    "{}:{}#{} systems={}",
                    group.phase,
                    group.group_id,
                    group.execution_index,
                    format_string_list(&group.systems)
                )
            })
            .unwrap_or_else(|| "unavailable".to_string());
        let component_labels = component_changes
            .iter()
            .map(|component| {
                format!(
                    "{}:{}:{} fields={}",
                    component.operation,
                    component.component_type_name,
                    component.component_type_id,
                    format_string_list(&component.field_names)
                )
            })
            .collect::<Vec<_>>();
        let event_labels = emitted_events
            .iter()
            .map(|event| {
                format!(
                    "{}#{} src={} keys={}",
                    event.event_type,
                    event.event_id,
                    event.source_entity_id,
                    format_string_list(&event.payload_keys)
                )
            })
            .collect::<Vec<_>>();
        let rng_labels = rng_calls
            .iter()
            .map(|rng| {
                format!(
                    "{}@{} deterministic={} seed={}",
                    rng.system_id,
                    rng.tick,
                    rng.deterministic,
                    rng.seed
                        .map(|seed| seed.to_string())
                        .unwrap_or_else(|| "none".to_string())
                )
            })
            .collect::<Vec<_>>();
        let input_labels = input_packets
            .iter()
            .map(|packet| {
                format!(
                    "peer={} tick={} seq={} player={} actions={} digest={} status={}",
                    packet.peer_id,
                    packet.tick,
                    packet.sequence_id,
                    packet
                        .player_id
                        .map(|player_id| player_id.to_string())
                        .unwrap_or_else(|| "none".to_string()),
                    format_string_list(&packet.action_names),
                    digest_prefix(&packet.digest),
                    packet.status
                )
            })
            .collect::<Vec<_>>();

        format!(
            "tick {} replay divergence: expected_hash={} actual_hash={}; SGC group {}; systems {}; components {}; events {}; RNG {}; mutations applied={} state_changes={} spawned={} destroyed={} added={} removed={} updated={}; input packets {}",
            tick,
            digest_prefix(expected_hash),
            digest_prefix(actual_hash),
            sgc_group,
            format_string_list(candidate_systems),
            format_string_list(&component_labels),
            format_string_list(&event_labels),
            format_string_list(&rng_labels),
            mutation.mutations_applied,
            mutation.state_changes,
            mutation.spawned_entities,
            mutation.destroyed_entities,
            mutation.added_components,
            mutation.removed_components,
            mutation.updated_components,
            format_string_list(&input_labels)
        )
    }

    pub fn print_state(&self, tick: u64, delta: &StateDelta, opts: &PrinterOpts) {
        print_state(tick, delta, &self.entity_store, &self.table_store, opts);
    }

    pub fn disconnect_engine(&mut self, reason: &str) {
        for bridge in &mut self.bridges {
            bridge.disconnect(reason);
        }
        self.bridges.clear();
    }

    pub fn engine_connected(&self) -> bool {
        self.bridges.iter().any(EngineBridge::is_connected)
    }

    pub fn adapter_type(&self) -> String {
        let adapters = self
            .bridges
            .iter()
            .filter(|bridge| bridge.is_connected())
            .map(|bridge| bridge.adapter_type().to_string())
            .collect::<Vec<_>>();
        match adapters.len() {
            0 => "headless".to_string(),
            1 => adapters[0].clone(),
            _ => format!("multi({})", adapters.join(",")),
        }
    }

    pub fn engine_bridge_stats(&self) -> Option<EngineBridgeStats> {
        let mut stats = None;
        for bridge in &self.bridges {
            stats = Some(match stats {
                None => bridge.stats(),
                Some(acc) => aggregate_bridge_stats(acc, bridge.stats()),
            });
        }
        stats
    }

    pub fn engine_connection_statuses(&self) -> Vec<RuntimeEngineConnectionStatus> {
        self.bridges
            .iter()
            .map(|bridge| {
                let stats = bridge.stats();
                RuntimeEngineConnectionStatus {
                    adapter_type: bridge.adapter_type().to_string(),
                    connected: bridge.is_connected(),
                    snapshots_sent: stats.snapshots_sent,
                    input_packets_received: stats.input_packets_received,
                    feedback_payloads_received: stats.feedback_payloads_received,
                    feedback_messages_received: stats.feedback_messages_received,
                    malformed_messages: stats.malformed_messages,
                    dropped_inputs: stats.dropped_inputs,
                    queued_inputs: stats.queued_inputs,
                    queued_feedback: stats.queued_feedback,
                }
            })
            .collect()
    }

    pub fn alive_count(&self) -> usize {
        self.entity_store.get_all_alive().len()
    }

    pub fn drain_engine_inputs(&mut self) -> Vec<xace_network_core::input::InputPacket> {
        std::mem::take(&mut self.engine_inputs)
    }

    pub fn pending_engine_input_count(&self) -> usize {
        self.engine_inputs.len()
    }

    pub fn pending_engine_feedback_count(&self) -> usize {
        self.feedback_buffer.pending_count()
    }

    pub fn spawn_summary(&self) -> &cgs_loader::SpawnSummary {
        &self.spawn_summary
    }

    pub fn register_component_migration_hook(
        &mut self,
        hook: RuntimeComponentMigrationHook,
    ) -> Result<()> {
        if hook.hook_id.trim().is_empty() {
            anyhow::bail!("component migration hook_id must not be empty");
        }
        if hook.from_schema_version.trim().is_empty() || hook.to_schema_version.trim().is_empty() {
            anyhow::bail!(
                "component migration hook '{}' must declare from/to schema versions",
                hook.hook_id
            );
        }
        if self
            .migration_hooks
            .iter()
            .any(|existing| existing.hook_id == hook.hook_id)
        {
            anyhow::bail!(
                "component migration hook '{}' is already registered",
                hook.hook_id
            );
        }
        self.migration_hooks.push(hook);
        self.migration_hooks
            .sort_by(|left, right| left.hook_id.cmp(&right.hook_id));
        Ok(())
    }

    pub fn migration_log(&self) -> &[RuntimeHotSwapMigrationReport] {
        &self.migration_log
    }

    pub fn config(&self) -> &RuntimeConfig {
        &self.config
    }

    pub fn phase_plan(&self) -> &cgs_loader::RuntimePhasePlan {
        &self.phase_plan
    }

    pub fn schedule_plan(&self) -> &cgs_loader::RuntimeSchedulePlan {
        &self.schedule_plan
    }

    pub fn schedule_identity(&self) -> &cgs_loader::RuntimeScheduleIdentity {
        &self.schedule_identity
    }

    pub fn schedule_snapshots(&self) -> &[cgs_loader::RuntimeScheduleSnapshot] {
        &self.schedule_snapshots
    }

    pub fn replay_traces(&self) -> &BTreeMap<u64, RuntimeTickReplayTrace> {
        &self.replay_traces
    }

    pub fn replay_trace_at_tick(&self, tick: u64) -> Option<&RuntimeTickReplayTrace> {
        self.replay_traces.get(&tick)
    }

    pub fn last_schedule_snapshot(&self) -> Option<&cgs_loader::RuntimeScheduleSnapshot> {
        self.schedule_snapshots.last()
    }

    pub fn classify_hot_swap_cgs_at_tick_boundary(
        &self,
        cgs_path: &Path,
        config: RuntimeConfig,
    ) -> Result<RuntimeHotSwapCompatibilityReport> {
        let candidate = load_hot_swap_candidate(cgs_path, config)?;
        Ok(self.classify_hot_swap_candidate(&candidate))
    }

    pub fn hot_swap_cgs_at_tick_boundary(
        &mut self,
        cgs_path: &Path,
        config: RuntimeConfig,
    ) -> Result<RuntimeHotSwapReport> {
        let requested_tick = self.phase_orch.current_tick();
        let pre_snapshot = self
            .world_snapshot()
            .map_err(|err| anyhow::anyhow!("capture pre-hot-swap world snapshot: {}", err))?;
        if !pre_snapshot.is_clean
            || pre_snapshot.has_pending_events()
            || pre_snapshot.has_pending_mutations()
        {
            anyhow::bail!(
                "runtime schema hot-swap requires a clean tick boundary at tick {}",
                requested_tick
            );
        }

        let previous_cgs_hash = self.spawn_summary.cgs_hash.clone();
        let previous_schema_version = self.spawn_summary.schema_version.clone();
        let previous_execution_plan_version = self.config.execution_plan_version;
        let previous_plan_hash = self.spawn_summary.execution_plan_hash.clone();
        let previous_system_ids = self.schedule_identity.scheduled_system_ids.clone();
        let previous_system_set = previous_system_ids.iter().cloned().collect::<BTreeSet<_>>();
        let preserved_entity_ids = self.entity_store.get_all_alive();
        let preserved_component_rows = pre_snapshot.component_tables_snapshot.total_row_count();

        let candidate = load_hot_swap_candidate(cgs_path, config)?;
        let compatibility = self.classify_hot_swap_candidate(&candidate);
        let migration_hooks = self.resolve_hot_swap_migration_hooks(&compatibility, &candidate)?;

        let additions = hot_swap_component_table_additions(
            &self.table_store,
            &candidate.summary.registered_components,
        )?;
        let table_rollback = self.table_store.rollback_snapshot();
        let added_component_tables =
            match apply_hot_swap_component_table_additions(&mut self.table_store, &additions) {
                Ok(added) => added,
                Err(err) => {
                    self.table_store.restore_rollback_snapshot(table_rollback);
                    return Err(err);
                }
            };
        let migration = match self.apply_hot_swap_migrations(
            &migration_hooks,
            &candidate,
            requested_tick,
            pre_snapshot.world_hash.clone(),
        ) {
            Ok(report) => report,
            Err(err) => {
                self.table_store.restore_rollback_snapshot(table_rollback);
                return Err(err);
            }
        };
        let post_table_snapshot = match self.world_snapshot() {
            Ok(snapshot) => snapshot,
            Err(err) => {
                self.table_store.restore_rollback_snapshot(table_rollback);
                anyhow::bail!("verify hot-swap state preservation: {}", err);
            }
        };
        if post_table_snapshot.entity_store_snapshot != pre_snapshot.entity_store_snapshot {
            self.table_store.restore_rollback_snapshot(table_rollback);
            anyhow::bail!(
                "runtime schema hot-swap changed entity state while preparing tick {}",
                requested_tick
            );
        }
        if let Some(migration_report) = &migration {
            if post_table_snapshot.world_hash != migration_report.migrated_world_hash {
                self.table_store.restore_rollback_snapshot(table_rollback);
                anyhow::bail!(
                    "runtime schema hot-swap migration hash changed during verification at tick {}",
                    requested_tick
                );
            }
        } else if post_table_snapshot.component_tables_snapshot
            != pre_snapshot.component_tables_snapshot
        {
            self.table_store.restore_rollback_snapshot(table_rollback);
            anyhow::bail!(
                "runtime schema hot-swap changed component rows while preparing tick {}",
                requested_tick
            );
        }

        let RuntimeHotSwapCandidate {
            config,
            summary: mut next_summary,
            phase_plan: next_phase_plan,
            schedule_plan: next_schedule_plan,
            identity: next_identity,
            registry: next_registry,
            scratch_table_store: _,
        } = candidate;

        next_summary.spawned_actors = self.spawn_summary.spawned_actors.clone();
        next_summary.entity_count = self.alive_count() as u32;

        let new_system_ids = next_identity.scheduled_system_ids.clone();
        let newly_active_system_ids = new_system_ids
            .iter()
            .filter(|system_id| !previous_system_set.contains(*system_id))
            .cloned()
            .collect::<Vec<_>>();
        let next_system_refs = next_phase_plan
            .iter()
            .flat_map(|(_, systems, _)| systems.iter().map(String::as_str))
            .collect::<Vec<_>>();

        self.config = config;
        self.phase_orch.update_schema_version(
            next_summary.schema_version.clone(),
            self.config.execution_plan_version,
        );
        self.determinism_guard.reconfigure_for_hot_swap(
            next_summary.schema_version.clone(),
            self.config.execution_plan_version,
            &next_system_refs,
        );
        self.registry = next_registry;
        self.phase_plan = next_phase_plan;
        self.schedule_plan = next_schedule_plan;
        self.schedule_identity = next_identity;
        self.feedback_log = FeedbackLog::new(
            next_summary.schema_version.clone(),
            self.config.execution_plan_version,
        );
        self.query_engine = QueryEngine::new();
        self.last_playback_commands.clear();
        self.replay_golden_log = None;

        let report = RuntimeHotSwapReport {
            schema: "xace.runtime.hot_swap_report.v1".to_string(),
            previous_cgs_hash,
            new_cgs_hash: next_summary.cgs_hash.clone(),
            previous_schema_version,
            new_schema_version: next_summary.schema_version.clone(),
            previous_execution_plan_version,
            new_execution_plan_version: self.config.execution_plan_version,
            previous_plan_hash,
            new_plan_hash: next_summary.execution_plan_hash.clone(),
            requested_tick,
            applied_tick: requested_tick,
            safe_tick_boundary: true,
            preserved_entity_ids,
            preserved_component_rows,
            added_component_tables,
            previous_system_ids,
            new_system_ids,
            newly_active_system_ids,
            compatibility,
            migration: migration.clone(),
        };
        self.spawn_summary = next_summary;
        if let Some(migration) = migration {
            self.migration_log.push(migration);
        }
        Ok(report)
    }

    fn classify_hot_swap_candidate(
        &self,
        candidate: &RuntimeHotSwapCandidate,
    ) -> RuntimeHotSwapCompatibilityReport {
        let previous_system_ids = self.schedule_identity.scheduled_system_ids.clone();
        let new_system_ids = candidate.identity.scheduled_system_ids.clone();
        let previous_system_set = previous_system_ids.iter().cloned().collect::<BTreeSet<_>>();
        let new_system_set = new_system_ids.iter().cloned().collect::<BTreeSet<_>>();
        let mut issues = Vec::new();
        let mut added_component_tables = Vec::new();
        let mut backfill_component_tables = Vec::new();
        let mut removed_component_tables = Vec::new();
        let mut changed_system_ids = BTreeSet::new();

        let previous_registrations =
            component_registration_map(&self.spawn_summary.registered_components);
        let new_registrations =
            component_registration_map(&candidate.summary.registered_components);

        for (type_id, previous) in &previous_registrations {
            match new_registrations.get(type_id) {
                Some(next) => {
                    if previous.name != next.name || previous.source != next.source {
                        issues.push(hot_swap_issue(
                            RuntimeHotSwapCompatibilityClass::Migratable,
                            "component_registration_changed",
                            format!(
                                "component type_id {} changed registration from '{}'/ {:?} to '{}'/ {:?}",
                                type_id,
                                previous.name,
                                previous.source,
                                next.name,
                                next.source
                            ),
                            Some(*type_id),
                            None,
                        ));
                    }
                }
                None => {
                    removed_component_tables.push(*type_id);
                    issues.push(hot_swap_issue(
                        RuntimeHotSwapCompatibilityClass::ResetRequired,
                        "component_table_removed",
                        format!(
                            "component type_id {} is registered in the live world but absent from the candidate schema",
                            type_id
                        ),
                        Some(*type_id),
                        None,
                    ));
                }
            }
        }

        for type_id in new_registrations.keys() {
            if previous_registrations.contains_key(type_id) {
                continue;
            }
            let candidate_rows = candidate
                .scratch_table_store
                .get_table(*type_id)
                .map(|table| table.count())
                .unwrap_or(0);
            if candidate_rows > 0 {
                backfill_component_tables.push(*type_id);
                issues.push(hot_swap_issue(
                    RuntimeHotSwapCompatibilityClass::Migratable,
                    "component_added_requires_backfill",
                    format!(
                        "component type_id {} appears on {} candidate actor instance(s) and requires deterministic backfill",
                        type_id, candidate_rows
                    ),
                    Some(*type_id),
                    None,
                ));
            } else {
                added_component_tables.push(*type_id);
                issues.push(hot_swap_issue(
                    RuntimeHotSwapCompatibilityClass::Additive,
                    "component_table_added_empty",
                    format!(
                        "component type_id {} is a new empty table and can be registered without row backfill",
                        type_id
                    ),
                    Some(*type_id),
                    None,
                ));
            }
        }

        if self.spawn_summary.mode_id != candidate.summary.mode_id {
            issues.push(hot_swap_issue(
                RuntimeHotSwapCompatibilityClass::ResetRequired,
                "mode_changed",
                format!(
                    "default mode changed from '{}' to '{}'",
                    self.spawn_summary.mode_id, candidate.summary.mode_id
                ),
                None,
                None,
            ));
        }

        if actor_topology(&self.spawn_summary) != actor_topology(&candidate.summary) {
            issues.push(hot_swap_issue(
                RuntimeHotSwapCompatibilityClass::ResetRequired,
                "actor_topology_changed",
                "actor IDs or spawn counts changed and require explicit reset approval".to_string(),
                None,
                None,
            ));
        }

        if self.spawn_summary.semantic_bindings != candidate.summary.semantic_bindings {
            issues.push(hot_swap_issue(
                RuntimeHotSwapCompatibilityClass::StateTransforming,
                "semantic_bindings_changed",
                "semantic playback bindings changed and require engine-side side-effect policy"
                    .to_string(),
                None,
                None,
            ));
        }

        if self.schedule_identity.source != candidate.identity.source {
            issues.push(hot_swap_issue(
                RuntimeHotSwapCompatibilityClass::StateTransforming,
                "schedule_source_changed",
                format!(
                    "schedule source changed from {:?} to {:?}",
                    self.schedule_identity.source, candidate.identity.source
                ),
                None,
                None,
            ));
        }

        let added_system_ids = new_system_ids
            .iter()
            .filter(|system_id| !previous_system_set.contains(*system_id))
            .cloned()
            .collect::<Vec<_>>();
        for system_id in &added_system_ids {
            issues.push(hot_swap_issue(
                RuntimeHotSwapCompatibilityClass::Additive,
                "system_added",
                format!("system '{}' is newly scheduled", system_id),
                None,
                Some(system_id.clone()),
            ));
        }

        let removed_system_ids = previous_system_ids
            .iter()
            .filter(|system_id| !new_system_set.contains(*system_id))
            .cloned()
            .collect::<Vec<_>>();
        for system_id in &removed_system_ids {
            issues.push(hot_swap_issue(
                RuntimeHotSwapCompatibilityClass::StateTransforming,
                "system_removed",
                format!("system '{}' was removed from the live schedule", system_id),
                None,
                Some(system_id.clone()),
            ));
        }

        let previous_common_order = previous_system_ids
            .iter()
            .filter(|system_id| new_system_set.contains(*system_id))
            .cloned()
            .collect::<Vec<_>>();
        let new_common_order = new_system_ids
            .iter()
            .filter(|system_id| previous_system_set.contains(*system_id))
            .cloned()
            .collect::<Vec<_>>();
        if previous_common_order != new_common_order {
            issues.push(hot_swap_issue(
                RuntimeHotSwapCompatibilityClass::StateTransforming,
                "system_order_changed",
                "relative order of existing scheduled systems changed".to_string(),
                None,
                None,
            ));
        }

        let previous_signatures = system_signature_map(&self.spawn_summary.runtime_systems);
        let new_signatures = system_signature_map(&candidate.summary.runtime_systems);
        let previous_phase_by_system = schedule_phase_by_system(&self.schedule_identity.groups);
        let new_phase_by_system = schedule_phase_by_system(&candidate.identity.groups);
        for system_id in previous_system_set.intersection(&new_system_set) {
            match (
                previous_signatures.get(system_id),
                new_signatures.get(system_id),
            ) {
                (Some(previous), Some(next)) if previous != next => {
                    changed_system_ids.insert(system_id.clone());
                    issues.push(hot_swap_issue(
                        RuntimeHotSwapCompatibilityClass::StateTransforming,
                        "system_contract_changed",
                        format!("system '{}' changed runtime execution contract", system_id),
                        None,
                        Some(system_id.clone()),
                    ));
                }
                (Some(_), Some(_)) => {}
                _ => {
                    changed_system_ids.insert(system_id.clone());
                    issues.push(hot_swap_issue(
                        RuntimeHotSwapCompatibilityClass::StateTransforming,
                        "system_contract_unresolved",
                        format!(
                            "system '{}' could not be resolved in both old and new runtime system tables",
                            system_id
                        ),
                        None,
                        Some(system_id.clone()),
                    ));
                }
            }

            if previous_phase_by_system.get(system_id) != new_phase_by_system.get(system_id) {
                changed_system_ids.insert(system_id.clone());
                issues.push(hot_swap_issue(
                    RuntimeHotSwapCompatibilityClass::StateTransforming,
                    "system_phase_changed",
                    format!("system '{}' moved to a different schedule phase", system_id),
                    None,
                    Some(system_id.clone()),
                ));
            }

            if self.schedule_identity.system_access.get(system_id)
                != candidate.identity.system_access.get(system_id)
            {
                changed_system_ids.insert(system_id.clone());
                issues.push(hot_swap_issue(
                    RuntimeHotSwapCompatibilityClass::StateTransforming,
                    "system_access_changed",
                    format!("system '{}' changed SGC component access", system_id),
                    None,
                    Some(system_id.clone()),
                ));
            }

            if self.schedule_identity.system_dependencies.get(system_id)
                != candidate.identity.system_dependencies.get(system_id)
            {
                changed_system_ids.insert(system_id.clone());
                issues.push(hot_swap_issue(
                    RuntimeHotSwapCompatibilityClass::StateTransforming,
                    "system_dependencies_changed",
                    format!("system '{}' changed SGC dependencies", system_id),
                    None,
                    Some(system_id.clone()),
                ));
            }
        }

        let overall_class = issues
            .iter()
            .map(|issue| issue.class)
            .max()
            .unwrap_or(RuntimeHotSwapCompatibilityClass::Additive);
        let migration_required = issues
            .iter()
            .any(|issue| issue.class == RuntimeHotSwapCompatibilityClass::Migratable);
        let reset_required = issues
            .iter()
            .any(|issue| issue.class == RuntimeHotSwapCompatibilityClass::ResetRequired);
        let live_compatible = issues
            .iter()
            .all(|issue| issue.class == RuntimeHotSwapCompatibilityClass::Additive);

        RuntimeHotSwapCompatibilityReport {
            schema: "xace.runtime.hot_swap_compatibility.v1".to_string(),
            overall_class,
            live_compatible,
            migration_required,
            reset_required,
            added_component_tables,
            backfill_component_tables,
            removed_component_tables,
            added_system_ids,
            removed_system_ids,
            changed_system_ids: changed_system_ids.into_iter().collect(),
            previous_system_ids,
            new_system_ids,
            issues,
        }
    }

    fn resolve_hot_swap_migration_hooks(
        &self,
        compatibility: &RuntimeHotSwapCompatibilityReport,
        candidate: &RuntimeHotSwapCandidate,
    ) -> Result<Vec<RuntimeComponentMigrationHook>> {
        if compatibility.live_compatible {
            return Ok(Vec::new());
        }
        if compatibility
            .issues
            .iter()
            .any(|issue| issue.class >= RuntimeHotSwapCompatibilityClass::StateTransforming)
        {
            anyhow::bail!("{}", hot_swap_refusal_message(compatibility));
        }

        let from_schema_version = self.spawn_summary.schema_version.as_str();
        let to_schema_version = candidate.summary.schema_version.as_str();
        let mut resolved = Vec::new();
        let mut resolved_hook_ids = BTreeSet::new();
        for issue in compatibility
            .issues
            .iter()
            .filter(|issue| issue.class == RuntimeHotSwapCompatibilityClass::Migratable)
        {
            let Some(hook) = self
                .migration_hooks
                .iter()
                .find(|hook| hook.supports_issue(from_schema_version, to_schema_version, issue))
            else {
                anyhow::bail!(
                    "{} missing_migration_hook code={} component_type_id={:?} from_schema_version={} to_schema_version={}",
                    hot_swap_refusal_message(compatibility),
                    issue.code,
                    issue.component_type_id,
                    from_schema_version,
                    to_schema_version
                );
            };

            if resolved_hook_ids.insert(hook.hook_id.clone()) {
                resolved.push(hook.clone());
            }
        }
        Ok(resolved)
    }

    fn apply_hot_swap_migrations(
        &mut self,
        hooks: &[RuntimeComponentMigrationHook],
        candidate: &RuntimeHotSwapCandidate,
        requested_tick: u64,
        old_world_hash: String,
    ) -> Result<Option<RuntimeHotSwapMigrationReport>> {
        if hooks.is_empty() {
            return Ok(None);
        }

        let mut records = Vec::new();
        for hook in hooks {
            match hook.operation {
                RuntimeComponentMigrationOperation::BackfillFromCandidateDefaults => {
                    let candidate_table = candidate
                        .scratch_table_store
                        .get_table(hook.component_type_id)
                        .ok_or_else(|| {
                            anyhow::anyhow!(
                                "migration hook '{}' could not find candidate component table {}",
                                hook.hook_id,
                                hook.component_type_id
                            )
                        })?;
                    if candidate_table.is_empty() {
                        anyhow::bail!(
                            "migration hook '{}' matched component {} but candidate table has no default rows",
                            hook.hook_id,
                            hook.component_type_id
                        );
                    }
                    if !self.table_store.has_table(hook.component_type_id) {
                        anyhow::bail!(
                            "migration hook '{}' cannot write unregistered component table {}",
                            hook.hook_id,
                            hook.component_type_id
                        );
                    }

                    let old_component_hash = component_table_rows_hash(
                        hook.component_type_id,
                        self.table_store.get_table(hook.component_type_id),
                    )?;
                    let mut entity_ids = Vec::new();
                    for (entity_id, component_json) in candidate_table.iter() {
                        if !self.entity_store.exists(entity_id) {
                            anyhow::bail!(
                                "migration hook '{}' refused component {} row for non-present entity {}",
                                hook.hook_id,
                                hook.component_type_id,
                                entity_id
                            );
                        }
                        if self
                            .table_store
                            .has_component(entity_id, hook.component_type_id)
                        {
                            anyhow::bail!(
                                "migration hook '{}' refused to overwrite component {} on entity {}",
                                hook.hook_id,
                                hook.component_type_id,
                                entity_id
                            );
                        }
                        self.table_store
                            .add_component(
                                entity_id,
                                hook.component_type_id,
                                component_json.to_string(),
                                requested_tick,
                            )
                            .map_err(|err| {
                                anyhow::anyhow!(
                                    "migration hook '{}' failed to backfill component {} on entity {}: {}",
                                    hook.hook_id,
                                    hook.component_type_id,
                                    entity_id,
                                    err
                                )
                            })?;
                        entity_ids.push(entity_id);
                    }

                    let new_component_hash = component_table_rows_hash(
                        hook.component_type_id,
                        self.table_store.get_table(hook.component_type_id),
                    )?;
                    records.push(RuntimeComponentMigrationRecord {
                        hook_id: hook.hook_id.clone(),
                        operation: hook.operation.as_str().to_string(),
                        component_type_id: hook.component_type_id,
                        rows_written: entity_ids.len(),
                        entity_ids,
                        old_component_hash,
                        new_component_hash,
                    });
                }
            }
        }

        let migrated_snapshot = self
            .world_snapshot()
            .map_err(|err| anyhow::anyhow!("capture post-migration world snapshot: {}", err))?;
        Ok(Some(RuntimeHotSwapMigrationReport {
            schema: "xace.runtime.hot_swap_migration_report.v1".to_string(),
            from_schema_version: self.spawn_summary.schema_version.clone(),
            to_schema_version: candidate.summary.schema_version.clone(),
            requested_tick,
            old_world_hash,
            migrated_world_hash: migrated_snapshot.world_hash,
            records,
        }))
    }

    pub fn parallel_group_execution_policy(&self) -> ParallelGroupExecutionPolicy {
        self.phase_orch.parallel_group_execution_policy()
    }

    pub fn status(&self) -> RuntimeStatus {
        let last = self.last_tick_result.as_ref();
        let bridge_stats = self.engine_bridge_stats().unwrap_or_default();
        let latest_world_hash = self
            .determinism_guard
            .latest_hash()
            .map(|(_, hash)| hash.to_string())
            .unwrap_or_default();
        let parallel_group_execution_policy = self.parallel_group_execution_policy();
        RuntimeStatus {
            tick: self.phase_orch.current_tick(),
            alive_count: self.alive_count(),
            engine_connected: self.engine_connected(),
            adapter_type: self.adapter_type(),
            engine_connections: self.engine_connection_statuses(),
            engine_snapshots_sent: bridge_stats.snapshots_sent,
            engine_input_packets_received: bridge_stats.input_packets_received,
            engine_feedback_payloads_received: bridge_stats.feedback_payloads_received,
            engine_feedback_messages_received: bridge_stats.feedback_messages_received,
            engine_malformed_messages: bridge_stats.malformed_messages,
            engine_dropped_inputs: bridge_stats.dropped_inputs,
            pending_engine_inputs: self.pending_engine_input_count(),
            pending_engine_feedback: self.pending_engine_feedback_count(),
            registered_systems: self.registry.system_count(),
            phase_count: self.phase_plan.len(),
            last_engine_feedback_processed: last
                .map(|summary| summary.engine_feedback_processed)
                .unwrap_or(0),
            last_engine_feedback_invalid: last
                .map(|summary| summary.engine_feedback_invalid)
                .unwrap_or(0),
            last_engine_feedback_errors: last
                .map(|summary| summary.engine_feedback_errors)
                .unwrap_or(0),
            latest_world_hash,
            cgs_hash: self.spawn_summary.cgs_hash.clone(),
            schema_version: self.spawn_summary.schema_version.clone(),
            execution_plan_version: self.config.execution_plan_version.to_string(),
            parallel_group_execution_policy: parallel_group_execution_policy.as_str().to_string(),
            parallel_group_worker_threads: parallel_group_execution_policy.uses_worker_threads(),
            hash_log: self.hash_log(),
        }
    }

    pub fn last_tick_result(&self) -> Option<&RuntimeTickSummary> {
        self.last_tick_result.as_ref()
    }

    pub fn hash_log(&self) -> Vec<RuntimeHashRecord> {
        self.determinism_guard
            .hash_log()
            .into_iter()
            .map(|(tick, world_hash)| RuntimeHashRecord { tick, world_hash })
            .collect()
    }

    pub fn world_hash_at_tick(&self, tick: u64) -> Option<&str> {
        self.determinism_guard.hash_at_tick(tick)
    }

    pub fn record_replay_hash_log(&mut self) -> Result<usize> {
        let records = self.hash_log();
        if records.is_empty() {
            anyhow::bail!("Cannot record replay before at least one tick hash exists");
        }

        let mut log = GoldenLog::new(
            self.spawn_summary.schema_version.clone(),
            self.config.execution_plan_version,
        );
        for record in records {
            log.record(record.tick, record.world_hash);
        }
        let count = log.tick_count();
        self.replay_golden_log = Some(log);
        Ok(count)
    }

    pub fn recorded_replay_tick_count(&self) -> usize {
        self.replay_golden_log
            .as_ref()
            .map(GoldenLog::tick_count)
            .unwrap_or(0)
    }

    pub fn validate_recorded_replay_from_cgs(
        &self,
        cgs_path: &Path,
        config: RuntimeConfig,
    ) -> Result<RuntimeReplayValidation> {
        let golden = self
            .replay_golden_log
            .as_ref()
            .ok_or_else(|| {
                anyhow::anyhow!("Cannot validate replay before replay_record captures a hash log")
            })?
            .clone();

        let mut replay_runtime = RuntimeOrchestrator::initialise_with_config(cgs_path, config)?;
        let mut live_hashes = BTreeMap::new();
        let mut live_schedules = BTreeMap::new();
        let mut live_traces = BTreeMap::new();
        for _ in 0..=golden.end_tick {
            let result = replay_runtime
                .tick()
                .map_err(|err| anyhow::anyhow!("{:?}", err))?;
            if let Some(snapshot) = replay_runtime.last_schedule_snapshot() {
                live_schedules.insert(result.tick, snapshot.clone());
            }
            if let Some(trace) = replay_runtime.replay_trace_at_tick(result.tick) {
                live_traces.insert(result.tick, trace.clone());
            }
            live_hashes.insert(result.tick, result.world_hash);
        }

        let mut compared_ticks = 0;
        let mut schedule_snapshots_compared = 0;
        for (tick, expected_hash) in golden.iter_ordered() {
            compared_ticks += 1;
            match live_hashes.get(&tick) {
                Some(actual_hash) if actual_hash == expected_hash => {}
                Some(actual_hash) => {
                    return Ok(RuntimeReplayValidation {
                        passed: false,
                        compared_ticks,
                        first_mismatch: Some(RuntimeReplayMismatch {
                            tick,
                            expected_hash: expected_hash.to_string(),
                            actual_hash: actual_hash.clone(),
                            diagnosis: self.diagnose_replay_mismatch(
                                tick,
                                expected_hash,
                                actual_hash,
                                live_traces.get(&tick).cloned(),
                            ),
                        }),
                        schedule_snapshots_compared,
                        first_schedule_mismatch: None,
                    });
                }
                None => {
                    return Ok(RuntimeReplayValidation {
                        passed: false,
                        compared_ticks,
                        first_mismatch: Some(RuntimeReplayMismatch {
                            tick,
                            expected_hash: expected_hash.to_string(),
                            actual_hash: String::new(),
                            diagnosis: self.diagnose_replay_mismatch(tick, expected_hash, "", None),
                        }),
                        schedule_snapshots_compared,
                        first_schedule_mismatch: None,
                    });
                }
            }

            let expected_schedule = self.schedule_identity.snapshot_for_tick(tick);
            if let Some(recorded_schedule) = self
                .schedule_snapshots
                .iter()
                .find(|snapshot| snapshot.tick == tick)
            {
                if recorded_schedule != &expected_schedule {
                    return Ok(RuntimeReplayValidation {
                        passed: false,
                        compared_ticks,
                        first_mismatch: None,
                        schedule_snapshots_compared,
                        first_schedule_mismatch: Some(RuntimeScheduleReplayMismatch {
                            tick,
                            expected: expected_schedule,
                            actual: Some(recorded_schedule.clone()),
                        }),
                    });
                }
            } else {
                return Ok(RuntimeReplayValidation {
                    passed: false,
                    compared_ticks,
                    first_mismatch: None,
                    schedule_snapshots_compared,
                    first_schedule_mismatch: Some(RuntimeScheduleReplayMismatch {
                        tick,
                        expected: expected_schedule,
                        actual: None,
                    }),
                });
            }

            match live_schedules.get(&tick) {
                Some(actual_schedule) if actual_schedule == &expected_schedule => {
                    schedule_snapshots_compared += 1;
                }
                Some(actual_schedule) => {
                    return Ok(RuntimeReplayValidation {
                        passed: false,
                        compared_ticks,
                        first_mismatch: None,
                        schedule_snapshots_compared,
                        first_schedule_mismatch: Some(RuntimeScheduleReplayMismatch {
                            tick,
                            expected: expected_schedule,
                            actual: Some(actual_schedule.clone()),
                        }),
                    });
                }
                None => {
                    return Ok(RuntimeReplayValidation {
                        passed: false,
                        compared_ticks,
                        first_mismatch: None,
                        schedule_snapshots_compared,
                        first_schedule_mismatch: Some(RuntimeScheduleReplayMismatch {
                            tick,
                            expected: expected_schedule,
                            actual: None,
                        }),
                    });
                }
            }
        }

        Ok(RuntimeReplayValidation {
            passed: true,
            compared_ticks,
            first_mismatch: None,
            schedule_snapshots_compared,
            first_schedule_mismatch: None,
        })
    }

    pub fn control_snapshot(&self) -> TickSnapshot {
        let last = self.last_tick_result.as_ref();
        let mut snapshot = TickSnapshot::new(
            self.phase_orch.current_tick(),
            deterministic_timestamp_ms(
                self.phase_orch.current_tick(),
                self.config.bridge.tick_rate,
            ),
            build_entity_states(&self.entity_store, &self.table_store),
            last.map(|summary| summary.spawned_ids.clone())
                .unwrap_or_default(),
            last.map(|summary| summary.destroyed_ids.clone())
                .unwrap_or_default(),
            Vec::new(),
        );
        snapshot.playback_commands = self.last_playback_commands.clone();
        snapshot
    }

    pub fn world_snapshot(&self) -> Result<WorldSnapshot, XaceError> {
        let mut snapshot_engine = SnapshotEngine::standard(
            self.spawn_summary.schema_version.clone(),
            self.config.execution_plan_version,
            self.config.world_seed,
        );
        let mut snapshot = snapshot_engine.take_snapshot(
            self.phase_orch.current_tick(),
            &self.entity_store,
            &self.table_store,
        )?;
        snapshot.cgs_hash = self.spawn_summary.cgs_hash.clone();
        snapshot.world_hash.clear();
        snapshot.world_hash = WorldHasher::compute(&snapshot);
        Ok(snapshot)
    }

    pub fn restore_world_snapshot(&mut self, snapshot: &WorldSnapshot) -> Result<(), XaceError> {
        if snapshot.world_hash.is_empty() {
            return Err(XaceError::FatalError {
                message: format!(
                    "Cannot restore snapshot at tick {} without a canonical world_hash",
                    snapshot.tick
                ),
                context: xace_core::errors::xace_error::ErrorContext::new(
                    "RuntimeOrchestrator",
                    "restore_world_snapshot",
                )
                .with_tick(snapshot.tick),
                snapshot_recovery_possible: false,
            });
        }
        if let Err(reason) = validate_restorable_snapshot(snapshot) {
            return Err(XaceError::ValidationFailure {
                message: format!(
                    "Cannot restore runtime snapshot at tick {} because it violates X10-012 restore completeness: {}",
                    snapshot.tick, reason
                ),
                context: xace_core::errors::xace_error::ErrorContext::new(
                    "RuntimeOrchestrator",
                    "restore_world_snapshot",
                )
                .with_tick(snapshot.tick),
                rule_violated: "X10-012".into(),
                failed_path: reason.failed_path().into(),
            });
        }
        let pre_restore_hash = WorldHasher::compute(snapshot);
        if pre_restore_hash != snapshot.world_hash {
            return Err(XaceError::FatalError {
                message: format!(
                    "Snapshot hash mismatch before live restore at tick {} — expected '{}', got '{}'",
                    snapshot.tick, snapshot.world_hash, pre_restore_hash,
                ),
                context: xace_core::errors::xace_error::ErrorContext::new(
                    "RuntimeOrchestrator",
                    "restore_world_snapshot",
                )
                .with_tick(snapshot.tick),
                snapshot_recovery_possible: false,
            });
        }
        self.disconnect_engine("runtime_snapshot_restore");
        let mut snapshot_engine = SnapshotEngine::standard(
            self.spawn_summary.schema_version.clone(),
            self.config.execution_plan_version,
            self.config.world_seed,
        );
        snapshot_engine.restore_snapshot(
            snapshot,
            &mut self.entity_store,
            &mut self.table_store,
        )?;
        let mut restored_snapshot =
            snapshot_engine.take_snapshot(snapshot.tick, &self.entity_store, &self.table_store)?;
        restored_snapshot.cgs_hash = snapshot.cgs_hash.clone();
        restored_snapshot.world_hash.clear();
        restored_snapshot.world_hash = WorldHasher::compute(&restored_snapshot);
        if restored_snapshot.world_hash != snapshot.world_hash {
            return Err(XaceError::FatalError {
                message: format!(
                    "Live restore hash mismatch at tick {} — expected '{}', got '{}'",
                    snapshot.tick, snapshot.world_hash, restored_snapshot.world_hash,
                ),
                context: xace_core::errors::xace_error::ErrorContext::new(
                    "RuntimeOrchestrator",
                    "restore_world_snapshot",
                )
                .with_tick(snapshot.tick),
                snapshot_recovery_possible: false,
            });
        }
        self.phase_orch.restore_tick(snapshot.tick);
        self.determinism_guard = build_determinism_guard(
            self.config.determinism_guard_mode,
            &self.spawn_summary.schema_version,
            self.config.execution_plan_version,
            &self.phase_plan,
        );
        self.rng_interceptor =
            RngInterceptor::new(self.config.world_seed, self.config.determinism_guard_mode);
        self.query_engine = QueryEngine::new();
        self.event_bus = EventBus::new();
        self.mutation_gate = MutationGate::new();
        self.engine_inputs.clear();
        self.schedule_snapshots
            .retain(|schedule| schedule.tick < snapshot.tick);
        self.replay_traces.retain(|tick, _| *tick < snapshot.tick);
        let _ = self.feedback_buffer.drain_sorted();
        self.feedback_validator.reset_for_next_tick();
        self.feedback_log = FeedbackLog::new(
            self.spawn_summary.schema_version.clone(),
            self.config.execution_plan_version,
        );
        self.last_tick_result = None;
        self.last_playback_commands.clear();
        self.replay_golden_log = None;
        Ok(())
    }

    fn pump_engine_inbound(&mut self) {
        for bridge in &mut self.bridges {
            bridge.pump_inbound();
        }
    }

    fn collect_engine_inputs_from_bridge(&mut self) {
        for bridge in &mut self.bridges {
            self.engine_inputs.extend(bridge.take_input_packets());
        }
    }

    fn process_engine_feedback_at_tick_start(&mut self) -> RuntimeFeedbackDrainReport {
        let tick = self.phase_orch.current_tick();
        self.feedback_validator.reset_for_next_tick();

        let drained = self.feedback_buffer.drain_sorted();
        self.feedback_log.record_tick(tick, drained.clone());
        let attempted = drained.len();
        let valid = self.feedback_validator.filter_valid(drained);
        let invalid = attempted.saturating_sub(valid.len());
        let (route_report, errors) = self.feedback_router.route_all_report(valid);
        for err in &errors {
            log::warn!("Engine feedback handler error at tick {}: {}", tick, err);
        }
        RuntimeFeedbackDrainReport::from_route_report(route_report, invalid, errors.len())
    }

    pub fn entity_is_alive(&self, entity_id: u64) -> bool {
        self.entity_store.is_alive(entity_id)
    }

    pub fn set_preview_component_field(
        &mut self,
        entity_id: u64,
        component_type_id: u32,
        field_path: &str,
        value: Value,
    ) -> Result<()> {
        if !self.entity_store.is_alive(entity_id) {
            anyhow::bail!("entity {} is not alive", entity_id);
        }
        if !self.table_store.has_component(entity_id, component_type_id) {
            anyhow::bail!(
                "entity {} does not have component type {}",
                entity_id,
                component_type_id
            );
        }
        validate_preview_field_path(field_path)?;
        let current = self
            .table_store
            .get_component(entity_id, component_type_id)
            .ok_or_else(|| anyhow::anyhow!("component disappeared during edit"))?;
        let mut component_json: Value = serde_json::from_str(current)
            .map_err(|err| anyhow::anyhow!("component JSON is invalid: {}", err))?;
        set_json_path(&mut component_json, field_path, value)?;
        self.table_store
            .update_component(
                entity_id,
                component_type_id,
                serde_json::to_string(&component_json)?,
                self.phase_orch.current_tick(),
            )
            .map_err(|err| anyhow::anyhow!("component update failed: {}", err))?;
        Ok(())
    }

    fn send_tick_to_engine(
        &mut self,
        result: &TickResult,
        playback_commands: &[EnginePlaybackCommand],
    ) {
        if self.bridges.is_empty() {
            return;
        }
        let spawned = result
            .state_delta
            .spawned_entities
            .iter()
            .map(|entity| entity.entity_id)
            .collect::<Vec<u64>>();
        let destroyed = result
            .state_delta
            .destroyed_entities
            .iter()
            .map(|entity| entity.entity_id)
            .collect::<Vec<_>>();

        let mut connected_bridges = Vec::with_capacity(self.bridges.len());
        for mut bridge in std::mem::take(&mut self.bridges) {
            let still_connected = bridge.send_tick(
                result.tick,
                &self.entity_store,
                &self.table_store,
                spawned.clone(),
                destroyed.clone(),
                playback_commands.to_vec(),
            );
            if still_connected {
                self.engine_inputs.extend(bridge.take_input_packets());
                connected_bridges.push(bridge);
            } else {
                log::warn!("Engine disconnected; continuing with remaining adapters");
            }
        }
        self.bridges = connected_bridges;
    }

    fn playback_commands_for_events(&self, events: &[Event]) -> Vec<EnginePlaybackCommand> {
        events
            .iter()
            .flat_map(|event| {
                self.spawn_summary
                    .semantic_bindings
                    .commands_for_event(event)
                    .into_iter()
            })
            .map(EnginePlaybackCommand::from)
            .collect()
    }

    fn apply_pending_engine_inputs(
        &mut self,
    ) -> Result<Vec<RuntimeEngineInputApplication>, XaceError> {
        let inputs = std::mem::take(&mut self.engine_inputs);
        let mut applications = Vec::new();
        for packet in inputs {
            let Some(player_id) = packet.player_id else {
                applications.push(RuntimeEngineInputApplication {
                    packet,
                    applied: false,
                    status: "missing_player_id".to_string(),
                });
                continue;
            };
            if player_id == 0 {
                applications.push(RuntimeEngineInputApplication {
                    packet,
                    applied: false,
                    status: "reserved_player_id".to_string(),
                });
                continue;
            }
            if !self.entity_store.is_alive(player_id) {
                applications.push(RuntimeEngineInputApplication {
                    packet,
                    applied: false,
                    status: "player_entity_not_alive".to_string(),
                });
                continue;
            }
            let input_json = runtime_input_component_json(&packet);
            if self
                .table_store
                .has_component(player_id, cgs_loader::type_ids::INPUT)
            {
                self.table_store.update_component(
                    player_id,
                    cgs_loader::type_ids::INPUT,
                    input_json,
                    self.phase_orch.current_tick(),
                )?;
            } else {
                self.table_store.add_component(
                    player_id,
                    cgs_loader::type_ids::INPUT,
                    input_json,
                    self.phase_orch.current_tick(),
                )?;
            }
            applications.push(RuntimeEngineInputApplication {
                packet,
                applied: true,
                status: "applied".to_string(),
            });
        }
        Ok(applications)
    }

    fn session_id(&self) -> String {
        format!("session-{}", std::process::id())
    }

    fn handshake_engine_connections(
        &mut self,
        connections: Vec<tcp_server::EngineConnection>,
    ) -> Result<()> {
        for conn in connections {
            let bridge = EngineBridge::handshake_with_config(
                conn.writer()?,
                conn.buf_reader()?,
                self.session_id(),
                self.spawn_summary.cgs_hash.clone(),
                self.spawn_summary.schema_version.clone(),
                &self.entity_store,
                &self.table_store,
                self.feedback_buffer.clone(),
                self.config.bridge.clone(),
            )?;
            self.bridges.push(bridge);
        }
        Ok(())
    }
}

fn merge_distinct<T: Clone + PartialEq>(first: &[T], second: &[T]) -> Vec<T> {
    let mut merged = first.to_vec();
    for item in second {
        if !merged.contains(item) {
            merged.push(item.clone());
        }
    }
    merged
}

fn json_field_names(component_json: &str) -> Vec<String> {
    let Ok(Value::Object(map)) = serde_json::from_str::<Value>(component_json) else {
        return Vec::new();
    };
    map.keys().cloned().collect()
}

fn component_update_field_names(change: &ComponentChange) -> Vec<String> {
    let mut fields = Vec::new();
    for field in &change.field_changes {
        if field.field_name == "data" {
            let expanded = json_field_names(&field.value_json);
            if !expanded.is_empty() {
                fields.extend(expanded);
                continue;
            }
        }
        fields.push(field.field_name.clone());
    }
    fields.sort();
    fields.dedup();
    fields
}

fn format_string_list(values: &[String]) -> String {
    if values.is_empty() {
        "none".to_string()
    } else {
        values.join(",")
    }
}

fn digest_prefix(value: &str) -> String {
    if value.is_empty() {
        "none".to_string()
    } else {
        value.chars().take(12).collect()
    }
}

fn aggregate_bridge_stats(acc: EngineBridgeStats, next: EngineBridgeStats) -> EngineBridgeStats {
    EngineBridgeStats {
        snapshots_sent: acc.snapshots_sent.saturating_add(next.snapshots_sent),
        bytes_sent: acc.bytes_sent.saturating_add(next.bytes_sent),
        input_packets_received: acc
            .input_packets_received
            .saturating_add(next.input_packets_received),
        feedback_payloads_received: acc
            .feedback_payloads_received
            .saturating_add(next.feedback_payloads_received),
        feedback_messages_received: acc
            .feedback_messages_received
            .saturating_add(next.feedback_messages_received),
        malformed_messages: acc
            .malformed_messages
            .saturating_add(next.malformed_messages),
        dropped_inputs: acc.dropped_inputs.saturating_add(next.dropped_inputs),
        queued_inputs: acc.queued_inputs.saturating_add(next.queued_inputs),
        queued_feedback: acc.queued_feedback.saturating_add(next.queued_feedback),
    }
}

fn deterministic_timestamp_ms(tick: u64, tick_rate: u32) -> u64 {
    let rate = u64::from(tick_rate.max(1));
    tick.saturating_mul(1000) / rate
}

fn runtime_input_component_json(packet: &xace_network_core::input::InputPacket) -> String {
    let mut move_x = 0.0_f32;
    let mut move_z = 0.0_f32;
    let mut attack_pressed = false;
    let mut attack_started = false;
    let mut interact_pressed = false;
    let mut interact_started = false;
    let mut pickup_pressed = false;
    let mut pickup_started = false;
    let mut dash_pressed = false;
    let mut dash_started = false;
    let mut active_actions = Vec::new();

    for action in &packet.actions {
        let canonical = canonical_action_name(&action.action);
        match canonical.as_str() {
            "move" | "move2d" | "movement" => {
                move_x += action.value;
                move_z += action.secondary_value;
            }
            "movex" | "axisx" | "leftstickx" => move_x += action.value,
            "movez" | "axisz" | "movey" | "axisy" | "leftsticky" => move_z += action.value,
            "moveforward" | "forward" => move_z += action.value,
            "moveback" | "back" | "backward" => move_z -= action.value,
            "moveright" | "right" => move_x += action.value,
            "moveleft" | "left" => move_x -= action.value,
            "attack" | "primaryattack" | "fire" => {
                let state = button_state(action);
                attack_pressed |= state.pressed;
                attack_started |= state.started;
                if state.pressed {
                    active_actions.push("Attack");
                }
            }
            "interact" | "use" => {
                let state = button_state(action);
                interact_pressed |= state.pressed;
                interact_started |= state.started;
                if state.pressed {
                    active_actions.push("Interact");
                }
            }
            "pickup" | "pickupitem" => {
                let state = button_state(action);
                pickup_pressed |= state.pressed;
                pickup_started |= state.started;
                interact_pressed |= state.pressed;
                interact_started |= state.started;
                if state.pressed {
                    active_actions.push("Pickup");
                }
            }
            "dash" | "sprint" => {
                let state = button_state(action);
                dash_pressed |= state.pressed;
                dash_started |= state.started;
                if state.pressed {
                    active_actions.push("Dash");
                }
            }
            _ => {}
        }
    }

    active_actions.sort_unstable();
    active_actions.dedup();

    json!({
        "move_x": move_x.clamp(-1.0, 1.0),
        "move_z": move_z.clamp(-1.0, 1.0),
        "attack_pressed": attack_pressed,
        "attack_started": attack_started,
        "interact_pressed": interact_pressed,
        "interact_started": interact_started,
        "pickup_pressed": pickup_pressed,
        "pickup_started": pickup_started,
        "dash_pressed": dash_pressed,
        "dash_started": dash_started,
        "active_actions": active_actions,
        "sequence_id": packet.sequence_id,
        "peer_id": packet.peer_id,
        "source_tick": packet.tick,
        "device_id": packet.device_id,
        "predicted": packet.predicted,
    })
    .to_string()
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct ButtonState {
    pressed: bool,
    started: bool,
}

fn button_state(action: &xace_network_core::input::InputAction) -> ButtonState {
    use xace_network_core::input::InputActionPhase;

    let cancelled = matches!(action.phase, InputActionPhase::Cancelled);
    let pressed = !cancelled && action.value > 0.0;
    ButtonState {
        pressed,
        started: pressed && matches!(action.phase, InputActionPhase::Started),
    }
}

fn canonical_action_name(action: &str) -> String {
    action
        .bytes()
        .filter(|byte| byte.is_ascii_alphanumeric())
        .map(|byte| byte.to_ascii_lowercase() as char)
        .collect()
}

fn validate_preview_field_path(field_path: &str) -> Result<()> {
    if field_path.is_empty() {
        anyhow::bail!("field_path must not be empty");
    }
    if field_path.len() > 160 {
        anyhow::bail!("field_path exceeds 160 bytes");
    }
    for segment in field_path.split('.') {
        if segment.is_empty() {
            anyhow::bail!("field_path contains an empty segment");
        }
        if !segment
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'-'))
        {
            anyhow::bail!("field_path segment '{}' is not portable", segment);
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::path::{Path, PathBuf};
    use std::time::{SystemTime, UNIX_EPOCH};

    use serde_json::Value;
    use xace_core::events::event_struct::Event;
    use xace_core::events::semantic_event_registry::{domain_event, INTERACTION_ACCEPTED};
    use xace_core::runtime::phase_enum::PhaseEnum;
    use xace_network_core::input::{InputAction, InputActionKind, InputActionPhase, InputPacket};

    use super::*;

    struct RefusedHotSwapClassification {
        report: RuntimeHotSwapCompatibilityReport,
        error: String,
    }

    fn input_json(packet: &InputPacket) -> Value {
        serde_json::from_str(&runtime_input_component_json(packet)).unwrap()
    }

    fn dev_config() -> RuntimeConfig {
        RuntimeConfig::development_with_cgs_derived_plan()
    }

    fn initialise_dev(cgs_path: &Path) -> RuntimeOrchestrator {
        RuntimeOrchestrator::initialise_with_config(cgs_path, dev_config()).unwrap()
    }

    fn classify_refused_hot_swap_candidate(
        old_hash_digit: &str,
        candidate_cgs: String,
        candidate_plan: String,
    ) -> RefusedHotSwapClassification {
        let old_hash = old_hash_digit.repeat(64);
        let candidate_value = serde_json::from_str::<Value>(&candidate_cgs).unwrap();
        let candidate_hash = candidate_value["metadata"]["cgs_hash"]
            .as_str()
            .unwrap()
            .to_string();
        let (root, cgs_path) =
            write_temp_project_cgs(cgs_hot_swap_runtime_systems(&old_hash, 1, false));
        write_runtime_plan(
            &root,
            &old_hash,
            runtime_plan_generated_counter_only(&old_hash, 1),
        );
        let config = RuntimeConfig {
            sgc_plan_policy: cgs_loader::SgcPlanPolicy::RequirePersisted,
            ..RuntimeConfig::default()
        };
        let mut runtime =
            RuntimeOrchestrator::initialise_with_config(&cgs_path, config.clone()).unwrap();
        runtime.tick().unwrap();

        std::fs::write(&cgs_path, candidate_cgs).unwrap();
        write_runtime_plan(&root, &candidate_hash, candidate_plan);
        let report = runtime
            .classify_hot_swap_cgs_at_tick_boundary(&cgs_path, config.clone())
            .unwrap();
        let error = runtime
            .hot_swap_cgs_at_tick_boundary(&cgs_path, config)
            .unwrap_err()
            .to_string();
        assert_eq!(runtime.status().tick, 1);
        assert_eq!(runtime.status().cgs_hash, old_hash);
        let _ = std::fs::remove_dir_all(root);
        RefusedHotSwapClassification { report, error }
    }

    fn assert_component_i64(
        runtime: &RuntimeOrchestrator,
        entity_id: u64,
        component_type_id: u32,
        field: &str,
        expected: i64,
    ) {
        let snapshot = runtime.world_snapshot().unwrap();
        let component_json = snapshot
            .component_tables_snapshot
            .get_table(component_type_id)
            .and_then(|table| table.get(entity_id))
            .unwrap_or_else(|| {
                panic!(
                    "missing component {} for entity {}",
                    component_type_id, entity_id
                )
            });
        let component = serde_json::from_str::<Value>(component_json).unwrap();
        assert_eq!(component[field].as_i64(), Some(expected));
    }

    fn assert_component_bool(
        runtime: &RuntimeOrchestrator,
        entity_id: u64,
        component_type_id: u32,
        field: &str,
        expected: bool,
    ) {
        let snapshot = runtime.world_snapshot().unwrap();
        let component_json = snapshot
            .component_tables_snapshot
            .get_table(component_type_id)
            .and_then(|table| table.get(entity_id))
            .unwrap_or_else(|| {
                panic!(
                    "missing component {} for entity {}",
                    component_type_id, entity_id
                )
            });
        let component = serde_json::from_str::<Value>(component_json).unwrap();
        assert_eq!(component[field].as_bool(), Some(expected));
    }

    fn assert_component_json_i64(
        components: &std::collections::BTreeMap<u32, String>,
        component_type_id: u32,
        field: &str,
        expected: i64,
    ) {
        let component = serde_json::from_str::<Value>(
            components
                .get(&component_type_id)
                .unwrap_or_else(|| panic!("missing component {}", component_type_id)),
        )
        .unwrap();
        assert_eq!(component[field].as_i64(), Some(expected));
    }

    fn assert_component_json_bool(
        components: &std::collections::BTreeMap<u32, String>,
        component_type_id: u32,
        field: &str,
        expected: bool,
    ) {
        let component = serde_json::from_str::<Value>(
            components
                .get(&component_type_id)
                .unwrap_or_else(|| panic!("missing component {}", component_type_id)),
        )
        .unwrap();
        assert_eq!(component[field].as_bool(), Some(expected));
    }

    #[test]
    fn semantic_playback_bindings_resolve_into_engine_snapshot_commands() {
        let path = write_temp_cgs(valid_cgs_with_semantic_bindings());
        let mut runtime = initialise_dev(&path);
        let event = Event::directed(
            1,
            2,
            domain_event(INTERACTION_ACCEPTED),
            0,
            PhaseEnum::Simulation,
        )
        .with_payload("actor_entity_id", "1")
        .with_payload("target_entity_id", "2")
        .with_payload("interaction_state", "accepted")
        .with_payload("interaction_type", "generic");

        let commands = runtime.playback_commands_for_events(&[event]);

        assert_eq!(commands.len(), 3);
        assert_eq!(commands[0].binding_id, "bind_anim");
        assert_eq!(commands[1].binding_id, "bind_audio");
        assert_eq!(commands[2].binding_id, "bind_vfx");
        for command in &commands {
            command.validate().unwrap();
        }

        runtime.last_playback_commands = commands;
        let snapshot = runtime.control_snapshot();
        assert_eq!(snapshot.playback_commands.len(), 3);
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn runtime_tick_records_world_hash_in_status() {
        let path = write_temp_cgs(valid_cgs_with_semantic_bindings());
        let mut runtime = initialise_dev(&path);

        let result = runtime.tick().unwrap();
        let status = runtime.status();

        assert_eq!(result.world_hash.len(), 64);
        assert_eq!(status.latest_world_hash, result.world_hash);
        assert_eq!(status.hash_log.len(), 1);
        assert_eq!(status.hash_log[0].tick, 0);
        assert_eq!(
            runtime.world_hash_at_tick(0),
            Some(status.hash_log[0].world_hash.as_str())
        );
        assert_eq!(
            runtime.last_tick_result().unwrap().world_hash,
            status.latest_world_hash
        );
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn replay_record_and_validate_compares_live_rerun_hashes() {
        let path = write_temp_cgs(valid_cgs_with_semantic_bindings());
        let mut runtime = initialise_dev(&path);

        runtime.tick().unwrap();
        runtime.tick().unwrap();
        let recorded = runtime.record_replay_hash_log().unwrap();
        let report = runtime
            .validate_recorded_replay_from_cgs(&path, dev_config())
            .unwrap();

        assert_eq!(recorded, 2);
        assert!(report.passed);
        assert_eq!(report.compared_ticks, 2);
        assert_eq!(report.first_mismatch, None);
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn replay_validate_requires_recorded_hash_log() {
        let path = write_temp_cgs(valid_cgs_with_semantic_bindings());
        let runtime = initialise_dev(&path);

        let result = runtime.validate_recorded_replay_from_cgs(&path, dev_config());

        assert!(result.is_err());
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn replay_corruption_injection_reports_first_mismatched_tick() {
        let path = write_temp_cgs(valid_cgs_with_semantic_bindings());
        let mut runtime = initialise_dev(&path);

        runtime.tick().unwrap();
        runtime.tick().unwrap();
        runtime.record_replay_hash_log().unwrap();
        runtime
            .replay_golden_log
            .as_mut()
            .unwrap()
            .entries
            .insert(1, "f".repeat(64));

        let report = runtime
            .validate_recorded_replay_from_cgs(&path, dev_config())
            .unwrap();

        assert!(!report.passed);
        let mismatch = report.first_mismatch.unwrap();
        assert_eq!(mismatch.tick, 1);
        assert_eq!(mismatch.expected_hash, "f".repeat(64));
        assert_eq!(mismatch.actual_hash.len(), 64);
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn x10_015_replay_divergence_diagnosis_identifies_generated_tick_evidence() {
        let hash = "5".repeat(64);
        let (root, cgs_path) =
            write_temp_project_cgs(cgs_with_two_generated_runtime_systems(&hash));
        write_runtime_plan(&root, &hash, runtime_plan_two_generated(&hash));
        let config = RuntimeConfig {
            sgc_plan_policy: cgs_loader::SgcPlanPolicy::RequirePersisted,
            ..RuntimeConfig::default()
        };
        let mut runtime =
            RuntimeOrchestrator::initialise_with_config(&cgs_path, config.clone()).unwrap();

        runtime.tick().unwrap();
        runtime.record_replay_hash_log().unwrap();
        runtime
            .replay_golden_log
            .as_mut()
            .unwrap()
            .entries
            .insert(0, "0".repeat(64));

        let report = runtime
            .validate_recorded_replay_from_cgs(&cgs_path, config)
            .unwrap();

        assert!(!report.passed);
        let mismatch = report.first_mismatch.unwrap();
        assert_eq!(mismatch.tick, 0);
        let diagnosis = mismatch.diagnosis;
        assert!(diagnosis.summary.contains("SGC group"));
        assert!(diagnosis.summary.contains("GeneratedCounterSystem"));
        assert!(diagnosis.summary.contains("GeneratedLootRollSystem"));
        assert!(diagnosis.summary.contains("COMP_COUNTER_V1"));
        assert!(diagnosis.summary.contains("generated.loot_roll"));
        assert!(diagnosis.summary.contains("RNG"));
        assert_eq!(
            diagnosis.suspected_sgc_group.as_ref().unwrap().group_id,
            "Simulation_group_0"
        );
        assert!(diagnosis
            .candidate_systems
            .contains(&"GeneratedCounterSystem".to_string()));
        assert!(diagnosis
            .component_changes
            .iter()
            .any(|component| component.component_type_id == 300
                && component.operation == "update_component"
                && component.field_names == vec!["count".to_string()]));
        assert!(diagnosis
            .emitted_events
            .iter()
            .any(|event| event.event_type.contains("generated.loot_roll")));
        assert!(diagnosis
            .rng_calls
            .iter()
            .any(|rng| rng.system_id == "GeneratedLootRollSystem"
                && rng.deterministic
                && rng.seed.is_some()));
        assert_eq!(diagnosis.mutation.mutations_applied, 1);
        assert_eq!(diagnosis.mutation.updated_components, 1);
        assert!(diagnosis.input_packets.is_empty());
        assert!(diagnosis.expected_trace.is_some());
        assert!(diagnosis.actual_trace.is_some());
        let readable_report = format!("{:#?}", diagnosis);
        assert!(readable_report.contains("RuntimeReplayDivergenceDiagnosis"));
        assert!(readable_report.contains("Simulation_group_0"));
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn x10_015_replay_divergence_diagnosis_identifies_input_packet() {
        let path = write_temp_cgs(valid_cgs_with_semantic_bindings());
        let mut runtime = initialise_dev(&path);
        let player_id = runtime.spawn_summary().spawned_actors[0].entity_ids[0];
        runtime.engine_inputs.push(
            InputPacket::with_actions(77, 0, 1, vec![InputAction::button("Attack", true)])
                .with_player(player_id)
                .with_device("keyboard"),
        );

        runtime.tick().unwrap();
        runtime.record_replay_hash_log().unwrap();
        let report = runtime
            .validate_recorded_replay_from_cgs(&path, dev_config())
            .unwrap();

        assert!(!report.passed);
        let diagnosis = report.first_mismatch.unwrap().diagnosis;
        assert_eq!(diagnosis.tick, 0);
        assert_eq!(diagnosis.input_packets.len(), 1);
        let packet = &diagnosis.input_packets[0];
        assert_eq!(packet.peer_id, 77);
        assert_eq!(packet.sequence_id, 1);
        assert_eq!(packet.player_id, Some(player_id));
        assert_eq!(packet.action_names, vec!["Attack".to_string()]);
        assert!(packet.applied);
        assert_eq!(packet.status, "applied");
        assert!(diagnosis.summary.contains("peer=77"));
        assert!(diagnosis.summary.contains("Attack"));
        assert_eq!(
            diagnosis
                .expected_trace
                .as_ref()
                .unwrap()
                .input_packets
                .len(),
            1
        );
        assert!(diagnosis
            .actual_trace
            .as_ref()
            .unwrap()
            .input_packets
            .is_empty());
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn default_runtime_config_refuses_missing_sgc_plan_before_tick_zero() {
        let (root, cgs_path) =
            write_temp_project_cgs(cgs_with_runtime_systems(&"a".repeat(64), 1, false));

        let result = RuntimeOrchestrator::initialise(&cgs_path);

        assert!(result.is_err());
        let err = result.err().unwrap();
        assert!(err
            .to_string()
            .contains("SGC execution plan required but missing"));
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn strict_sgc_plan_policy_refuses_missing_plan_before_tick_zero() {
        let (root, cgs_path) =
            write_temp_project_cgs(cgs_with_runtime_systems(&"a".repeat(64), 1, false));
        let config = RuntimeConfig {
            sgc_plan_policy: cgs_loader::SgcPlanPolicy::RequirePersisted,
            ..RuntimeConfig::default()
        };

        let result = RuntimeOrchestrator::initialise_with_config(&cgs_path, config);

        assert!(result.is_err());
        let err = result.err().unwrap();
        assert!(err
            .to_string()
            .contains("SGC execution plan required but missing"));
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn runtime_uses_persisted_sgc_plan_as_authoritative_schedule() {
        let hash = "b".repeat(64);
        let (root, cgs_path) = write_temp_project_cgs(cgs_with_runtime_systems(&hash, 7, false));
        write_runtime_plan(&root, &hash, runtime_plan(&hash, 7, false));
        let config = RuntimeConfig {
            sgc_plan_policy: cgs_loader::SgcPlanPolicy::RequirePersisted,
            ..RuntimeConfig::default()
        };

        let mut runtime = RuntimeOrchestrator::initialise_with_config(&cgs_path, config).unwrap();
        let status = runtime.status();

        assert_eq!(
            runtime.spawn_summary().phase_plan_source,
            cgs_loader::RuntimePhasePlanSource::PersistedSgc
        );
        assert_eq!(status.execution_plan_version, "7");
        assert_eq!(
            runtime.phase_plan(),
            &vec![(
                "Simulation".to_string(),
                vec!["MovementSystem".to_string()],
                false
            )]
        );
        let tick = runtime.tick().unwrap();
        assert_eq!(tick.tick, 0);
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn runtime_rejects_unregistered_sgc_plan_system_before_tick_zero() {
        let hash = "c".repeat(64);
        let (root, cgs_path) = write_temp_project_cgs(cgs_with_runtime_systems(&hash, 1, true));
        write_runtime_plan(&root, &hash, runtime_plan(&hash, 1, true));
        let config = RuntimeConfig {
            sgc_plan_policy: cgs_loader::SgcPlanPolicy::RequirePersisted,
            ..RuntimeConfig::default()
        };

        let result = RuntimeOrchestrator::initialise_with_config(&cgs_path, config);

        assert!(result.is_err());
        let err = result.err().unwrap();
        assert!(err.to_string().contains("CustomGeneratedSystem"));
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn runtime_executes_supported_generated_system_through_registry() {
        let hash = "4".repeat(64);
        let (root, cgs_path) =
            write_temp_project_cgs(cgs_with_generated_counter_runtime_system(&hash));
        let config = RuntimeConfig {
            sgc_plan_policy: cgs_loader::SgcPlanPolicy::DeriveFromCgs,
            ..RuntimeConfig::default()
        };

        let mut runtime = RuntimeOrchestrator::initialise_with_config(&cgs_path, config).unwrap();

        assert!(runtime.registry.has_system("GeneratedCounterSystem"));
        assert_eq!(
            runtime.phase_plan(),
            &vec![(
                "Simulation".to_string(),
                vec!["GeneratedCounterSystem".to_string()],
                false
            )]
        );
        let tick = runtime.tick().unwrap();
        assert_eq!(tick.mutations_applied, 1);
        let entity_id = runtime.spawn_summary().spawned_actors[0].entity_ids[0];
        let snapshot = runtime.world_snapshot().unwrap();
        let counter_json = snapshot
            .component_tables_snapshot
            .get_table(300)
            .and_then(|table| table.get(entity_id))
            .unwrap();
        let counter = serde_json::from_str::<Value>(counter_json).unwrap();
        assert_eq!(counter["count"].as_i64(), Some(1_000_000));
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn runtime_executes_multiple_generated_systems_through_abi() {
        let hash = "5".repeat(64);
        let (root, cgs_path) =
            write_temp_project_cgs(cgs_with_two_generated_runtime_systems(&hash));
        let config = RuntimeConfig {
            sgc_plan_policy: cgs_loader::SgcPlanPolicy::DeriveFromCgs,
            ..RuntimeConfig::default()
        };

        let mut runtime = RuntimeOrchestrator::initialise_with_config(&cgs_path, config).unwrap();

        assert!(runtime.registry.has_system("GeneratedCounterSystem"));
        assert!(runtime.registry.has_system("GeneratedLootRollSystem"));
        assert_eq!(
            runtime.phase_plan(),
            &vec![(
                "Simulation".to_string(),
                vec![
                    "GeneratedCounterSystem".to_string(),
                    "GeneratedLootRollSystem".to_string()
                ],
                false
            )]
        );
        let tick = runtime.tick().unwrap();
        assert_eq!(tick.mutations_applied, 1);
        assert_eq!(tick.emitted_events.len(), 1);
        assert_eq!(tick.events_dispatched, 1);
        assert_eq!(
            tick.emitted_events[0].event_type.name(),
            "Domain(generated.loot_roll)"
        );
        assert_eq!(
            tick.emitted_events[0]
                .payload
                .get("source")
                .map(String::as_str),
            Some("generated")
        );

        let counter_entity_id = runtime.spawn_summary().spawned_actors[0].entity_ids[0];
        let snapshot = runtime.world_snapshot().unwrap();
        let counter_json = snapshot
            .component_tables_snapshot
            .get_table(300)
            .and_then(|table| table.get(counter_entity_id))
            .unwrap();
        let counter = serde_json::from_str::<Value>(counter_json).unwrap();
        assert_eq!(counter["count"].as_i64(), Some(1_000_000));
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn persisted_sgc_schedule_snapshots_match_plan_for_generated_replay() {
        let hash = "6".repeat(64);
        let (root, cgs_path) =
            write_temp_project_cgs(cgs_with_two_generated_runtime_systems(&hash));
        write_runtime_plan(&root, &hash, runtime_plan_two_generated(&hash));
        let config = RuntimeConfig {
            sgc_plan_policy: cgs_loader::SgcPlanPolicy::RequirePersisted,
            ..RuntimeConfig::default()
        };

        let mut runtime =
            RuntimeOrchestrator::initialise_with_config(&cgs_path, config.clone()).unwrap();

        assert_eq!(
            runtime.spawn_summary().phase_plan_source,
            cgs_loader::RuntimePhasePlanSource::PersistedSgc
        );
        assert_eq!(runtime.schedule_plan().groups.len(), 1);
        let group = &runtime.schedule_plan().groups[0];
        assert_eq!(group.group_id, "Simulation_group_0");
        assert!(group.parallel);
        assert_eq!(
            group.systems,
            vec![
                "GeneratedCounterSystem".to_string(),
                "GeneratedLootRollSystem".to_string()
            ]
        );
        assert_eq!(
            group.component_access["GeneratedCounterSystem"].writes,
            vec![300]
        );
        assert_eq!(
            group.component_access["GeneratedLootRollSystem"].reads,
            vec![301]
        );

        runtime.tick().unwrap();
        runtime.tick().unwrap();
        assert_eq!(runtime.schedule_snapshots().len(), 2);
        assert_eq!(
            runtime.schedule_snapshots()[0],
            runtime.schedule_plan().snapshot_for_tick(0)
        );
        assert_eq!(
            runtime.schedule_snapshots()[1],
            runtime.schedule_plan().snapshot_for_tick(1)
        );

        runtime.record_replay_hash_log().unwrap();
        let report = runtime
            .validate_recorded_replay_from_cgs(&cgs_path, config)
            .unwrap();

        assert!(report.passed);
        assert_eq!(report.compared_ticks, 2);
        assert_eq!(report.schedule_snapshots_compared, 2);
        assert_eq!(report.first_mismatch, None);
        assert_eq!(report.first_schedule_mismatch, None);
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn runtime_tick_rejects_schedule_plan_hash_drift_before_execution() {
        let hash = "8".repeat(64);
        let (root, cgs_path) =
            write_temp_project_cgs(cgs_with_two_generated_runtime_systems(&hash));
        write_runtime_plan(&root, &hash, runtime_plan_two_generated(&hash));
        let config = RuntimeConfig {
            sgc_plan_policy: cgs_loader::SgcPlanPolicy::RequirePersisted,
            ..RuntimeConfig::default()
        };
        let mut runtime = RuntimeOrchestrator::initialise_with_config(&cgs_path, config).unwrap();
        runtime.schedule_plan.plan_hash = "0".repeat(64);

        let err = runtime
            .tick()
            .expect_err("tick must fail before executing a drifted schedule");

        assert!(err
            .to_string()
            .contains("Runtime schedule identity drift before tick 0"));
        assert!(err.to_string().contains("plan_hash drift"));
        assert_eq!(runtime.status().tick, 0);
        assert!(runtime.schedule_snapshots().is_empty());
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn replay_rejects_recorded_schedule_group_order_drift_at_first_bad_tick() {
        let hash = "9".repeat(64);
        let (root, cgs_path) =
            write_temp_project_cgs(cgs_with_two_generated_runtime_systems(&hash));
        write_runtime_plan(&root, &hash, runtime_plan_two_generated(&hash));
        let config = RuntimeConfig {
            sgc_plan_policy: cgs_loader::SgcPlanPolicy::RequirePersisted,
            ..RuntimeConfig::default()
        };
        let mut runtime =
            RuntimeOrchestrator::initialise_with_config(&cgs_path, config.clone()).unwrap();
        runtime.tick().unwrap();
        runtime.tick().unwrap();
        runtime.record_replay_hash_log().unwrap();
        runtime.schedule_snapshots[1].groups[0].systems.swap(0, 1);

        let report = runtime
            .validate_recorded_replay_from_cgs(&cgs_path, config)
            .unwrap();

        assert!(!report.passed);
        assert_eq!(report.first_mismatch, None);
        assert_eq!(report.compared_ticks, 2);
        assert_eq!(report.schedule_snapshots_compared, 1);
        let mismatch = report.first_schedule_mismatch.unwrap();
        assert_eq!(mismatch.tick, 1);
        assert!(mismatch.actual.is_some());
        assert_eq!(
            mismatch.expected.scheduled_system_ids,
            vec![
                "GeneratedCounterSystem".to_string(),
                "GeneratedLootRollSystem".to_string()
            ]
        );
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn persisted_sgc_executes_generated_plugin_external_registry_contract() {
        let hash = "7".repeat(64);
        let (root, cgs_path) =
            write_temp_project_cgs(cgs_with_generated_plugin_external_runtime_systems(&hash));
        write_runtime_plan(&root, &hash, runtime_plan_generated_plugin_external(&hash));
        let config = RuntimeConfig {
            sgc_plan_policy: cgs_loader::SgcPlanPolicy::RequirePersisted,
            ..RuntimeConfig::default()
        };

        let mut runtime =
            RuntimeOrchestrator::initialise_with_config(&cgs_path, config.clone()).unwrap();

        assert!(runtime.registry.has_system("GeneratedCounterSystem"));
        assert!(runtime.registry.has_system("PluginWeatherSystem"));
        assert!(runtime.registry.has_system("ExternalMirrorSystem"));
        assert_eq!(runtime.schedule_plan().groups.len(), 1);
        assert!(runtime.schedule_plan().groups[0].parallel);
        assert_eq!(
            runtime.schedule_plan().groups[0].systems,
            vec![
                "ExternalMirrorSystem".to_string(),
                "GeneratedCounterSystem".to_string(),
                "PluginWeatherSystem".to_string()
            ]
        );

        let first = runtime.tick().unwrap();
        assert_eq!(first.mutations_applied, 3);
        let entity_id = runtime.spawn_summary().spawned_actors[0].entity_ids[0];
        assert_component_i64(&runtime, entity_id, 300, "count", 1_000_000);
        assert_component_bool(&runtime, entity_id, 700, "active", true);
        assert_component_i64(&runtime, entity_id, 702, "mirrored_power", 5_000_000);

        let adapter_snapshot = runtime.control_snapshot();
        let adapter_entity = adapter_snapshot
            .entities
            .iter()
            .find(|entity| entity.id == entity_id)
            .expect("adapter snapshot should include executor-mutated entity");
        assert_component_json_i64(&adapter_entity.components, 300, "count", 1_000_000);
        assert_component_json_bool(&adapter_entity.components, 700, "active", true);
        assert_component_json_i64(&adapter_entity.components, 702, "mirrored_power", 5_000_000);

        let rollback_snapshot = runtime.world_snapshot().unwrap();
        let second = runtime.tick().unwrap();
        assert_eq!(second.mutations_applied, 3);
        assert_component_i64(&runtime, entity_id, 300, "count", 2_000_000);
        assert_eq!(runtime.schedule_snapshots().len(), 2);

        runtime.record_replay_hash_log().unwrap();
        let replay = runtime
            .validate_recorded_replay_from_cgs(&cgs_path, config)
            .unwrap();
        assert!(replay.passed);
        assert_eq!(replay.compared_ticks, 2);
        assert_eq!(replay.schedule_snapshots_compared, 2);

        runtime.restore_world_snapshot(&rollback_snapshot).unwrap();
        assert_component_i64(&runtime, entity_id, 300, "count", 1_000_000);
        let replayed_second = runtime.tick().unwrap();
        assert_eq!(replayed_second.world_hash, second.world_hash);
        assert_component_i64(&runtime, entity_id, 300, "count", 2_000_000);
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn x10_020_hot_swap_preserves_state_and_activates_new_systems() {
        let old_hash = "7".repeat(64);
        let new_hash = "8".repeat(64);
        let (root, cgs_path) =
            write_temp_project_cgs(cgs_hot_swap_runtime_systems(&old_hash, 1, false));
        write_runtime_plan(
            &root,
            &old_hash,
            runtime_plan_generated_counter_only(&old_hash, 1),
        );
        let config = RuntimeConfig {
            sgc_plan_policy: cgs_loader::SgcPlanPolicy::RequirePersisted,
            ..RuntimeConfig::default()
        };

        let mut runtime =
            RuntimeOrchestrator::initialise_with_config(&cgs_path, config.clone()).unwrap();
        let entity_id = runtime.spawn_summary().spawned_actors[0].entity_ids[0];

        runtime.tick().unwrap();
        runtime.tick().unwrap();
        let pre_swap_snapshot = runtime.world_snapshot().unwrap();
        assert_eq!(runtime.status().tick, 2);
        assert_eq!(runtime.status().cgs_hash, old_hash);
        assert_eq!(runtime.hash_log().len(), 2);
        assert_component_i64(&runtime, entity_id, 300, "count", 2_000_000);
        assert_component_bool(&runtime, entity_id, 700, "active", false);
        assert_component_i64(&runtime, entity_id, 702, "mirrored_power", 0);

        std::fs::write(&cgs_path, cgs_hot_swap_runtime_systems(&new_hash, 2, true)).unwrap();
        write_runtime_plan(
            &root,
            &new_hash,
            runtime_plan_generated_plugin_external_with_version(&new_hash, 2),
        );

        let report = runtime
            .hot_swap_cgs_at_tick_boundary(&cgs_path, config)
            .unwrap();
        assert_eq!(report.schema, "xace.runtime.hot_swap_report.v1");
        assert_eq!(
            report.compatibility.overall_class,
            RuntimeHotSwapCompatibilityClass::Additive
        );
        assert!(report.compatibility.live_compatible);
        assert_eq!(report.previous_cgs_hash, old_hash);
        assert_eq!(report.new_cgs_hash, new_hash);
        assert_eq!(report.previous_execution_plan_version, 1);
        assert_eq!(report.new_execution_plan_version, 2);
        assert_eq!(report.requested_tick, 2);
        assert_eq!(report.applied_tick, 2);
        assert!(report.safe_tick_boundary);
        assert_eq!(report.preserved_entity_ids, vec![entity_id]);
        assert_eq!(report.preserved_component_rows, 4);
        assert_eq!(
            report.previous_system_ids,
            vec!["GeneratedCounterSystem".to_string()]
        );
        assert_eq!(
            report.newly_active_system_ids,
            vec![
                "ExternalMirrorSystem".to_string(),
                "PluginWeatherSystem".to_string()
            ]
        );

        let post_swap_status = runtime.status();
        assert_eq!(post_swap_status.tick, 2);
        assert_eq!(post_swap_status.cgs_hash, new_hash);
        assert_eq!(post_swap_status.execution_plan_version, "2");
        assert!(runtime.entity_is_alive(entity_id));
        assert_eq!(runtime.hash_log().len(), 2);
        let post_swap_snapshot = runtime.world_snapshot().unwrap();
        assert_eq!(
            post_swap_snapshot.entity_store_snapshot,
            pre_swap_snapshot.entity_store_snapshot
        );
        assert_eq!(
            post_swap_snapshot.component_tables_snapshot,
            pre_swap_snapshot.component_tables_snapshot
        );
        assert_component_i64(&runtime, entity_id, 300, "count", 2_000_000);
        assert_component_bool(&runtime, entity_id, 700, "active", false);
        assert_component_i64(&runtime, entity_id, 702, "mirrored_power", 0);

        let tick_after_swap = runtime.tick().unwrap();
        assert_eq!(tick_after_swap.tick, 2);
        assert_eq!(tick_after_swap.mutations_applied, 3);
        assert_eq!(runtime.status().tick, 3);
        assert_eq!(runtime.hash_log().len(), 3);
        assert_component_i64(&runtime, entity_id, 300, "count", 3_000_000);
        assert_component_bool(&runtime, entity_id, 700, "active", true);
        assert_component_i64(&runtime, entity_id, 702, "mirrored_power", 5_000_000);
        let schedule = runtime.last_schedule_snapshot().unwrap();
        assert_eq!(schedule.tick, 2);
        assert_eq!(schedule.cgs_hash, new_hash);
        assert_eq!(schedule.plan_version, 2);
        assert_eq!(
            schedule.scheduled_system_ids,
            vec![
                "ExternalMirrorSystem".to_string(),
                "GeneratedCounterSystem".to_string(),
                "PluginWeatherSystem".to_string()
            ]
        );
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn x10_021_additive_empty_component_table_hot_swap_is_allowed() {
        let old_hash = "9".repeat(64);
        let new_hash = "a".repeat(64);
        let (root, cgs_path) =
            write_temp_project_cgs(cgs_hot_swap_runtime_systems(&old_hash, 1, false));
        write_runtime_plan(
            &root,
            &old_hash,
            runtime_plan_generated_counter_only(&old_hash, 1),
        );
        let config = RuntimeConfig {
            sgc_plan_policy: cgs_loader::SgcPlanPolicy::RequirePersisted,
            ..RuntimeConfig::default()
        };
        let mut runtime =
            RuntimeOrchestrator::initialise_with_config(&cgs_path, config.clone()).unwrap();
        runtime.tick().unwrap();

        std::fs::write(
            &cgs_path,
            cgs_with_added_empty_component_table(&new_hash, 2, 703),
        )
        .unwrap();
        write_runtime_plan(
            &root,
            &new_hash,
            runtime_plan_generated_counter_only(&new_hash, 2),
        );

        let compatibility = runtime
            .classify_hot_swap_cgs_at_tick_boundary(&cgs_path, config.clone())
            .unwrap();
        assert_eq!(
            compatibility.overall_class,
            RuntimeHotSwapCompatibilityClass::Additive
        );
        assert!(compatibility.live_compatible);
        assert_eq!(compatibility.added_component_tables, vec![703]);
        assert!(compatibility
            .issues
            .iter()
            .any(|issue| issue.code == "component_table_added_empty"));

        let report = runtime
            .hot_swap_cgs_at_tick_boundary(&cgs_path, config)
            .unwrap();
        assert_eq!(report.applied_tick, 1);
        assert_eq!(report.added_component_tables, vec![703]);
        assert_eq!(
            report.compatibility.overall_class,
            RuntimeHotSwapCompatibilityClass::Additive
        );
        assert_eq!(runtime.status().tick, 1);
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn x10_021_incompatible_hot_swap_classes_are_refused_before_live_swap() {
        let migratable = classify_refused_hot_swap_candidate(
            "b",
            cgs_with_added_actor_component_backfill_requirement(&"c".repeat(64), 2, 704),
            runtime_plan_generated_counter_only(&"c".repeat(64), 2),
        );
        assert_eq!(
            migratable.report.overall_class,
            RuntimeHotSwapCompatibilityClass::Migratable
        );
        assert!(!migratable.report.live_compatible);
        assert!(migratable.report.migration_required);
        assert_eq!(migratable.report.backfill_component_tables, vec![704]);
        assert!(migratable.error.contains("compatibility_class=migratable"));
        assert!(migratable
            .error
            .contains("component_added_requires_backfill"));

        let state_transforming = classify_refused_hot_swap_candidate(
            "d",
            cgs_with_counter_amount(&"e".repeat(64), 2, 2),
            runtime_plan_generated_counter_only(&"e".repeat(64), 2),
        );
        assert_eq!(
            state_transforming.report.overall_class,
            RuntimeHotSwapCompatibilityClass::StateTransforming
        );
        assert!(!state_transforming.report.live_compatible);
        assert_eq!(
            state_transforming.report.changed_system_ids,
            vec!["GeneratedCounterSystem".to_string()]
        );
        assert!(state_transforming
            .error
            .contains("compatibility_class=state_transforming"));
        assert!(state_transforming.error.contains("system_contract_changed"));

        let reset_required = classify_refused_hot_swap_candidate(
            "f",
            cgs_with_spawn_count(&"1".repeat(64), 2, 2),
            runtime_plan_generated_counter_only(&"1".repeat(64), 2),
        );
        assert_eq!(
            reset_required.report.overall_class,
            RuntimeHotSwapCompatibilityClass::ResetRequired
        );
        assert!(!reset_required.report.live_compatible);
        assert!(reset_required.report.reset_required);
        assert!(reset_required
            .error
            .contains("compatibility_class=reset_required"));
        assert!(reset_required.error.contains("actor_topology_changed"));
    }

    #[test]
    fn x10_022_runtime_state_migration_hooks_backfill_multiple_component_versions() {
        let v1_hash = "2".repeat(64);
        let v2_hash = "3".repeat(64);
        let v3_hash = "4".repeat(64);
        let (root, cgs_path) =
            write_temp_project_cgs(cgs_hot_swap_runtime_systems(&v1_hash, 1, false));
        write_runtime_plan(
            &root,
            &v1_hash,
            runtime_plan_generated_counter_only(&v1_hash, 1),
        );
        let config = RuntimeConfig {
            sgc_plan_policy: cgs_loader::SgcPlanPolicy::RequirePersisted,
            ..RuntimeConfig::default()
        };
        let mut runtime =
            RuntimeOrchestrator::initialise_with_config(&cgs_path, config.clone()).unwrap();
        let entity_id = runtime.spawn_summary().spawned_actors[0].entity_ids[0];
        runtime.tick().unwrap();
        let pre_v2_snapshot = runtime.world_snapshot().unwrap();
        assert!(pre_v2_snapshot
            .component_tables_snapshot
            .get_table(704)
            .is_none());

        runtime
            .register_component_migration_hook(
                RuntimeComponentMigrationHook::backfill_from_candidate_defaults(
                    "backfill_704_0_1_to_0_2",
                    "0.1.0",
                    "0.2.0",
                    704,
                ),
            )
            .unwrap();
        std::fs::write(
            &cgs_path,
            cgs_with_actor_component_backfill_versions(&v2_hash, 2, "0.2.0", &[(704, 100)]),
        )
        .unwrap();
        write_runtime_plan(
            &root,
            &v2_hash,
            runtime_plan_generated_counter_only_with_schema(&v2_hash, 2, "0.2.0"),
        );

        let v2_compatibility = runtime
            .classify_hot_swap_cgs_at_tick_boundary(&cgs_path, config.clone())
            .unwrap();
        assert_eq!(
            v2_compatibility.overall_class,
            RuntimeHotSwapCompatibilityClass::Migratable
        );
        assert!(v2_compatibility.migration_required);
        assert_eq!(v2_compatibility.backfill_component_tables, vec![704]);
        let v2_report = runtime
            .hot_swap_cgs_at_tick_boundary(&cgs_path, config.clone())
            .unwrap();
        let v2_migration = v2_report.migration.as_ref().unwrap();
        assert_eq!(
            v2_migration.schema,
            "xace.runtime.hot_swap_migration_report.v1"
        );
        assert_eq!(v2_migration.from_schema_version, "0.1.0");
        assert_eq!(v2_migration.to_schema_version, "0.2.0");
        assert_eq!(v2_migration.old_world_hash, pre_v2_snapshot.world_hash);
        assert_eq!(v2_migration.migrated_world_hash.len(), 64);
        assert_ne!(
            v2_migration.old_world_hash,
            v2_migration.migrated_world_hash
        );
        assert_eq!(v2_migration.records.len(), 1);
        assert_eq!(v2_migration.records[0].hook_id, "backfill_704_0_1_to_0_2");
        assert_eq!(v2_migration.records[0].component_type_id, 704);
        assert_eq!(v2_migration.records[0].entity_ids, vec![entity_id]);
        assert_eq!(v2_migration.records[0].rows_written, 1);
        assert_eq!(v2_migration.records[0].old_component_hash.len(), 64);
        assert_eq!(v2_migration.records[0].new_component_hash.len(), 64);
        assert_ne!(
            v2_migration.records[0].old_component_hash,
            v2_migration.records[0].new_component_hash
        );
        assert_eq!(runtime.migration_log().len(), 1);
        assert_eq!(runtime.status().schema_version, "0.2.0");
        assert_component_i64(&runtime, entity_id, 704, "value", 100);

        let pre_v3_snapshot = runtime.world_snapshot().unwrap();
        runtime
            .register_component_migration_hook(
                RuntimeComponentMigrationHook::backfill_from_candidate_defaults(
                    "backfill_705_0_2_to_0_3",
                    "0.2.0",
                    "0.3.0",
                    705,
                ),
            )
            .unwrap();
        std::fs::write(
            &cgs_path,
            cgs_with_actor_component_backfill_versions(
                &v3_hash,
                3,
                "0.3.0",
                &[(704, 100), (705, 200)],
            ),
        )
        .unwrap();
        write_runtime_plan(
            &root,
            &v3_hash,
            runtime_plan_generated_counter_only_with_schema(&v3_hash, 3, "0.3.0"),
        );

        let v3_report = runtime
            .hot_swap_cgs_at_tick_boundary(&cgs_path, config.clone())
            .unwrap();
        let v3_migration = v3_report.migration.as_ref().unwrap();
        assert_eq!(v3_migration.from_schema_version, "0.2.0");
        assert_eq!(v3_migration.to_schema_version, "0.3.0");
        assert_eq!(v3_migration.old_world_hash, pre_v3_snapshot.world_hash);
        assert_eq!(v3_migration.records.len(), 1);
        assert_eq!(v3_migration.records[0].hook_id, "backfill_705_0_2_to_0_3");
        assert_eq!(v3_migration.records[0].component_type_id, 705);
        assert_eq!(v3_migration.records[0].entity_ids, vec![entity_id]);
        assert_eq!(runtime.migration_log().len(), 2);
        assert_eq!(runtime.status().schema_version, "0.3.0");
        assert_component_i64(&runtime, entity_id, 704, "value", 100);
        assert_component_i64(&runtime, entity_id, 705, "value", 200);

        let post_migration_tick = runtime.tick().unwrap();
        assert_eq!(post_migration_tick.tick, 1);
        assert_eq!(runtime.status().tick, 2);
        assert_component_i64(&runtime, entity_id, 300, "count", 2_000_000);
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn x10_022_missing_migration_hook_refuses_without_state_mutation() {
        let old_hash = "5".repeat(64);
        let new_hash = "6".repeat(64);
        let (root, cgs_path) =
            write_temp_project_cgs(cgs_hot_swap_runtime_systems(&old_hash, 1, false));
        write_runtime_plan(
            &root,
            &old_hash,
            runtime_plan_generated_counter_only(&old_hash, 1),
        );
        let config = RuntimeConfig {
            sgc_plan_policy: cgs_loader::SgcPlanPolicy::RequirePersisted,
            ..RuntimeConfig::default()
        };
        let mut runtime =
            RuntimeOrchestrator::initialise_with_config(&cgs_path, config.clone()).unwrap();
        runtime.tick().unwrap();
        let pre_swap_snapshot = runtime.world_snapshot().unwrap();

        std::fs::write(
            &cgs_path,
            cgs_with_actor_component_backfill_versions(&new_hash, 2, "0.2.0", &[(704, 100)]),
        )
        .unwrap();
        write_runtime_plan(
            &root,
            &new_hash,
            runtime_plan_generated_counter_only_with_schema(&new_hash, 2, "0.2.0"),
        );

        let compatibility = runtime
            .classify_hot_swap_cgs_at_tick_boundary(&cgs_path, config.clone())
            .unwrap();
        assert_eq!(
            compatibility.overall_class,
            RuntimeHotSwapCompatibilityClass::Migratable
        );
        assert_eq!(compatibility.backfill_component_tables, vec![704]);
        let error = runtime
            .hot_swap_cgs_at_tick_boundary(&cgs_path, config)
            .unwrap_err()
            .to_string();
        assert!(error.contains("missing_migration_hook"));
        assert!(error.contains("component_added_requires_backfill"));
        assert_eq!(runtime.status().cgs_hash, old_hash);
        assert_eq!(runtime.status().schema_version, "0.1.0");
        assert!(runtime.migration_log().is_empty());
        let post_swap_snapshot = runtime.world_snapshot().unwrap();
        assert_eq!(
            post_swap_snapshot.entity_store_snapshot,
            pre_swap_snapshot.entity_store_snapshot
        );
        assert_eq!(
            post_swap_snapshot.component_tables_snapshot,
            pre_swap_snapshot.component_tables_snapshot
        );
        assert!(post_swap_snapshot
            .component_tables_snapshot
            .get_table(704)
            .is_none());
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn x10_012_clean_snapshot_restore_replay_matches_original_timeline() {
        let hash = "8".repeat(64);
        let (root, cgs_path) =
            write_temp_project_cgs(cgs_with_generated_plugin_external_runtime_systems(&hash));
        write_runtime_plan(&root, &hash, runtime_plan_generated_plugin_external(&hash));
        let config = RuntimeConfig {
            sgc_plan_policy: cgs_loader::SgcPlanPolicy::RequirePersisted,
            ..RuntimeConfig::default()
        };

        let mut runtime = RuntimeOrchestrator::initialise_with_config(&cgs_path, config).unwrap();

        runtime.tick().unwrap();
        let rollback_snapshot = runtime.world_snapshot().unwrap();
        assert!(rollback_snapshot.is_clean);
        assert!(!rollback_snapshot.has_pending_events());
        assert!(!rollback_snapshot.has_pending_mutations());
        assert!(rollback_snapshot.rng_state.stream_positions.is_empty());

        let second = runtime.tick().unwrap();
        let third = runtime.tick().unwrap();

        runtime.restore_world_snapshot(&rollback_snapshot).unwrap();
        let replayed_second = runtime.tick().unwrap();
        let replayed_third = runtime.tick().unwrap();

        assert_eq!(replayed_second.world_hash, second.world_hash);
        assert_eq!(replayed_third.world_hash, third.world_hash);
        let entity_id = runtime.spawn_summary().spawned_actors[0].entity_ids[0];
        assert_component_i64(&runtime, entity_id, 300, "count", 3_000_000);
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn live_restore_rejects_snapshot_hash_mismatch_before_restore() {
        let path = write_temp_cgs(valid_cgs_with_semantic_bindings());
        let mut runtime = initialise_dev(&path);
        runtime.tick().unwrap();
        let mut snapshot = runtime.world_snapshot().unwrap();
        snapshot.world_hash = "0".repeat(64);

        let result = runtime.restore_world_snapshot(&snapshot);

        assert!(result.is_err());
        let _ = std::fs::remove_file(path);
    }

    #[test]
    #[cfg(windows)]
    fn windows_10000_tick_deterministic_torture() {
        let path = write_temp_cgs(valid_cgs_with_semantic_bindings());
        let mut runtime_a = initialise_dev(&path);
        let mut runtime_b = initialise_dev(&path);

        for tick in 0..10_000_u64 {
            let a = runtime_a.tick().unwrap();
            let b = runtime_b.tick().unwrap();
            assert_eq!(a.tick, tick);
            assert_eq!(b.tick, tick);
            assert_eq!(
                a.world_hash, b.world_hash,
                "determinism torture diverged at tick {}",
                tick
            );
        }

        assert_eq!(runtime_a.status().hash_log.len(), 10_000);
        assert_eq!(runtime_b.status().hash_log.len(), 10_000);
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn runtime_input_component_accepts_semantic_button_actions() {
        let packet = InputPacket::with_actions(
            7,
            12,
            99,
            vec![
                InputAction {
                    action: "Attack".to_string(),
                    value: 1.0,
                    kind: InputActionKind::Button,
                    phase: InputActionPhase::Started,
                    secondary_value: 0.0,
                    target_entity: None,
                    metadata: Default::default(),
                },
                InputAction::button("Pickup", true),
                InputAction::button("Dash", true),
            ],
        )
        .with_player(1)
        .with_device("keyboard");

        let value = input_json(&packet);
        assert_eq!(value["attack_pressed"], true);
        assert_eq!(value["attack_started"], true);
        assert_eq!(value["interact_pressed"], true);
        assert_eq!(value["pickup_pressed"], true);
        assert_eq!(value["dash_pressed"], true);
        assert_eq!(value["peer_id"], 7);
        assert_eq!(value["source_tick"], 12);
    }

    #[test]
    fn runtime_input_component_accepts_current_lowercase_adapter_actions() {
        let packet = InputPacket::with_actions(
            1,
            3,
            4,
            vec![
                InputAction::axis("move_x", 0.75),
                InputAction::axis("move_z", -0.5),
                InputAction::button("attack", true),
                InputAction::button("interact", true),
                InputAction::button("dash", false),
            ],
        );

        let value = input_json(&packet);
        assert_eq!(value["move_x"], 0.75);
        assert_eq!(value["move_z"], -0.5);
        assert_eq!(value["attack_pressed"], true);
        assert_eq!(value["interact_pressed"], true);
        assert_eq!(value["pickup_pressed"], false);
        assert_eq!(value["dash_pressed"], false);
    }

    fn write_temp_cgs(contents: String) -> PathBuf {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "xace-runtime-playback-bindings-{}-{}.json",
            std::process::id(),
            unique
        ));
        std::fs::write(&path, contents).unwrap();
        path
    }

    fn write_temp_project_cgs(contents: String) -> (PathBuf, PathBuf) {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "xace-runtime-sgc-plan-{}-{}",
            std::process::id(),
            unique
        ));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("game.cgs.json");
        std::fs::write(&path, contents).unwrap();
        (root, path)
    }

    fn write_runtime_plan(root: &Path, cgs_hash: &str, contents: String) {
        let dir = root.join(".xace").join("execution_plans");
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join(format!("{}.plan.json", cgs_hash)), contents).unwrap();
    }

    fn valid_cgs_with_semantic_bindings() -> String {
        r#"
        {
          "metadata": {"name": "Runtime Semantic Binding Test", "version": "0.1.0", "schema_version": "0.1.0", "cgs_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
          "semantic_bindings": {
            "bindings": [
              {
                "binding_id": "bind_anim",
                "event_name": "interaction.accepted",
                "playback_kind": "Animation",
                "asset": {"id": "asset_interact_anim_clip_v1", "asset_type": "AnimationClip", "status": "Linked"},
                "semantic_action": "play",
                "entity_selector": "SourceEntity",
                "parameters": {"blend": "0.1"},
                "priority": 0
              },
              {
                "binding_id": "bind_audio",
                "event_name": "interaction.accepted",
                "playback_kind": "Audio",
                "asset": {"id": "asset_interact_sfx_v1", "asset_type": "AudioClip", "status": "Linked"},
                "semantic_action": "play",
                "entity_selector": "SourceEntity",
                "priority": 1
              },
              {
                "binding_id": "bind_vfx",
                "event_name": "interaction.accepted",
                "playback_kind": "Vfx",
                "asset": {"id": "asset_interact_particle_v1", "asset_type": "Particle", "status": "Linked"},
                "semantic_action": "spawn",
                "entity_selector": "TargetEntity",
                "priority": 2
              }
            ]
          },
          "global_systems": [],
          "modes": [
            {
              "id": "default",
              "schema_version": "0.1.0",
              "is_default": true,
              "actors": [
                {
                  "id": "player",
                  "spawn_count": 1,
                  "components": [
                    {"type_id": 1, "name": "COMP_TRANSFORM_V1", "defaults": {"position_x": 0, "position_y": 0, "position_z": 0}},
                    {"type_id": 2, "name": "COMP_IDENTITY_V1", "defaults": {"name": "player"}}
                  ]
                },
                {
                  "id": "target",
                  "spawn_count": 1,
                  "components": [
                    {"type_id": 1, "name": "COMP_TRANSFORM_V1", "defaults": {"position_x": 1, "position_y": 0, "position_z": 0}},
                    {"type_id": 2, "name": "COMP_IDENTITY_V1", "defaults": {"name": "target"}}
                  ]
                }
              ],
              "systems": [],
              "rules": []
            }
          ]
        }
        "#
        .to_string()
    }

    fn cgs_with_runtime_systems(
        cgs_hash: &str,
        execution_plan_version: u32,
        include_custom: bool,
    ) -> String {
        let global_systems = if include_custom {
            r#"{"id": "CustomGeneratedSystem", "phase": "Simulation", "reads": [1], "writes": [100], "depends_on": [], "deterministic": true}"#
        } else {
            r#"{"id": "MovementSystem", "phase": "Simulation", "reads": [1, 5], "writes": [1], "depends_on": [], "deterministic": true}"#
        };
        format!(
            r#"
        {{
          "metadata": {{"name": "Runtime Systems Test", "schema_version": "0.1.0", "version": "0.1.0", "execution_plan_version": {}, "cgs_hash": "{}"}},
          "global_systems": [{}],
          "modes": [
            {{
              "id": "default",
              "schema_version": "0.1.0",
              "is_default": true,
              "actors": [
                {{
                  "id": "player",
                  "spawn_count": 1,
                  "components": [
                    {{"type_id": 1, "name": "COMP_TRANSFORM_V1", "defaults": {{"position_x": 0, "position_y": 0, "position_z": 0}}}},
                    {{"type_id": 2, "name": "COMP_IDENTITY_V1", "defaults": {{"name": "player"}}}},
                    {{"type_id": 5, "name": "COMP_VELOCITY_V1", "defaults": {{"vx": 1, "vy": 0, "vz": 0}}}}
                  ]
                }}
              ],
              "systems": [],
              "rules": []
            }}
          ]
        }}
        "#,
            execution_plan_version, cgs_hash, global_systems
        )
    }

    fn cgs_with_generated_counter_runtime_system(cgs_hash: &str) -> String {
        format!(
            r#"
        {{
          "metadata": {{"name": "Generated Counter Runtime Test", "schema_version": "0.1.0", "version": "0.1.0", "cgs_hash": "{}"}},
          "global_systems": [
            {{
              "id": "GeneratedCounterSystem",
              "phase": "Simulation",
              "reads": [300],
              "writes": [300],
              "depends_on": [],
              "deterministic": true,
              "runtime_executor": {{
                "kind": "generated.increment_numeric_field",
                "component_type_id": 300,
                "field": "count",
                "amount": 1
              }}
            }}
          ],
          "modes": [
            {{
              "id": "default",
              "schema_version": "0.1.0",
              "is_default": true,
              "actors": [
                {{
                  "id": "counter",
                  "spawn_count": 1,
                  "components": [
                    {{"type_id": 300, "name": "COMP_COUNTER_V1", "defaults": {{"count": 0}}}}
                  ]
                }}
              ],
              "systems": [],
              "rules": []
            }}
          ]
        }}
        "#,
            cgs_hash
        )
    }

    fn cgs_with_two_generated_runtime_systems(cgs_hash: &str) -> String {
        format!(
            r#"
        {{
          "metadata": {{"name": "Generated Pair Runtime Test", "schema_version": "0.1.0", "version": "0.1.0", "cgs_hash": "{}"}},
          "global_systems": [
            {{
              "id": "GeneratedCounterSystem",
              "phase": "Simulation",
              "reads": [300],
              "writes": [300],
              "depends_on": [],
              "deterministic": true,
              "runtime_executor": {{
                "kind": "generated.increment_numeric_field",
                "component_type_id": 300,
                "field": "count",
                "amount": 1,
                "abi": {{
                  "schema": "xace.generated_system_abi.v1",
                  "version": 1,
                  "inputs": {{
                    "query_components": [300],
                    "component_reads": [300],
                    "current_tick": false
                  }},
                  "events": {{"emits": []}},
                  "rng": {{"allowed": false, "max_calls_per_entity": 0}},
                  "errors": {{"policy": "halt_and_rollback"}},
                  "rollback": {{
                    "mutation_hook": "mutation_gate_deferred",
                    "event_hook": "event_bus_phase_buffered",
                    "rng_hook": "rng_windowed"
                  }}
                }}
              }}
            }},
            {{
              "id": "GeneratedLootRollSystem",
              "phase": "Simulation",
              "reads": [301],
              "writes": [],
              "depends_on": [],
              "deterministic": true,
              "runtime_executor": {{
                "kind": "generated.emit_event_on_rng_threshold",
                "component_type_id": 301,
                "chance": 1.0,
                "event_type": "generated.loot_roll",
                "payload": {{"source": "generated"}},
                "abi": {{
                  "schema": "xace.generated_system_abi.v1",
                  "version": 1,
                  "inputs": {{
                    "query_components": [301],
                    "component_reads": [301],
                    "current_tick": true
                  }},
                  "events": {{
                    "emits": [
                      {{
                        "event_type": "generated.loot_roll",
                        "broadcast": true,
                        "payload": {{"source": "generated"}}
                      }}
                    ]
                  }},
                  "rng": {{"allowed": true, "max_calls_per_entity": 1}},
                  "errors": {{"policy": "halt_and_rollback"}},
                  "rollback": {{
                    "mutation_hook": "mutation_gate_deferred",
                    "event_hook": "event_bus_phase_buffered",
                    "rng_hook": "rng_windowed"
                  }}
                }}
              }}
            }}
          ],
          "modes": [
            {{
              "id": "default",
              "schema_version": "0.1.0",
              "is_default": true,
              "actors": [
                {{
                  "id": "counter",
                  "spawn_count": 1,
                  "components": [
                    {{"type_id": 300, "name": "COMP_COUNTER_V1", "defaults": {{"count": 0}}}}
                  ]
                }},
                {{
                  "id": "loot_source",
                  "spawn_count": 1,
                  "components": [
                    {{"type_id": 301, "name": "COMP_LOOT_ROLL_V1", "defaults": {{"enabled": true}}}}
                  ]
                }}
              ],
              "systems": [],
              "rules": []
            }}
          ]
        }}
        "#,
            cgs_hash
        )
    }

    fn cgs_with_generated_plugin_external_runtime_systems(cgs_hash: &str) -> String {
        format!(
            r#"
        {{
          "metadata": {{"name": "Unified Runtime Executor Test", "schema_version": "0.1.0", "version": "0.1.0", "execution_plan_version": 1, "cgs_hash": "{}"}},
          "component_schemas": [
            {{"type_id": 300, "name": "COMP_COUNTER_V1", "defaults": {{"count": 0}}, "source": "generated"}},
            {{"type_id": 700, "name": "PLUGIN_WEATHER_STATE_V1", "defaults": {{"active": false}}, "source": "plugin"}},
            {{"type_id": 701, "name": "EXTERNAL_POWER_SOURCE_V1", "defaults": {{"power": 5000000}}, "source": "external"}},
            {{"type_id": 702, "name": "EXTERNAL_MIRROR_STATE_V1", "defaults": {{"mirrored_power": 0}}, "source": "external"}}
          ],
          "global_systems": [
            {{
              "id": "ExternalMirrorSystem",
              "phase": "Simulation",
              "reads": [701, 702],
              "writes": [702],
              "depends_on": [],
              "deterministic": true,
              "runtime_executor": {{
                "kind": "external.copy_numeric_field",
                "source_component_type_id": 701,
                "source_field": "power",
                "target_component_type_id": 702,
                "target_field": "mirrored_power",
                "abi": {{
                  "schema": "xace.runtime_executor_abi.v1",
                  "version": 1,
                  "inputs": {{
                    "query_components": [701, 702],
                    "component_reads": [701, 702],
                    "current_tick": false
                  }},
                  "events": {{"emits": []}},
                  "rng": {{"allowed": false, "max_calls_per_entity": 0}},
                  "errors": {{"policy": "halt_and_rollback"}},
                  "rollback": {{
                    "mutation_hook": "mutation_gate_deferred",
                    "event_hook": "event_bus_phase_buffered",
                    "rng_hook": "rng_windowed"
                  }}
                }}
              }}
            }},
            {{
              "id": "GeneratedCounterSystem",
              "phase": "Simulation",
              "reads": [300],
              "writes": [300],
              "depends_on": [],
              "deterministic": true,
              "runtime_executor": {{
                "kind": "generated.increment_numeric_field",
                "component_type_id": 300,
                "field": "count",
                "amount": 1,
                "abi": {{
                  "schema": "xace.runtime_executor_abi.v1",
                  "version": 1,
                  "inputs": {{
                    "query_components": [300],
                    "component_reads": [300],
                    "current_tick": false
                  }},
                  "events": {{"emits": []}},
                  "rng": {{"allowed": false, "max_calls_per_entity": 0}},
                  "errors": {{"policy": "halt_and_rollback"}},
                  "rollback": {{
                    "mutation_hook": "mutation_gate_deferred",
                    "event_hook": "event_bus_phase_buffered",
                    "rng_hook": "rng_windowed"
                  }}
                }}
              }}
            }},
            {{
              "id": "PluginWeatherSystem",
              "phase": "Simulation",
              "reads": [700],
              "writes": [700],
              "depends_on": [],
              "deterministic": true,
              "runtime_executor": {{
                "kind": "plugin.set_json_field",
                "component_type_id": 700,
                "field": "active",
                "value": true,
                "abi": {{
                  "schema": "xace.runtime_executor_abi.v1",
                  "version": 1,
                  "inputs": {{
                    "query_components": [700],
                    "component_reads": [700],
                    "current_tick": false
                  }},
                  "events": {{"emits": []}},
                  "rng": {{"allowed": false, "max_calls_per_entity": 0}},
                  "errors": {{"policy": "halt_and_rollback"}},
                  "rollback": {{
                    "mutation_hook": "mutation_gate_deferred",
                    "event_hook": "event_bus_phase_buffered",
                    "rng_hook": "rng_windowed"
                  }}
                }}
              }}
            }}
          ],
          "modes": [
            {{
              "id": "default",
              "schema_version": "0.1.0",
              "is_default": true,
              "actors": [
                {{
                  "id": "runtime_executor_subject",
                  "spawn_count": 1,
                  "components": [
                    {{"type_id": 300, "name": "COMP_COUNTER_V1", "defaults": {{"count": 0}}}},
                    {{"type_id": 700, "name": "PLUGIN_WEATHER_STATE_V1", "defaults": {{"active": false}}}},
                    {{"type_id": 701, "name": "EXTERNAL_POWER_SOURCE_V1", "defaults": {{"power": 5000000}}}},
                    {{"type_id": 702, "name": "EXTERNAL_MIRROR_STATE_V1", "defaults": {{"mirrored_power": 0}}}}
                  ]
                }}
              ],
              "systems": [],
              "rules": []
            }}
          ]
        }}
        "#,
            cgs_hash
        )
    }

    fn cgs_hot_swap_runtime_systems(
        cgs_hash: &str,
        execution_plan_version: u32,
        include_extended_systems: bool,
    ) -> String {
        let external_mirror = json!({
            "id": "ExternalMirrorSystem",
            "phase": "Simulation",
            "reads": [701, 702],
            "writes": [702],
            "depends_on": [],
            "deterministic": true,
            "runtime_executor": {
                "kind": "external.copy_numeric_field",
                "source_component_type_id": 701,
                "source_field": "power",
                "target_component_type_id": 702,
                "target_field": "mirrored_power"
            }
        });
        let generated_counter = json!({
            "id": "GeneratedCounterSystem",
            "phase": "Simulation",
            "reads": [300],
            "writes": [300],
            "depends_on": [],
            "deterministic": true,
            "runtime_executor": {
                "kind": "generated.increment_numeric_field",
                "component_type_id": 300,
                "field": "count",
                "amount": 1
            }
        });
        let plugin_weather = json!({
            "id": "PluginWeatherSystem",
            "phase": "Simulation",
            "reads": [700],
            "writes": [700],
            "depends_on": [],
            "deterministic": true,
            "runtime_executor": {
                "kind": "plugin.set_json_field",
                "component_type_id": 700,
                "field": "active",
                "value": true
            }
        });
        let mut global_systems = vec![generated_counter];
        if include_extended_systems {
            global_systems.insert(0, external_mirror);
            global_systems.push(plugin_weather);
        }

        serde_json::to_string_pretty(&json!({
            "metadata": {
                "name": "Runtime Hot Swap Test",
                "schema_version": "0.1.0",
                "version": "0.1.0",
                "execution_plan_version": execution_plan_version,
                "cgs_hash": cgs_hash
            },
            "component_schemas": [
                {"type_id": 300, "name": "COMP_COUNTER_V1", "defaults": {"count": 0}, "source": "generated"},
                {"type_id": 700, "name": "PLUGIN_WEATHER_STATE_V1", "defaults": {"active": false}, "source": "plugin"},
                {"type_id": 701, "name": "EXTERNAL_POWER_SOURCE_V1", "defaults": {"power": 5000000}, "source": "external"},
                {"type_id": 702, "name": "EXTERNAL_MIRROR_STATE_V1", "defaults": {"mirrored_power": 0}, "source": "external"}
            ],
            "global_systems": global_systems,
            "modes": [
                {
                    "id": "default",
                    "schema_version": "0.1.0",
                    "is_default": true,
                    "actors": [
                        {
                            "id": "runtime_hot_swap_subject",
                            "spawn_count": 1,
                            "components": [
                                {"type_id": 300, "name": "COMP_COUNTER_V1", "defaults": {"count": 0}},
                                {"type_id": 700, "name": "PLUGIN_WEATHER_STATE_V1", "defaults": {"active": false}},
                                {"type_id": 701, "name": "EXTERNAL_POWER_SOURCE_V1", "defaults": {"power": 5000000}},
                                {"type_id": 702, "name": "EXTERNAL_MIRROR_STATE_V1", "defaults": {"mirrored_power": 0}}
                            ]
                        }
                    ],
                    "systems": [],
                    "rules": []
                }
            ]
        }))
        .unwrap()
    }

    fn cgs_with_added_empty_component_table(
        cgs_hash: &str,
        execution_plan_version: u32,
        component_type_id: u32,
    ) -> String {
        let mut cgs = serde_json::from_str::<Value>(&cgs_hot_swap_runtime_systems(
            cgs_hash,
            execution_plan_version,
            false,
        ))
        .unwrap();
        cgs["component_schemas"]
            .as_array_mut()
            .unwrap()
            .push(json!({
                "type_id": component_type_id,
                "name": format!("COMP_HOT_SWAP_EMPTY_{}_V1", component_type_id),
                "defaults": {"value": 0},
                "source": "generated"
            }));
        serde_json::to_string_pretty(&cgs).unwrap()
    }

    fn cgs_with_added_actor_component_backfill_requirement(
        cgs_hash: &str,
        execution_plan_version: u32,
        component_type_id: u32,
    ) -> String {
        let mut cgs = serde_json::from_str::<Value>(&cgs_with_added_empty_component_table(
            cgs_hash,
            execution_plan_version,
            component_type_id,
        ))
        .unwrap();
        cgs["modes"][0]["actors"][0]["components"]
            .as_array_mut()
            .unwrap()
            .push(json!({
                "type_id": component_type_id,
                "name": format!("COMP_HOT_SWAP_EMPTY_{}_V1", component_type_id),
                "defaults": {"value": 100}
            }));
        serde_json::to_string_pretty(&cgs).unwrap()
    }

    fn cgs_with_schema_version(cgs_json: String, schema_version: &str) -> String {
        let mut cgs = serde_json::from_str::<Value>(&cgs_json).unwrap();
        cgs["metadata"]["schema_version"] = json!(schema_version);
        cgs["metadata"]["version"] = json!(schema_version);
        for mode in cgs["modes"].as_array_mut().unwrap() {
            mode["schema_version"] = json!(schema_version);
        }
        serde_json::to_string_pretty(&cgs).unwrap()
    }

    fn cgs_with_actor_component_backfill_versions(
        cgs_hash: &str,
        execution_plan_version: u32,
        schema_version: &str,
        component_defaults: &[(u32, i64)],
    ) -> String {
        let mut cgs = serde_json::from_str::<Value>(&cgs_with_schema_version(
            cgs_hot_swap_runtime_systems(cgs_hash, execution_plan_version, false),
            schema_version,
        ))
        .unwrap();
        for (component_type_id, default_value) in component_defaults {
            cgs["component_schemas"]
                .as_array_mut()
                .unwrap()
                .push(json!({
                    "type_id": component_type_id,
                    "name": format!("COMP_HOT_SWAP_MIGRATED_{}_V1", component_type_id),
                    "defaults": {"value": 0},
                    "source": "generated"
                }));
            cgs["modes"][0]["actors"][0]["components"]
                .as_array_mut()
                .unwrap()
                .push(json!({
                    "type_id": component_type_id,
                    "name": format!("COMP_HOT_SWAP_MIGRATED_{}_V1", component_type_id),
                    "defaults": {"value": default_value}
                }));
        }
        serde_json::to_string_pretty(&cgs).unwrap()
    }

    fn cgs_with_counter_amount(cgs_hash: &str, execution_plan_version: u32, amount: i64) -> String {
        let mut cgs = serde_json::from_str::<Value>(&cgs_hot_swap_runtime_systems(
            cgs_hash,
            execution_plan_version,
            false,
        ))
        .unwrap();
        let systems = cgs["global_systems"].as_array_mut().unwrap();
        let counter = systems
            .iter_mut()
            .find(|system| system["id"] == "GeneratedCounterSystem")
            .unwrap();
        counter["runtime_executor"]["amount"] = json!(amount);
        serde_json::to_string_pretty(&cgs).unwrap()
    }

    fn cgs_with_spawn_count(
        cgs_hash: &str,
        execution_plan_version: u32,
        spawn_count: u32,
    ) -> String {
        let mut cgs = serde_json::from_str::<Value>(&cgs_hot_swap_runtime_systems(
            cgs_hash,
            execution_plan_version,
            false,
        ))
        .unwrap();
        cgs["modes"][0]["actors"][0]["spawn_count"] = json!(spawn_count);
        serde_json::to_string_pretty(&cgs).unwrap()
    }

    fn runtime_plan(cgs_hash: &str, plan_version: u32, include_custom: bool) -> String {
        let systems = if include_custom {
            r#"["CustomGeneratedSystem"]"#
        } else {
            r#"["MovementSystem"]"#
        };
        let all_system_ids = if include_custom {
            r#"["CustomGeneratedSystem"]"#
        } else {
            r#"["MovementSystem"]"#
        };
        let system_metadata = if include_custom {
            r#""CustomGeneratedSystem": {"display_name": "Custom Generated System", "phase": "Simulation", "depends_on": [], "deterministic": true, "version": {"major": 1, "minor": 0}, "description": ""}"#
        } else {
            r#""MovementSystem": {"display_name": "Movement System", "phase": "Simulation", "depends_on": [], "deterministic": true, "version": {"major": 1, "minor": 0}, "description": ""}"#
        };
        let access_sets = if include_custom {
            r#""CustomGeneratedSystem": {"reads": [1], "writes": [100]}"#
        } else {
            r#""MovementSystem": {"reads": [1, 5], "writes": [1]}"#
        };
        let all_reads = if include_custom { "[1]" } else { "[1, 5]" };
        let all_writes = if include_custom { "[100]" } else { "[1]" };
        let component_ids = if include_custom { "[1, 100]" } else { "[1, 5]" };
        format!(
            r#"{{
          "schema_version": "0.1.0",
          "plan_version": {},
          "adapter_protocol_version": 1,
          "migration_status": "current",
          "created_tick": 0,
          "plan_hash": "{}",
          "compiled_from_cgs_hash": "{}",
          "all_system_ids": {},
          "phases": {{
            "2": {{
              "phase": "Simulation",
              "groups": [
                {{
                  "group_id": "Simulation_group_0",
                  "phase": "Simulation",
                  "parallel": false,
                  "systems": {},
                  "serialization_constraints": [],
                  "execution_index": 0
                }}
              ],
              "total_system_count": 1
            }}
          }},
          "component_access_sets": {{
            "schema": "xace.sgc.component_access_sets.v1",
            "by_system": {{{}}},
            "all_reads": {},
            "all_writes": {},
            "component_ids": {}
          }},
          "system_metadata": {{
            "schema": "xace.sgc.system_metadata.v1",
            "systems": {{{}}}
          }},
          "proof_bundle": {{
            "schema": "xace.sgc.proof_ref.v1",
            "path": ".xace/proof/sgc/{}",
            "compiled_from_cgs_hash": "{}",
            "plan_hash": "{}",
            "input_hash": "{}",
            "validation_hash": "{}"
          }}
        }}"#,
            plan_version,
            "d".repeat(64),
            cgs_hash,
            all_system_ids,
            systems,
            access_sets,
            all_reads,
            all_writes,
            component_ids,
            system_metadata,
            cgs_hash,
            cgs_hash,
            "d".repeat(64),
            "1".repeat(64),
            "2".repeat(64)
        )
    }

    fn runtime_plan_two_generated(cgs_hash: &str) -> String {
        format!(
            r#"{{
          "schema_version": "0.1.0",
          "plan_version": 1,
          "adapter_protocol_version": 1,
          "migration_status": "current",
          "created_tick": 0,
          "plan_hash": "{}",
          "compiled_from_cgs_hash": "{}",
          "all_system_ids": ["GeneratedCounterSystem", "GeneratedLootRollSystem"],
          "phases": {{
            "2": {{
              "phase": "Simulation",
              "groups": [
                {{
                  "group_id": "Simulation_group_0",
                  "phase": "Simulation",
                  "parallel": true,
                  "systems": ["GeneratedCounterSystem", "GeneratedLootRollSystem"],
                  "serialization_constraints": [],
                  "execution_index": 0
                }}
              ],
              "total_system_count": 2
            }}
          }},
          "component_access_sets": {{
            "schema": "xace.sgc.component_access_sets.v1",
            "by_system": {{
              "GeneratedCounterSystem": {{"reads": [300], "writes": [300]}},
              "GeneratedLootRollSystem": {{"reads": [301], "writes": []}}
            }},
            "all_reads": [300, 301],
            "all_writes": [300],
            "component_ids": [300, 301]
          }},
          "system_metadata": {{
            "schema": "xace.sgc.system_metadata.v1",
            "systems": {{
              "GeneratedCounterSystem": {{"display_name": "Generated Counter System", "phase": "Simulation", "depends_on": [], "deterministic": true, "version": {{"major": 1, "minor": 0}}, "description": ""}},
              "GeneratedLootRollSystem": {{"display_name": "Generated Loot Roll System", "phase": "Simulation", "depends_on": [], "deterministic": true, "version": {{"major": 1, "minor": 0}}, "description": ""}}
            }}
          }},
          "proof_bundle": {{
            "schema": "xace.sgc.proof_ref.v1",
            "path": ".xace/proof/sgc/{}",
            "compiled_from_cgs_hash": "{}",
            "plan_hash": "{}",
            "input_hash": "{}",
            "validation_hash": "{}"
          }}
        }}"#,
            "e".repeat(64),
            cgs_hash,
            cgs_hash,
            cgs_hash,
            "e".repeat(64),
            "1".repeat(64),
            "2".repeat(64)
        )
    }

    fn runtime_plan_generated_counter_only(cgs_hash: &str, plan_version: u32) -> String {
        format!(
            r#"{{
          "schema_version": "0.1.0",
          "plan_version": {},
          "adapter_protocol_version": 1,
          "migration_status": "current",
          "created_tick": 0,
          "plan_hash": "{}",
          "compiled_from_cgs_hash": "{}",
          "all_system_ids": ["GeneratedCounterSystem"],
          "phases": {{
            "2": {{
              "phase": "Simulation",
              "groups": [
                {{
                  "group_id": "Simulation_group_0",
                  "phase": "Simulation",
                  "parallel": false,
                  "systems": ["GeneratedCounterSystem"],
                  "serialization_constraints": [],
                  "execution_index": 0
                }}
              ],
              "total_system_count": 1
            }}
          }},
          "component_access_sets": {{
            "schema": "xace.sgc.component_access_sets.v1",
            "by_system": {{
              "GeneratedCounterSystem": {{"reads": [300], "writes": [300]}}
            }},
            "all_reads": [300],
            "all_writes": [300],
            "component_ids": [300]
          }},
          "system_metadata": {{
            "schema": "xace.sgc.system_metadata.v1",
            "systems": {{
              "GeneratedCounterSystem": {{"display_name": "Generated Counter System", "phase": "Simulation", "depends_on": [], "deterministic": true, "version": {{"major": 1, "minor": 0}}, "description": "Generated deterministic numeric increment executor."}}
            }}
          }},
          "proof_bundle": {{
            "schema": "xace.sgc.proof_ref.v1",
            "path": ".xace/proof/sgc/{}",
            "compiled_from_cgs_hash": "{}",
            "plan_hash": "{}",
            "input_hash": "{}",
            "validation_hash": "{}"
          }}
        }}"#,
            plan_version,
            "c".repeat(64),
            cgs_hash,
            cgs_hash,
            cgs_hash,
            "c".repeat(64),
            "1".repeat(64),
            "2".repeat(64)
        )
    }

    fn runtime_plan_generated_counter_only_with_schema(
        cgs_hash: &str,
        plan_version: u32,
        schema_version: &str,
    ) -> String {
        let mut plan = serde_json::from_str::<Value>(&runtime_plan_generated_counter_only(
            cgs_hash,
            plan_version,
        ))
        .unwrap();
        plan["schema_version"] = json!(schema_version);
        serde_json::to_string_pretty(&plan).unwrap()
    }

    fn runtime_plan_generated_plugin_external(cgs_hash: &str) -> String {
        runtime_plan_generated_plugin_external_with_version(cgs_hash, 1)
    }

    fn runtime_plan_generated_plugin_external_with_version(
        cgs_hash: &str,
        plan_version: u32,
    ) -> String {
        format!(
            r#"{{
          "schema_version": "0.1.0",
          "plan_version": {},
          "adapter_protocol_version": 1,
          "migration_status": "current",
          "created_tick": 0,
          "plan_hash": "{}",
          "compiled_from_cgs_hash": "{}",
          "all_system_ids": ["ExternalMirrorSystem", "GeneratedCounterSystem", "PluginWeatherSystem"],
          "phases": {{
            "2": {{
              "phase": "Simulation",
              "groups": [
                {{
                  "group_id": "Simulation_group_0",
                  "phase": "Simulation",
                  "parallel": true,
                  "systems": ["ExternalMirrorSystem", "GeneratedCounterSystem", "PluginWeatherSystem"],
                  "serialization_constraints": [],
                  "execution_index": 0
                }}
              ],
              "total_system_count": 3
            }}
          }},
          "component_access_sets": {{
            "schema": "xace.sgc.component_access_sets.v1",
            "by_system": {{
              "ExternalMirrorSystem": {{"reads": [701, 702], "writes": [702]}},
              "GeneratedCounterSystem": {{"reads": [300], "writes": [300]}},
              "PluginWeatherSystem": {{"reads": [700], "writes": [700]}}
            }},
            "all_reads": [300, 700, 701, 702],
            "all_writes": [300, 700, 702],
            "component_ids": [300, 700, 701, 702]
          }},
          "system_metadata": {{
            "schema": "xace.sgc.system_metadata.v1",
            "systems": {{
              "ExternalMirrorSystem": {{"display_name": "External Mirror System", "phase": "Simulation", "depends_on": [], "deterministic": true, "version": {{"major": 1, "minor": 0}}, "description": "External deterministic numeric field copy executor."}},
              "GeneratedCounterSystem": {{"display_name": "Generated Counter System", "phase": "Simulation", "depends_on": [], "deterministic": true, "version": {{"major": 1, "minor": 0}}, "description": "Generated deterministic numeric increment executor."}},
              "PluginWeatherSystem": {{"display_name": "Plugin Weather System", "phase": "Simulation", "depends_on": [], "deterministic": true, "version": {{"major": 1, "minor": 0}}, "description": "Plugin deterministic JSON field set executor."}}
            }}
          }},
          "proof_bundle": {{
            "schema": "xace.sgc.proof_ref.v1",
            "path": ".xace/proof/sgc/{}",
            "compiled_from_cgs_hash": "{}",
            "plan_hash": "{}",
            "input_hash": "{}",
            "validation_hash": "{}"
          }}
        }}"#,
            plan_version,
            "f".repeat(64),
            cgs_hash,
            cgs_hash,
            cgs_hash,
            "f".repeat(64),
            "1".repeat(64),
            "2".repeat(64)
        )
    }
}

struct RuntimeHotSwapCandidate {
    config: RuntimeConfig,
    summary: cgs_loader::SpawnSummary,
    phase_plan: cgs_loader::RuntimePhasePlan,
    schedule_plan: cgs_loader::RuntimeSchedulePlan,
    identity: cgs_loader::RuntimeScheduleIdentity,
    registry: SystemRegistry,
    scratch_table_store: ComponentTableStore,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct RuntimeHotSwapSystemSignature {
    phase: String,
    reads: Vec<u32>,
    writes: Vec<u32>,
    depends_on: Vec<String>,
    deterministic: bool,
    parallel: bool,
    runtime_executor: String,
}

fn load_hot_swap_candidate(
    cgs_path: &Path,
    mut config: RuntimeConfig,
) -> Result<RuntimeHotSwapCandidate> {
    let mut scratch_entity_store = EntityStore::new();
    let mut scratch_table_store = ComponentTableStore::new();
    let summary = cgs_loader::load_and_spawn_with_plan_policy(
        cgs_path,
        &mut scratch_entity_store,
        &mut scratch_table_store,
        config.sgc_plan_policy,
        config.sgc_plan_path.as_deref(),
    )?;
    config.execution_plan_version = summary.execution_plan_version;
    let phase_plan = summary.phase_plan.clone();
    let schedule_plan = summary.schedule_plan.clone();
    let identity = schedule_plan.identity();
    let mut registry = builtin_systems::build_default_registry()?;
    register_runtime_executor_systems(&mut registry, &summary.runtime_systems)?;
    validate_phase_plan(&phase_plan, &registry)?;

    Ok(RuntimeHotSwapCandidate {
        config,
        summary,
        phase_plan,
        schedule_plan,
        identity,
        registry,
        scratch_table_store,
    })
}

fn hot_swap_issue(
    class: RuntimeHotSwapCompatibilityClass,
    code: impl Into<String>,
    message: impl Into<String>,
    component_type_id: Option<u32>,
    system_id: Option<String>,
) -> RuntimeHotSwapCompatibilityIssue {
    RuntimeHotSwapCompatibilityIssue {
        class,
        code: code.into(),
        message: message.into(),
        component_type_id,
        system_id,
    }
}

fn hot_swap_refusal_message(compatibility: &RuntimeHotSwapCompatibilityReport) -> String {
    format!(
        "runtime schema hot-swap refused: compatibility_class={} reset_required={} migration_required={} issues={}",
        compatibility.overall_class.as_str(),
        compatibility.reset_required,
        compatibility.migration_required,
        compatibility.issue_summary()
    )
}

fn component_table_rows_hash(
    component_type_id: u32,
    table: Option<&ComponentTable>,
) -> Result<String> {
    let rows = table
        .map(|table| {
            table
                .iter()
                .map(|(entity_id, component_json)| {
                    let parsed = serde_json::from_str::<Value>(component_json)
                        .unwrap_or_else(|_| Value::String(component_json.to_string()));
                    json!({
                        "entity_id": entity_id,
                        "component_json": parsed
                    })
                })
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    let payload = json!({
        "component_type_id": component_type_id,
        "rows": rows
    });
    let bytes = serde_json::to_vec(&payload)?;
    let digest = Sha256::digest(&bytes);
    Ok(format!("{:x}", digest))
}

fn component_registration_map(
    registrations: &[cgs_loader::ComponentRegistration],
) -> BTreeMap<u32, cgs_loader::ComponentRegistration> {
    registrations
        .iter()
        .map(|registration| (registration.type_id, registration.clone()))
        .collect()
}

fn actor_topology(summary: &cgs_loader::SpawnSummary) -> Vec<(String, usize)> {
    summary
        .spawned_actors
        .iter()
        .map(|actor| (actor.actor_id.clone(), actor.entity_ids.len()))
        .collect()
}

fn schedule_phase_by_system(
    groups: &[cgs_loader::RuntimeScheduleGroup],
) -> BTreeMap<String, String> {
    groups
        .iter()
        .flat_map(|group| {
            group
                .systems
                .iter()
                .map(move |system_id| (system_id.clone(), group.phase.clone()))
        })
        .collect()
}

fn system_signature_map(
    systems: &[cgs_loader::CgsSystem],
) -> BTreeMap<String, RuntimeHotSwapSystemSignature> {
    systems
        .iter()
        .map(|system| (system.id.trim().to_string(), system_signature(system)))
        .collect()
}

fn system_signature(system: &cgs_loader::CgsSystem) -> RuntimeHotSwapSystemSignature {
    let mut reads = system.reads.clone();
    reads.sort_unstable();
    let mut writes = system.writes.clone();
    writes.sort_unstable();
    let mut depends_on = system.depends_on.clone();
    depends_on.sort();

    RuntimeHotSwapSystemSignature {
        phase: system.phase.trim().to_string(),
        reads,
        writes,
        depends_on,
        deterministic: system.deterministic,
        parallel: system.parallel,
        runtime_executor: serde_json::to_string(&system.runtime_executor).unwrap_or_default(),
    }
}

fn hot_swap_component_table_additions(
    table_store: &ComponentTableStore,
    registrations: &[cgs_loader::ComponentRegistration],
) -> Result<Vec<cgs_loader::ComponentRegistration>> {
    let mut additions = Vec::new();
    for registration in registrations {
        if let Some(existing) = table_store.get_table(registration.type_id) {
            if existing.component_type_name() != registration.name {
                anyhow::bail!(
                    "runtime schema hot-swap refused component type_id {} rename from '{}' to '{}'",
                    registration.type_id,
                    existing.component_type_name(),
                    registration.name
                );
            }
            continue;
        }
        additions.push(registration.clone());
    }
    Ok(additions)
}

fn apply_hot_swap_component_table_additions(
    table_store: &mut ComponentTableStore,
    additions: &[cgs_loader::ComponentRegistration],
) -> Result<Vec<u32>> {
    let mut added = Vec::new();
    for registration in additions {
        table_store
            .register_table(registration.type_id, registration.name.as_str())
            .map_err(|err| {
                anyhow::anyhow!(
                    "register hot-swap component table {} '{}': {}",
                    registration.type_id,
                    registration.name,
                    err
                )
            })?;
        added.push(registration.type_id);
    }
    Ok(added)
}

fn register_runtime_executor_systems(
    registry: &mut SystemRegistry,
    systems: &[cgs_loader::CgsSystem],
) -> Result<()> {
    for system in systems {
        let system_id = system.id.trim();
        if system_id.is_empty() || registry.has_system(system_id) {
            continue;
        }
        let Some(spec) = cgs_loader::runtime_executor_spec(system)? else {
            continue;
        };
        registry
            .register(crate::generated_system_abi::build_generated_runtime_system(
                spec,
            ))
            .map_err(|err| anyhow::anyhow!("{}", err))?;
    }
    Ok(())
}

fn set_json_path(target: &mut Value, field_path: &str, value: Value) -> Result<()> {
    let mut cursor = target;
    let mut segments = field_path.split('.').peekable();
    while let Some(segment) = segments.next() {
        let is_leaf = segments.peek().is_none();
        if is_leaf {
            let Some(object) = cursor.as_object_mut() else {
                anyhow::bail!("field_path '{}' does not resolve to an object", field_path);
            };
            object.insert(segment.to_string(), value);
            return Ok(());
        }
        let Some(object) = cursor.as_object_mut() else {
            anyhow::bail!("field_path '{}' does not resolve to an object", field_path);
        };
        cursor = object
            .entry(segment.to_string())
            .or_insert_with(|| Value::Object(serde_json::Map::new()));
    }
    Ok(())
}

fn validate_phase_plan(
    plan: &cgs_loader::RuntimePhasePlan,
    registry: &SystemRegistry,
) -> Result<()> {
    for (_, systems, _) in plan {
        let system_refs = systems.iter().map(String::as_str).collect::<Vec<_>>();
        registry
            .validate_execution_plan_systems(&system_refs)
            .map_err(|err| anyhow::anyhow!("invalid phase plan: {}", err))?;
    }
    Ok(())
}

fn build_determinism_guard(
    mode: GuardMode,
    schema_version: &str,
    execution_plan_version: u32,
    phase_plan: &cgs_loader::RuntimePhasePlan,
) -> DeterminismGuard {
    let mut guard = DeterminismGuard::new(mode, schema_version, execution_plan_version);
    let system_ids = phase_plan
        .iter()
        .flat_map(|(_, systems, _)| systems.iter().map(String::as_str))
        .collect::<Vec<_>>();
    guard.register_systems(&system_ids);
    guard
}
