//! # XACE Module Boundary Interfaces
//!
//! The complete set of trait interfaces that define every module boundary
//! in XACE. These are the contracts — not implementations.
//!
//! ## Why Interfaces First
//! CLAUDE.md Coding Convention 1: "Contracts before implementation."
//! Every module in XACE implements one or more of these traits.
//! No module may call another module except through these interfaces.
//! This enforces the 7-layer architecture and prevents layer bypass.
//!
//! ## Treat as a Public API
//! These interfaces are load-bearing for the entire multi-language
//! boundary between Rust, Python, TypeScript, and C#.
//! Once Phase 1 is committed, treat these as frozen public API.
//! Changes require explicit versioning and migration planning.
//!
//! ## Interface Inventory
//! ISystem           — a single game system that runs each tick
//! IMutationGate     — deferred mutation queue controller
//! IEntityStore      — entity lifecycle manager
//! IComponentTable   — per-type component data storage
//! ISnapshotEngine   — world state capture and restore
//! IEventBus         — deterministic event dispatch
//! IDeterminismGuard — D-rule enforcement at execution boundaries
//! IEngineAdapter    — engine-side state sync (updated Audit 6)
//! ISaveEngine       — save/load/migration (Audit 7)
//!
//! ## Error Handling
//! All fallible interface methods return Result<T, XaceError>.
//! No interface method panics — errors are always propagated.
//! The caller decides how to handle each error variant.

use std::collections::BTreeMap;
use crate::entity_id::EntityID;
use crate::entity_metadata::Tick;
use crate::errors::xace_error::XaceError;
use crate::errors::determinism_error::DeterminismViolation;
use crate::runtime::world_snapshot::WorldSnapshot;
use crate::runtime::state_delta::StateDelta;
use crate::events::event_struct::Event;
use crate::events::event_type::EventType;
use crate::wire::feedback_payload::FeedbackPayload;
use crate::wire::snapshot_payload::SnapshotPayload;
use crate::wire::delta_payload::DeltaPayload;

// ── ISystem ───────────────────────────────────────────────────────────────────

/// A single game system that executes once per simulation tick phase.
///
/// Systems are the only place where game logic lives. They read component
/// data via SystemContext, compute results, and submit mutations via the
/// Mutation Gate. They never call other systems directly.
///
/// ## Implementation Requirements
/// - Must be deterministic: same input state → same output state always
/// - Must only read declared components (SystemDefinition.reads)
/// - Must only write declared components via Mutation Gate (SystemDefinition.writes)
/// - Must never call OS random, current time, or other non-deterministic APIs
/// - Must never mutate component state directly — only via Mutation Gate (I2)
///
/// ## Lifecycle
/// Systems are registered in the SystemRegistry at startup.
/// The PhaseOrchestrator calls execute() on each system each tick
/// in the order defined by the ExecutionPlan (D1).
pub trait ISystem: Send + Sync {
    /// Returns the unique system ID matching the CGS SystemDefinition.
    /// Must be stable across runs — used for RNG seeding (D6) and
    /// ExecutionPlan validation.
    fn system_id(&self) -> &str;

    /// Executes this system for one tick in the given phase.
    ///
    /// Called by the PhaseOrchestrator. The system reads component data,
    /// computes results, and submits mutations and events to the context.
    ///
    /// ## Contract
    /// - Must complete without direct state mutation (I2)
    /// - Must use only declared component reads and writes
    /// - Must be deterministic given identical input state
    /// - Must not block — no I/O, no network, no file access
    ///
    /// Returns Ok(()) on success. Returns XaceError on violation.
    fn execute(&self, context: &mut dyn ISystemContext) -> Result<(), XaceError>;

    /// Returns the component type IDs this system reads.
    /// Must match SystemDefinition.reads exactly.
    /// Used by SystemContext to enforce read access contracts.
    fn declared_reads(&self) -> &[u32];

    /// Returns the component type IDs this system writes.
    /// Must match SystemDefinition.writes exactly.
    /// Used by SystemContext to enforce write access contracts.
    fn declared_writes(&self) -> &[u32];
}

// ── ISystemContext ────────────────────────────────────────────────────────────

/// The context passed to each system during execute().
///
/// Provides controlled access to component data, mutation submission,
/// and event emission. The system may only access what it declared
/// in its SystemDefinition read/write sets.
///
/// This is the primary enforcement boundary for access control —
/// attempting to access an undeclared component returns an error.
pub trait ISystemContext {
    /// Reads a component for the given entity.
    /// Returns error if component_type_id was not declared in reads.
    /// Returns None if the entity does not have this component.
    fn get_component(
        &self,
        entity_id: EntityID,
        component_type_id: u32,
    ) -> Result<Option<&str>, XaceError>;

    /// Returns all entity IDs that have all the given component types.
    /// Results are always sorted by EntityID ASC (D3).
    fn query_entities(
        &self,
        component_type_ids: &[u32],
    ) -> Result<Vec<EntityID>, XaceError>;

    /// Submits a component mutation to the Mutation Gate.
    /// The mutation is deferred — applied after phase completion (D4).
    /// component_json must be valid JSON matching the component schema.
    fn submit_mutation(
        &mut self,
        entity_id: EntityID,
        component_type_id: u32,
        component_json: String,
    ) -> Result<(), XaceError>;

    /// Submits an entity spawn request to the Mutation Gate.
    /// The spawn is deferred — applied after phase completion (D4).
    fn submit_spawn(
        &mut self,
        actor_id: String,
        initial_components: BTreeMap<u32, String>,
    ) -> Result<(), XaceError>;

    /// Submits an entity destroy request to the Mutation Gate.
    /// The destroy is deferred — applied after phase completion (D4).
    fn submit_destroy(&mut self, entity_id: EntityID) -> Result<(), XaceError>;

    /// Emits an event to the EventBus.
    /// The event is deferred — dispatched after phase completion (D5).
    fn emit_event(&mut self, event: Event) -> Result<(), XaceError>;

    /// Returns the current simulation tick.
    fn current_tick(&self) -> Tick;

    /// Returns the next deterministic random value for this system.
    /// Seed is hash(world_seed, system_id, tick) — always reproducible (D6).
    fn next_random(&mut self) -> Result<f64, XaceError>;
}

// ── IMutationGate ─────────────────────────────────────────────────────────────

/// Deferred mutation queue — the only path for structural world state changes.
///
/// All mutations to the EntityStore and ComponentTables must go through
/// the Mutation Gate (I2, I9). Direct mutation is forbidden.
///
/// ## Four Deferred Queues
/// The gate maintains four queues applied in strict order (D4):
/// 1. spawn_queue       — entity creation with initial components
/// 2. add_queue         — component addition to existing entities
/// 3. modify_queue      — component field updates on existing entities
/// 4. remove_queue      — component removal from entities
/// 5. destroy_queue     — entity destruction
///
/// ## Application Order (D4)
/// apply_all() drains queues in this exact order:
/// spawn → add_components → modify_components → remove_components → destroy
/// No deviation from this order is permitted.
pub trait IMutationGate: Send + Sync {
    /// Queues an entity spawn with initial component data.
    /// Spawn is applied at next apply_all() call (D4).
    fn request_spawn(
        &mut self,
        actor_id: String,
        initial_components: BTreeMap<u32, String>,
    ) -> Result<(), XaceError>;

    /// Queues a component addition to an existing entity.
    /// Addition is applied at next apply_all() call (D4).
    fn request_add_component(
        &mut self,
        entity_id: EntityID,
        component_type_id: u32,
        component_json: String,
    ) -> Result<(), XaceError>;

    /// Queues a component modification on an existing entity.
    /// Modification is applied at next apply_all() call (D4).
    fn request_modify_component(
        &mut self,
        entity_id: EntityID,
        component_type_id: u32,
        component_json: String,
    ) -> Result<(), XaceError>;

    /// Queues a component removal from an existing entity.
    /// Removal is applied at next apply_all() call (D4).
    fn request_remove_component(
        &mut self,
        entity_id: EntityID,
        component_type_id: u32,
    ) -> Result<(), XaceError>;

    /// Queues an entity destruction.
    /// Destruction is applied at next apply_all() call (D4).
    fn request_destroy(&mut self, entity_id: EntityID) -> Result<(), XaceError>;

    /// Applies all queued mutations in enforced order (D4):
    /// spawn → add → modify → remove → destroy
    ///
    /// Called by PhaseOrchestrator after each phase completes.
    /// Returns the StateDelta produced by this application batch.
    /// Returns error if any mutation fails validation.
    fn apply_all(
        &mut self,
        entity_store: &mut dyn IEntityStore,
        tick: Tick,
    ) -> Result<StateDelta, XaceError>;

    /// Returns the total number of pending mutations across all queues.
    fn pending_count(&self) -> usize;

    /// Returns true if all queues are empty.
    fn is_empty(&self) -> bool;

    /// Discards all pending mutations without applying them.
    /// Used for rollback when a transaction fails mid-application.
    fn discard_all(&mut self);
}

// ── IEntityStore ──────────────────────────────────────────────────────────────

/// Entity lifecycle manager — creates, destroys, and tracks all entities.
///
/// The EntityStore is the authoritative record of every entity that has
/// ever existed in the world. It maintains entity metadata including
/// lifecycle state, creation tick, destruction tick, and tags.
///
/// ## Global Invariant I1
/// Component tables must never contain EntityIDs not in the EntityStore.
/// The EntityStore is the source of truth for entity existence.
///
/// ## Determinism (D2, D3)
/// EntityIDs are never reused (D2). Destroyed IDs are permanently archived.
/// get_all_alive() always returns entities sorted by EntityID ASC (D3).
pub trait IEntityStore: Send + Sync {
    /// Creates a new entity and returns its unique EntityID.
    /// ID is monotonically increasing and never reused (D2).
    fn create_entity(&mut self, created_tick: Tick) -> Result<EntityID, XaceError>;

    /// Marks an entity for destruction at the given tick.
    /// Entity transitions to DestroyRequested state.
    /// Full destruction is completed by apply_destroy() after phase end.
    fn request_destroy(
        &mut self,
        entity_id: EntityID,
        tick: Tick,
    ) -> Result<(), XaceError>;

    /// Completes destruction of a DestroyRequested entity.
    /// Transitions entity to Destroyed then Archived.
    /// EntityID is permanently reserved — never regenerated (D2).
    fn apply_destroy(
        &mut self,
        entity_id: EntityID,
        tick: Tick,
    ) -> Result<(), XaceError>;

    /// Returns true if the entity exists in any non-archived state.
    fn exists(&self, entity_id: EntityID) -> bool;

    /// Returns true if the entity is currently Active.
    fn is_alive(&self, entity_id: EntityID) -> bool;

    /// Returns all alive (Active) entity IDs sorted by EntityID ASC (D3).
    /// This ordering is mandatory for deterministic system iteration.
    fn get_all_alive(&self) -> Vec<EntityID>;

    /// Returns the total count of all entities including archived.
    fn total_count(&self) -> usize;

    /// Returns the next EntityID that would be generated.
    /// Used by SnapshotEngine to capture generator state.
    fn peek_next_id(&self) -> EntityID;
}

// ── IComponentTable ───────────────────────────────────────────────────────────

/// Per-type component data storage for one component type.
///
/// Each registered component type has exactly one ComponentTable.
/// The ComponentTableStore (not a separate interface) holds all tables
/// keyed by component_type_id.
///
/// ## Determinism (D3, D11)
/// All iteration over this table must yield entities in EntityID ASC order.
/// The underlying BTreeMap<EntityID, Data> guarantees this (D3).
/// Serialization uses stable key ordering (D11).
pub trait IComponentTable: Send + Sync {
    /// Returns the component type ID this table serves.
    fn component_type_id(&self) -> u32;

    /// Adds a component instance for an entity.
    /// Returns error if the entity already has this component.
    fn add(
        &mut self,
        entity_id: EntityID,
        component_json: String,
    ) -> Result<(), XaceError>;

    /// Updates the component data for an entity.
    /// Returns error if the entity does not have this component.
    fn update(
        &mut self,
        entity_id: EntityID,
        component_json: String,
    ) -> Result<(), XaceError>;

    /// Removes the component from an entity.
    /// Returns error if the entity does not have this component.
    fn remove(&mut self, entity_id: EntityID) -> Result<(), XaceError>;

    /// Returns the component data for an entity, if present.
    fn get(&self, entity_id: EntityID) -> Option<&str>;

    /// Returns true if the entity has this component.
    fn has(&self, entity_id: EntityID) -> bool;

    /// Returns all entity IDs that have this component, sorted ASC (D3).
    fn all_entity_ids(&self) -> Vec<EntityID>;

    /// Returns the total number of component instances in this table.
    fn count(&self) -> usize;

    /// Serializes the entire table to a snapshot-compatible string.
    /// Used by SnapshotEngine — must produce identical output for
    /// identical state across all machines (D11).
    fn to_snapshot_json(&self) -> Result<String, XaceError>;
}

// ── ISnapshotEngine ───────────────────────────────────────────────────────────

/// World state capture and restore engine.
///
/// Takes deterministic snapshots of the complete world state and
/// restores them exactly. The foundation for rollback, replay,
/// network resync, and save/load.
///
/// ## Global Invariant I10
/// Snapshot restore must reconstruct world state exactly.
/// restore_snapshot(take_snapshot()) must produce a world state
/// that generates identical output on all subsequent ticks.
pub trait ISnapshotEngine: Send + Sync {
    /// Captures the complete world state at the current tick.
    ///
    /// The snapshot includes entity store, all component tables,
    /// RNG state, event queue state, and mutation queue state.
    /// The world_hash is computed and embedded in the snapshot (D9).
    ///
    /// ## Performance Note
    /// Phase 5 implements this as a deep copy initially.
    /// Copy-on-write optimization is planned for v2.
    fn take_snapshot(
        &self,
        tick: Tick,
        schema_version: &str,
        execution_plan_version: u32,
    ) -> Result<WorldSnapshot, XaceError>;

    /// Restores the world to the exact state captured in the snapshot.
    ///
    /// After restore, the EntityStore, all ComponentTables, and the
    /// RNG generator are reset to their snapshot-time values.
    /// Any state that existed after the snapshot tick is discarded.
    ///
    /// Returns error if:
    /// - Snapshot schema_version does not match current version (I7)
    /// - Snapshot is structurally invalid
    /// - World hash verification fails after restore
    fn restore_snapshot(&mut self, snapshot: &WorldSnapshot) -> Result<(), XaceError>;

    /// Stores a snapshot in the snapshot store with retention policy.
    fn store_snapshot(&mut self, snapshot: WorldSnapshot) -> Result<(), XaceError>;

    /// Retrieves a stored snapshot for the given tick.
    /// Returns None if no snapshot exists for that tick.
    fn get_snapshot(&self, tick: Tick) -> Option<&WorldSnapshot>;

    /// Returns the most recent stored snapshot.
    /// Returns None if no snapshots have been stored yet.
    fn latest_snapshot(&self) -> Option<&WorldSnapshot>;

    /// Verifies that two snapshots represent identical world state
    /// by comparing their world_hash values.
    /// Used by the DeterminismGuard for replay validation (D9, D14).
    fn verify_snapshot_match(
        &self,
        snapshot_a: &WorldSnapshot,
        snapshot_b: &WorldSnapshot,
    ) -> bool;
}

// ── IEventBus ─────────────────────────────────────────────────────────────────

/// Deterministic event dispatch system.
///
/// Systems emit events during phase execution. Events are buffered
/// and dispatched after phase completion in deterministic order (D5).
/// No event may modify state directly — all mutations via Mutation Gate (I9).
///
/// ## Deferred Dispatch (D5)
/// Events are never dispatched mid-phase. They accumulate in the
/// phase event buffer and are dispatched at phase end, sorted by
/// (creation_tick ASC, creation_phase ASC, event_id ASC).
pub trait IEventBus: Send + Sync {
    /// Queues an event for deferred dispatch at phase end.
    /// The event_id is assigned by the bus — never by the caller.
    fn emit(&mut self, event: Event) -> Result<EventId, XaceError>;

    /// Dispatches all buffered events for the current phase.
    /// Events are sorted by (tick, phase, event_id) before dispatch (D5).
    /// Called by PhaseOrchestrator after phase execution completes.
    ///
    /// Returns the number of events dispatched.
    fn dispatch_phase_events(&mut self, phase: u8) -> Result<usize, XaceError>;

    /// Registers a system to receive events of the given types.
    /// Subscriptions are static — declared at startup, never dynamic (I4).
    fn register_subscription(
        &mut self,
        system_id: String,
        event_types: Vec<EventType>,
    ) -> Result<(), XaceError>;

    /// Returns all pending events for a subscribed system.
    /// Called by the system during its execute() phase.
    fn get_events_for_system(
        &self,
        system_id: &str,
    ) -> Result<Vec<&Event>, XaceError>;

    /// Marks an event as consumed by the receiving system.
    /// Consumed events are removed at the start of the next tick.
    fn mark_consumed(&mut self, event_id: EventId) -> Result<(), XaceError>;

    /// Returns the total number of events pending in all phase buffers.
    fn pending_count(&self) -> usize;

    /// Removes all consumed events from all buffers.
    /// Called at the start of each tick during Cleanup phase.
    fn purge_consumed(&mut self);
}

/// Type alias for event IDs used in the EventBus interface.
pub type EventId = u64;

// ── IDeterminismGuard ─────────────────────────────────────────────────────────

/// Enforcement layer for all 15 XACE determinism rules (D1-D15).
///
/// The DeterminismGuard is a cross-cutting concern — it hooks into
/// every execution boundary in the runtime. Every major runtime
/// operation passes through one or more guard hooks.
///
/// ## Three Modes
/// STRICT — violation = immediate halt (production default)
/// DEV    — violation = log + continue (development only)
/// SILENT — violation = record only (testing)
///
/// ## The 15 Hooks
/// The guard exposes 6 runtime hooks covering all D-rule boundaries.
/// Additional static analysis hooks are used during code generation.
pub trait IDeterminismGuard: Send + Sync {
    /// Hook: called before each system executes.
    /// Validates system is executing in declared phase and order (D1).
    fn before_system_execute(
        &mut self,
        system_id: &str,
        phase: u8,
        tick: Tick,
    ) -> Result<(), DeterminismViolation>;

    /// Hook: called after all systems in a phase complete.
    /// Validates mutation gate is drained before next phase (D4).
    fn after_phase_complete(
        &mut self,
        phase: u8,
        tick: Tick,
    ) -> Result<(), DeterminismViolation>;

    /// Hook: called after world_hash is computed each tick.
    /// Validates hash matches replay expected hash if in replay mode (D9).
    fn validate_world_hash(
        &mut self,
        tick: Tick,
        computed_hash: &str,
        expected_hash: Option<&str>,
    ) -> Result<(), DeterminismViolation>;

    /// Hook: called when a system requests an RNG value.
    /// Validates the RNG is seeded correctly (D6).
    /// Blocks any attempt to use OS or language-native random.
    fn validate_rng_usage(
        &self,
        system_id: &str,
        tick: Tick,
    ) -> Result<(), DeterminismViolation>;

    /// Hook: called when input arrives from the engine adapter.
    /// Validates input is applied at tick boundary only (D12).
    fn validate_input_timing(
        &self,
        tick: Tick,
        is_at_boundary: bool,
    ) -> Result<(), DeterminismViolation>;

    /// Hook: called when schema version is checked against plan version.
    /// Validates versions match exactly (D10).
    fn validate_version_match(
        &self,
        runtime_schema_version: &str,
        plan_schema_version: &str,
    ) -> Result<(), DeterminismViolation>;

    /// Returns all recorded violations since last reset.
    /// Used by tests in SILENT mode to assert violation detection.
    fn recorded_violations(&self) -> &[DeterminismViolation];

    /// Clears the recorded violation log.
    /// Called between test cases in SILENT mode.
    fn clear_violations(&mut self);

    /// Returns the total number of violations recorded this session.
    fn violation_count(&self) -> usize;
}

// ── IEngineAdapter ────────────────────────────────────────────────────────────

/// Engine-side state synchronization interface (updated Audit 6).
///
/// The engine adapter is the bridge between XACE's authoritative
/// simulation state and the engine's visual representation.
///
/// ## Layer 5 Contract
/// Engine adapters are Layer 6 — they mirror state only.
/// They NEVER modify authoritative simulation state (I5, D13).
/// They receive commands (DELTA, SNAPSHOT) and send back
/// input and feedback. Nothing more.
///
/// ## Bidirectional Communication (Audit 6)
/// XACE → Engine: StateDelta (every tick), SnapshotPayload (on resync)
/// Engine → XACE: InputPacket (every tick), FeedbackPayload (every tick)
///
/// ## Visibility Queries
/// XACE writes query_pending to COMP_PERCEPTION_V1.
/// The adapter batches these and sends them to the engine.
/// Results return next tick as VISIBILITY_QUERY_RESULT feedback.
pub trait IEngineAdapter: Send + Sync {
    /// Applies a StateDelta to the engine scene.
    ///
    /// The engine creates spawned entities, updates changed components,
    /// and removes destroyed entities. Application order is enforced (D4):
    /// spawn → add_components → modify_components → remove_components → destroy
    fn apply_delta(&mut self, delta: &DeltaPayload) -> Result<(), XaceError>;

    /// Sends a full SnapshotPayload to the engine for scene reconstruction.
    ///
    /// Called on initial connection or desync recovery.
    /// The engine clears its scene and rebuilds from the snapshot.
    fn apply_snapshot(&mut self, snapshot: &SnapshotPayload) -> Result<(), XaceError>;

    /// Collects all player input generated since the last tick.
    ///
    /// Returns input packaged with the tick it was generated on (I14).
    /// Input is applied at tick boundaries only (D12).
    /// Returns empty input packet if no input this tick.
    fn collect_local_input(&mut self, tick: Tick) -> Result<Vec<u8>, XaceError>;

    /// Drains all engine feedback accumulated since the last tick.
    ///
    /// Called at the START of each tick before any phase runs (I13, Audit 6).
    /// Returns all feedback messages sorted by (generated_frame ASC, entity_id ASC).
    /// Feedback handlers write results to components via Mutation Gate.
    fn receive_feedback_batch(&mut self, tick: Tick) -> Result<FeedbackPayload, XaceError>;

    /// Sends batched visibility queries to the engine.
    ///
    /// XACE collects COMP_PERCEPTION_V1.visibility_query_pending flags
    /// each tick and sends them as a batch for the engine to raycast.
    /// Results return next tick as VISIBILITY_QUERY_RESULT feedback (I13).
    fn send_visibility_queries(
        &mut self,
        queries: Vec<VisibilityQuery>,
    ) -> Result<(), XaceError>;

    /// Sends a game event notification to the engine.
    ///
    /// Events that require engine-side response (play animation, trigger audio)
    /// are forwarded here. Engine responds via feedback next tick.
    fn send_event(&mut self, event: &Event) -> Result<(), XaceError>;

    /// Returns the adapter's connection state.
    fn is_connected(&self) -> bool;

    /// Returns the engine type this adapter targets.
    fn engine_name(&self) -> &str;
}

/// A visibility raycast query sent from XACE to the engine.
///
/// XACE writes query_pending to COMP_PERCEPTION_V1 →
/// VisibilityQueryBatcher collects these each tick →
/// send_visibility_queries() sends them in a batch →
/// Engine performs raycasts → returns results as VISIBILITY_QUERY_RESULT feedback.
#[derive(Debug, Clone)]
pub struct VisibilityQuery {
    /// The entity performing the visibility check (the observer).
    pub observer_entity_id: EntityID,

    /// The entity being checked for visibility (the target).
    pub target_entity_id: EntityID,

    /// Maximum raycast distance in world units.
    /// 0.0 means use the observer's detection_radius.
    pub max_distance: f32,
}

// ── ISaveEngine ───────────────────────────────────────────────────────────────

/// Save, load, and migration engine (Audit 7).
///
/// Manages the three-layer save system:
/// - SessionSave: active game state (WorldSnapshot — transient)
/// - ProgressSave: level, inventory, story flags (persistent)
/// - WorldSave: world changes (doors, NPCs, terrain — persistent)
///
/// ## Save Determinism (I15)
/// Same WorldSnapshot + ProgressSave must produce identical gameplay.
/// Save files carry CGS version — migrated on load if schema changed.
///
/// ## Schema Version Migration
/// Old saves carry the CGS version they were created on.
/// The SaveEngine walks the SchemaDelta chain to migrate save data
/// from the old version to the current version before loading.
pub trait ISaveEngine: Send + Sync {
    /// Saves the current world session state.
    ///
    /// Serializes WorldSnapshot deterministically (D11).
    /// Save file carries schema_version for migration on load.
    fn save_session(
        &self,
        snapshot: &WorldSnapshot,
        slot_id: &str,
    ) -> Result<(), XaceError>;

    /// Loads a previously saved world session.
    ///
    /// Validates schema_version matches current CGS version.
    /// If versions mismatch, attempts migration via SchemaDelta chain.
    /// Returns XaceError::SaveVersionMismatch if migration fails.
    fn load_session(&self, slot_id: &str) -> Result<WorldSnapshot, XaceError>;

    /// Saves persistent progress data (level, inventory, story flags).
    ///
    /// ProgressSave is separate from SessionSave — it survives
    /// session restarts and is never rolled back with snapshots.
    fn save_progress(
        &self,
        slot_id: &str,
        progress_json: &str,
    ) -> Result<(), XaceError>;

    /// Loads persistent progress data.
    fn load_progress(&self, slot_id: &str) -> Result<String, XaceError>;

    /// Saves world-state changes (doors, destructibles, NPC positions).
    ///
    /// WorldSave records changes to the game world that persist
    /// across sessions — separate from player progress.
    fn save_world_state(
        &self,
        slot_id: &str,
        world_state_json: &str,
    ) -> Result<(), XaceError>;

    /// Loads world-state changes.
    fn load_world_state(&self, slot_id: &str) -> Result<String, XaceError>;

    /// Attempts to migrate a save file from an old CGS version.
    ///
    /// Walks the SchemaDelta chain from save_schema_version to
    /// current_schema_version applying each delta's operations.
    /// Returns the migrated WorldSnapshot or SaveVersionMismatch error.
    fn migrate_save(
        &self,
        snapshot: WorldSnapshot,
        save_schema_version: &str,
        current_schema_version: &str,
    ) -> Result<WorldSnapshot, XaceError>;

    /// Lists all available save slots with metadata.
    fn list_slots(&self) -> Result<Vec<SaveSlotInfo>, XaceError>;

    /// Deletes a save slot and all associated data.
    fn delete_slot(&mut self, slot_id: &str) -> Result<(), XaceError>;
}

/// Metadata about a save slot.
#[derive(Debug, Clone)]
pub struct SaveSlotInfo {
    /// The unique slot identifier.
    pub slot_id: String,

    /// Human-readable display name for this slot.
    pub display_name: String,

    /// The CGS version this save was created on.
    pub schema_version: String,

    /// ISO 8601 timestamp when this slot was last saved.
    pub last_saved_at: String,

    /// The simulation tick this save represents.
    pub tick: Tick,

    /// Whether a migration is available if the schema has changed.
    pub migration_available: bool,
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    /// A minimal mock implementation of ISystem for testing.
    struct MockSystem {
        id: String,
        reads: Vec<u32>,
        writes: Vec<u32>,
    }

    impl ISystem for MockSystem {
        fn system_id(&self) -> &str {
            &self.id
        }

        fn execute(
            &self,
            _context: &mut dyn ISystemContext,
        ) -> Result<(), XaceError> {
            Ok(())
        }

        fn declared_reads(&self) -> &[u32] {
            &self.reads
        }

        fn declared_writes(&self) -> &[u32] {
            &self.writes
        }
    }

    #[test]
    fn system_interface_implementable() {
        let sys = MockSystem {
            id: "sys_test".into(),
            reads: vec![1, 5],
            writes: vec![5],
        };
        assert_eq!(sys.system_id(), "sys_test");
        assert_eq!(sys.declared_reads(), &[1, 5]);
        assert_eq!(sys.declared_writes(), &[5]);
    }

    #[test]
    fn visibility_query_fields_accessible() {
        let query = VisibilityQuery {
            observer_entity_id: 1,
            target_entity_id: 2,
            max_distance: 50.0,
        };
        assert_eq!(query.observer_entity_id, 1);
        assert_eq!(query.target_entity_id, 2);
        assert_eq!(query.max_distance, 50.0);
    }

    #[test]
    fn save_slot_info_fields_accessible() {
        let slot = SaveSlotInfo {
            slot_id: "slot_001".into(),
            display_name: "My Save".into(),
            schema_version: "0.1.0".into(),
            last_saved_at: "2026-01-01T00:00:00Z".into(),
            tick: 1000,
            migration_available: false,
        };
        assert_eq!(slot.slot_id, "slot_001");
        assert_eq!(slot.tick, 1000);
        assert!(!slot.migration_available);
    }

    #[test]
    fn system_reads_and_writes_are_separate() {
        let sys = MockSystem {
            id: "sys_movement".into(),
            reads: vec![1, 6],  // TRANSFORM, INPUT
            writes: vec![1, 5], // TRANSFORM, VELOCITY
        };
        assert!(sys.declared_reads().contains(&6)); // reads INPUT
        assert!(!sys.declared_writes().contains(&6)); // does not write INPUT
        assert!(sys.declared_writes().contains(&5)); // writes VELOCITY
    }
}