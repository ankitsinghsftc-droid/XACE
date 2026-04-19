//! # World Snapshot
//!
//! A complete, deterministic capture of the entire world state at a
//! specific simulation tick. Used for rollback, replay, save/load,
//! network resync, and determinism validation.
//!
//! ## What a WorldSnapshot Is
//! A WorldSnapshot is a point-in-time freeze of everything the runtime
//! needs to reconstruct the world exactly as it was at tick N:
//! - Every entity and its state
//! - Every component and its field values
//! - The RNG state for every system
//! - The event queue state
//! - The mutation queue state
//! - Schema and execution plan version markers
//!
//! ## Global Invariant I10
//! Snapshot restore must reconstruct world state exactly.
//! Given identical snapshot + identical ExecutionPlan, the runtime
//! must produce identical output on every subsequent tick.
//! This is what makes replay, rollback, and network resync possible.
//!
//! ## Determinism (D9, D11)
//! The world_hash is computed after every tick from the snapshot content.
//! Same world state = same hash, always, on any machine.
//! Stable key ordering and fixed precision are mandatory (D11).
//! Floating point values are serialized with fixed decimal places.
//!
//! ## Save System (Audit 7)
//! WorldSnapshot is the SessionSave layer — the active game state.
//! ProgressSave and WorldSave are built on top of WorldSnapshot.
//! The Save Engine serializes WorldSnapshot to disk deterministically.
//!
//! ## Snapshot vs StateDelta
//! StateDelta = what changed this tick (minimal, for engine sync)
//! WorldSnapshot = complete world state (full, for rollback/replay)

use std::collections::BTreeMap;
use serde::{Deserialize, Serialize};
use crate::entity_id::EntityID;
use crate::entity_state::EntityState;
use crate::entity_metadata::Tick;

// ── Entity Store Snapshot ─────────────────────────────────────────────────────

/// Snapshot of a single entity's identity and lifecycle state.
///
/// Captures the minimal entity record needed to restore the EntityStore.
/// Component data is stored separately in ComponentTablesSnapshot.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct EntityRecord {
    /// The entity's unique ID. Immutable after creation.
    pub entity_id: EntityID,

    /// The entity's current lifecycle state.
    pub state: EntityState,

    /// The tick on which this entity was created.
    pub created_tick: Tick,

    /// The tick on which this entity was destroyed.
    /// u64::MAX if still alive.
    pub destroyed_tick: Tick,

    /// Sorted tags from COMP_IDENTITY_V1.
    /// Duplicated here for fast snapshot restoration without
    /// querying the component table.
    pub tags: Vec<String>,
}

impl EntityRecord {
    pub fn new(
        entity_id: EntityID,
        state: EntityState,
        created_tick: Tick,
    ) -> Self {
        Self {
            entity_id,
            state,
            created_tick,
            destroyed_tick: u64::MAX,
            tags: Vec::new(),
        }
    }
}

/// Snapshot of the entire EntityStore.
///
/// Contains all entity records — alive, destroyed, and archived.
/// Archived entities are included to maintain ID reservation integrity (D2).
/// Records are stored in EntityID ascending order (D3).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct EntityStoreSnapshot {
    /// All entity records sorted by EntityID ASC (D3).
    /// Includes alive, disabled, destroyed, and archived entities.
    pub entities: Vec<EntityRecord>,

    /// The next EntityID the generator would produce.
    /// Restored into EntityIdGenerator on snapshot restore
    /// to prevent ID collision with previously existing entities (D2).
    pub next_entity_id: EntityID,
}

impl EntityStoreSnapshot {
    pub fn empty() -> Self {
        Self {
            entities: Vec::new(),
            next_entity_id: 1,
        }
    }

    /// Returns the total number of entity records in this snapshot.
    pub fn entity_count(&self) -> usize {
        self.entities.len()
    }

    /// Returns the count of entities in Active state.
    pub fn alive_count(&self) -> usize {
        self.entities
            .iter()
            .filter(|e| matches!(e.state, EntityState::Active))
            .count()
    }
}

// ── Component Tables Snapshot ─────────────────────────────────────────────────

/// Snapshot of one component table — all instances of one component type.
///
/// Maps EntityID → serialized component data for one component type.
/// BTreeMap guarantees EntityID ascending iteration order (D3).
/// Component data is serialized as JSON with stable key ordering (D11).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ComponentTableSnapshot {
    /// The component type ID this table covers.
    pub component_type_id: u32,

    /// The canonical component type name.
    pub component_type_name: String,

    /// EntityID → serialized component JSON.
    /// BTreeMap guarantees EntityID ascending order (D3).
    /// JSON keys within each component are sorted alphabetically (D11).
    pub rows: BTreeMap<EntityID, String>,
}

impl ComponentTableSnapshot {
    pub fn new(
        component_type_id: u32,
        component_type_name: impl Into<String>,
    ) -> Self {
        Self {
            component_type_id,
            component_type_name: component_type_name.into(),
            rows: BTreeMap::new(),
        }
    }

    /// Returns the number of component instances in this table.
    pub fn row_count(&self) -> usize {
        self.rows.len()
    }

    /// Returns the serialized component data for a specific entity.
    pub fn get(&self, entity_id: EntityID) -> Option<&str> {
        self.rows.get(&entity_id).map(|s| s.as_str())
    }

    /// Inserts or updates a component row.
    pub fn set(&mut self, entity_id: EntityID, component_json: impl Into<String>) {
        self.rows.insert(entity_id, component_json.into());
    }
}

/// Snapshot of all component tables in the runtime.
///
/// Contains one ComponentTableSnapshot per registered component type
/// that has at least one entity instance. Empty component tables
/// are not included — they add no information.
///
/// BTreeMap keyed by component_type_id guarantees deterministic
/// iteration order across all component types (D11).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ComponentTablesSnapshot {
    /// component_type_id → ComponentTableSnapshot.
    /// BTreeMap guarantees ascending type_id iteration order (D11).
    pub tables: BTreeMap<u32, ComponentTableSnapshot>,
}

impl ComponentTablesSnapshot {
    pub fn empty() -> Self {
        Self {
            tables: BTreeMap::new(),
        }
    }

    /// Returns the table for a specific component type, if present.
    pub fn get_table(&self, type_id: u32) -> Option<&ComponentTableSnapshot> {
        self.tables.get(&type_id)
    }

    /// Inserts or replaces a component table snapshot.
    pub fn set_table(&mut self, snapshot: ComponentTableSnapshot) {
        self.tables.insert(snapshot.component_type_id, snapshot);
    }

    /// Returns the total number of component instances across all tables.
    pub fn total_row_count(&self) -> usize {
        self.tables.values().map(|t| t.row_count()).sum()
    }

    /// Returns the number of component types represented.
    pub fn table_count(&self) -> usize {
        self.tables.len()
    }
}

// ── RNG State ─────────────────────────────────────────────────────────────────

/// The complete state of the deterministic RNG at snapshot time.
///
/// Every system has its own RNG stream seeded by hash(world_seed, system_id, tick).
/// To restore deterministic behavior after a snapshot restore, the RNG
/// state for every active system must be captured and restored exactly.
///
/// ## Determinism Rule D6
/// DeterministicRNG only. seed=hash(world_seed, system_id, tick).
/// No OS/language RNG. The RNG interceptor blocks any non-deterministic
/// random calls and raises a DeterminismViolation error.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RngState {
    /// The world seed used to initialize all system RNG streams.
    /// Constant for the lifetime of a world session.
    /// Set at world genesis and never changed.
    pub world_seed: u64,

    /// Current stream positions for each system's RNG.
    /// BTreeMap<system_id, stream_position> — sorted for determinism (D11).
    /// stream_position is the number of values consumed from this stream.
    pub stream_positions: BTreeMap<String, u64>,
}

impl RngState {
    /// Creates an initial RNG state with the given world seed.
    /// All stream positions start at zero.
    pub fn new(world_seed: u64) -> Self {
        Self {
            world_seed,
            stream_positions: BTreeMap::new(),
        }
    }

    /// Records the current stream position for a system.
    pub fn set_stream_position(&mut self, system_id: &str, position: u64) {
        self.stream_positions.insert(system_id.to_string(), position);
    }

    /// Returns the stream position for a system, or 0 if not yet recorded.
    pub fn get_stream_position(&self, system_id: &str) -> u64 {
        self.stream_positions
            .get(system_id)
            .copied()
            .unwrap_or(0)
    }
}

// ── Event Queue State ─────────────────────────────────────────────────────────

/// Snapshot of the EventBus state at a specific tick.
///
/// Captures all pending events that have been emitted but not yet
/// dispatched. On snapshot restore, these events are re-inserted
/// into the EventBus so dispatch continues correctly.
///
/// Events are sorted by (tick, phase, event_id) — same sort order
/// as the EventDispatcher uses (D5).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct EventQueueState {
    /// Pending events serialized as JSON, sorted by (tick, phase, event_id).
    /// Each entry is a serialized EventComponent.
    pub pending_events: Vec<String>,

    /// The next event_id the EventBus would assign.
    /// Restored to prevent event_id collision after snapshot restore.
    pub next_event_id: u64,
}

impl EventQueueState {
    pub fn empty() -> Self {
        Self {
            pending_events: Vec::new(),
            next_event_id: 1,
        }
    }

    /// Returns the number of pending events.
    pub fn pending_count(&self) -> usize {
        self.pending_events.len()
    }

    /// Returns true if there are no pending events.
    pub fn is_empty(&self) -> bool {
        self.pending_events.is_empty()
    }
}

// ── Mutation Queue State ──────────────────────────────────────────────────────

/// Snapshot of the MutationGate's deferred queue state.
///
/// Captures any mutations that were submitted but not yet applied
/// when the snapshot was taken. On restore, these mutations are
/// re-queued for application at the next phase boundary.
///
/// In normal operation this is usually empty — snapshots are taken
/// at tick boundaries when all mutations have been applied.
/// Populated only when snapshots are taken mid-phase (rare).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MutationQueueState {
    /// Pending spawn requests serialized as JSON.
    pub pending_spawns: Vec<String>,

    /// Pending component additions serialized as JSON.
    pub pending_additions: Vec<String>,

    /// Pending component modifications serialized as JSON.
    pub pending_modifications: Vec<String>,

    /// Pending component removals serialized as JSON.
    pub pending_removals: Vec<String>,

    /// Pending entity destroy requests serialized as JSON.
    pub pending_destroys: Vec<String>,
}

impl MutationQueueState {
    pub fn empty() -> Self {
        Self {
            pending_spawns: Vec::new(),
            pending_additions: Vec::new(),
            pending_modifications: Vec::new(),
            pending_removals: Vec::new(),
            pending_destroys: Vec::new(),
        }
    }

    /// Returns true if all queues are empty.
    /// Normal state at tick boundaries.
    pub fn is_empty(&self) -> bool {
        self.pending_spawns.is_empty()
            && self.pending_additions.is_empty()
            && self.pending_modifications.is_empty()
            && self.pending_removals.is_empty()
            && self.pending_destroys.is_empty()
    }

    /// Returns total count of pending mutations across all queues.
    pub fn total_pending(&self) -> usize {
        self.pending_spawns.len()
            + self.pending_additions.len()
            + self.pending_modifications.len()
            + self.pending_removals.len()
            + self.pending_destroys.len()
    }
}

// ── World Snapshot ────────────────────────────────────────────────────────────

/// A complete, deterministic capture of the entire world state.
///
/// The single most important data structure for runtime correctness.
/// Everything needed to reconstruct the world exactly is here.
///
/// ## Restore Guarantee (I10)
/// Given WorldSnapshot S taken at tick T:
/// restore(S) + run(ExecutionPlan) must produce identical output
/// to the original run from tick T onward, on any machine, forever.
///
/// ## Hashing (D9)
/// world_hash is computed from the serialized snapshot content
/// using stable key ordering and fixed float precision (D11).
/// hash(entity_store + component_tables + rng_state + tick) must
/// be identical for identical world states across all machines.
///
/// ## Schema Version Lock (D10, I7)
/// A snapshot taken on schema version "0.2.1" can only be restored
/// on a runtime also running schema version "0.2.1".
/// Version mismatch triggers SaveVersionMismatch error →
/// migration attempt → warn if migration fails.
///
/// ## Engine Feedback (Audit 6, I13)
/// Engine feedback is NOT included in WorldSnapshot.
/// Feedback is transient — it arrives from the engine each tick
/// and is processed at the tick boundary. It is never part of
/// the authoritative simulation state.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorldSnapshot {
    /// The simulation tick this snapshot was taken at.
    /// Immutable after creation.
    pub tick: Tick,

    /// Real time in seconds at snapshot time.
    /// Derived from tick × (1.0 / simulation_rate).
    /// Informational only — runtime always uses tick, never time_seconds.
    pub time_seconds: f64,

    /// The CGS semantic version active when this snapshot was taken.
    /// Must match current CGS version on restore (I7, D10).
    pub schema_version: String,

    /// The ExecutionPlan version active when this snapshot was taken.
    /// Must match current plan version on restore (I7, D10).
    pub execution_plan_version: u32,

    /// The CGS hash active when this snapshot was taken.
    /// Cross-referenced with CGS metadata.cgs_hash on restore (D10).
    pub cgs_hash: String,

    /// Complete state of the EntityStore at this tick.
    pub entity_store_snapshot: EntityStoreSnapshot,

    /// Complete state of all component tables at this tick.
    pub component_tables_snapshot: ComponentTablesSnapshot,

    /// Complete RNG state for all systems at this tick.
    pub rng_state: RngState,

    /// EventBus pending queue state at this tick.
    pub event_queue_state: EventQueueState,

    /// MutationGate pending queue state at this tick.
    /// Usually empty at tick boundaries.
    pub mutation_queue_state: MutationQueueState,

    /// Deterministic hash of this snapshot's entire content.
    /// Computed by the DeterminismGuard after every tick (D9).
    /// Same world state = same hash, always, on any machine.
    pub world_hash: String,

    /// Whether this snapshot was taken at a clean tick boundary.
    /// True = all mutations applied, all events dispatched.
    /// False = mid-phase snapshot (rare, used for debugging only).
    pub is_clean: bool,
}

impl WorldSnapshot {
    /// Creates a new WorldSnapshot with all required fields.
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        tick: Tick,
        time_seconds: f64,
        schema_version: impl Into<String>,
        execution_plan_version: u32,
        cgs_hash: impl Into<String>,
        entity_store_snapshot: EntityStoreSnapshot,
        component_tables_snapshot: ComponentTablesSnapshot,
        rng_state: RngState,
        event_queue_state: EventQueueState,
        mutation_queue_state: MutationQueueState,
        world_hash: impl Into<String>,
    ) -> Self {
        Self {
            tick,
            time_seconds,
            schema_version: schema_version.into(),
            execution_plan_version,
            cgs_hash: cgs_hash.into(),
            entity_store_snapshot,
            component_tables_snapshot,
            rng_state,
            event_queue_state,
            mutation_queue_state,
            world_hash: world_hash.into(),
            is_clean: true,
        }
    }

    /// Creates an empty WorldSnapshot for a new world at tick 0.
    /// Used by the Game Genesis Engine when creating a new game session.
    pub fn empty(
        schema_version: impl Into<String>,
        execution_plan_version: u32,
        world_seed: u64,
    ) -> Self {
        Self {
            tick: 0,
            time_seconds: 0.0,
            schema_version: schema_version.into(),
            execution_plan_version,
            cgs_hash: String::new(),
            entity_store_snapshot: EntityStoreSnapshot::empty(),
            component_tables_snapshot: ComponentTablesSnapshot::empty(),
            rng_state: RngState::new(world_seed),
            event_queue_state: EventQueueState::empty(),
            mutation_queue_state: MutationQueueState::empty(),
            world_hash: String::new(),
            is_clean: true,
        }
    }

    /// Returns the total number of alive entities in this snapshot.
    pub fn alive_entity_count(&self) -> usize {
        self.entity_store_snapshot.alive_count()
    }

    /// Returns the total number of component instances across all tables.
    pub fn total_component_count(&self) -> usize {
        self.component_tables_snapshot.total_row_count()
    }

    /// Returns true if this snapshot has no entities.
    pub fn is_world_empty(&self) -> bool {
        self.entity_store_snapshot.entity_count() == 0
    }

    /// Returns true if the mutation queue is clean at this snapshot.
    /// A clean mutation queue means all mutations were applied before
    /// the snapshot was taken — the normal case at tick boundaries.
    pub fn has_pending_mutations(&self) -> bool {
        !self.mutation_queue_state.is_empty()
    }

    /// Returns true if there are pending events in the event queue.
    pub fn has_pending_events(&self) -> bool {
        !self.event_queue_state.is_empty()
    }

    /// Validates this snapshot for structural integrity.
    ///
    /// Checks:
    /// - schema_version is not empty
    /// - execution_plan_version >= 1
    /// - world_hash is not empty (must be computed before validation)
    /// - entity_store next_entity_id > 0
    /// - All entity IDs in component tables exist in entity_store
    ///
    /// Full content validation is performed by the SnapshotEngine (Phase 5).
    pub fn validate(&self) -> Result<(), String> {
        if self.schema_version.is_empty() {
            return Err("WorldSnapshot schema_version must not be empty".into());
        }

        if self.execution_plan_version == 0 {
            return Err(
                "WorldSnapshot execution_plan_version must be >= 1".into()
            );
        }

        if self.world_hash.is_empty() {
            return Err(
                "WorldSnapshot world_hash must not be empty — \
                 compute hash before calling validate()"
                    .into(),
            );
        }

        if self.entity_store_snapshot.next_entity_id == 0 {
            return Err(
                "WorldSnapshot entity_store next_entity_id must be > 0 — \
                 NULL_ENTITY_ID (0) must never be generated (D2)"
                    .into(),
            );
        }

        // Verify all entity IDs in component tables exist in entity store
        let entity_ids: std::collections::HashSet<EntityID> = self
            .entity_store_snapshot
            .entities
            .iter()
            .map(|e| e.entity_id)
            .collect();

        for (type_id, table) in &self.component_tables_snapshot.tables {
            for entity_id in table.rows.keys() {
                if !entity_ids.contains(entity_id) {
                    return Err(format!(
                        "WorldSnapshot component table {} contains EntityID {} \
                         not present in EntityStore — violates I1",
                        type_id, entity_id
                    ));
                }
            }
        }

        Ok(())
    }

    /// Returns true if this snapshot is compatible with the given
    /// schema version and execution plan version.
    /// Used by the runtime before restoring a snapshot (I7, D10).
    pub fn is_compatible(
        &self,
        schema_version: &str,
        execution_plan_version: u32,
    ) -> bool {
        self.schema_version == schema_version
            && self.execution_plan_version == execution_plan_version
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn test_snapshot() -> WorldSnapshot {
        let mut snapshot = WorldSnapshot::empty("0.1.0", 1, 12345);
        snapshot.world_hash = "hash_abc123".into();
        snapshot.cgs_hash = "cgs_hash_xyz".into();
        snapshot
    }

    #[test]
    fn empty_snapshot_is_at_tick_zero() {
        let snap = WorldSnapshot::empty("0.1.0", 1, 42);
        assert_eq!(snap.tick, 0);
        assert_eq!(snap.time_seconds, 0.0);
    }

    #[test]
    fn empty_snapshot_has_no_entities() {
        let snap = WorldSnapshot::empty("0.1.0", 1, 42);
        assert!(snap.is_world_empty());
        assert_eq!(snap.alive_entity_count(), 0);
    }

    #[test]
    fn empty_snapshot_has_no_pending_mutations() {
        let snap = WorldSnapshot::empty("0.1.0", 1, 42);
        assert!(!snap.has_pending_mutations());
    }

    #[test]
    fn empty_snapshot_has_no_pending_events() {
        let snap = WorldSnapshot::empty("0.1.0", 1, 42);
        assert!(!snap.has_pending_events());
    }

    #[test]
    fn validate_passes_for_valid_snapshot() {
        let snap = test_snapshot();
        assert!(snap.validate().is_ok());
    }

    #[test]
    fn validate_fails_for_empty_schema_version() {
        let mut snap = test_snapshot();
        snap.schema_version = String::new();
        assert!(snap.validate().is_err());
    }

    #[test]
    fn validate_fails_for_zero_plan_version() {
        let mut snap = test_snapshot();
        snap.execution_plan_version = 0;
        assert!(snap.validate().is_err());
    }

    #[test]
    fn validate_fails_for_empty_world_hash() {
        let mut snap = WorldSnapshot::empty("0.1.0", 1, 42);
        assert!(snap.validate().is_err());
    }

    #[test]
    fn validate_fails_when_component_entity_not_in_store() {
        let mut snap = test_snapshot();
        let mut table = ComponentTableSnapshot::new(1, "COMP_TRANSFORM_V1");
        // Entity 999 does not exist in entity store
        table.set(999, "{}");
        snap.component_tables_snapshot.set_table(table);
        assert!(snap.validate().is_err());
    }

    #[test]
    fn validate_passes_when_component_entity_in_store() {
        let mut snap = test_snapshot();
        // Add entity to store
        snap.entity_store_snapshot.entities.push(EntityRecord::new(
            1,
            EntityState::Active,
            0,
        ));
        snap.entity_store_snapshot.next_entity_id = 2;
        // Add component for that entity
        let mut table = ComponentTableSnapshot::new(1, "COMP_TRANSFORM_V1");
        table.set(1, r#"{"position":{"x":0,"y":0,"z":0}}"#);
        snap.component_tables_snapshot.set_table(table);
        assert!(snap.validate().is_ok());
    }

    #[test]
    fn is_compatible_matches_version_and_plan() {
        let snap = test_snapshot();
        assert!(snap.is_compatible("0.1.0", 1));
        assert!(!snap.is_compatible("0.2.0", 1));
        assert!(!snap.is_compatible("0.1.0", 2));
    }

    #[test]
    fn rng_state_world_seed_preserved() {
        let snap = WorldSnapshot::empty("0.1.0", 1, 99999);
        assert_eq!(snap.rng_state.world_seed, 99999);
    }

    #[test]
    fn rng_stream_position_stored_and_retrieved() {
        let mut rng = RngState::new(42);
        rng.set_stream_position("sys_movement", 150);
        assert_eq!(rng.get_stream_position("sys_movement"), 150);
        assert_eq!(rng.get_stream_position("sys_missing"), 0);
    }

    #[test]
    fn entity_store_snapshot_counts_correctly() {
        let mut store = EntityStoreSnapshot::empty();
        store.entities.push(EntityRecord::new(1, EntityState::Active, 0));
        store.entities.push(EntityRecord::new(2, EntityState::Active, 0));
        store.entities.push(EntityRecord::new(3, EntityState::Archived, 5));
        assert_eq!(store.entity_count(), 3);
        assert_eq!(store.alive_count(), 2);
    }

    #[test]
    fn component_table_snapshot_get_set() {
        let mut table = ComponentTableSnapshot::new(1, "COMP_TRANSFORM_V1");
        table.set(42, r#"{"position":{"x":1.0}}"#);
        assert_eq!(table.get(42), Some(r#"{"position":{"x":1.0}}"#));
        assert_eq!(table.get(99), None);
        assert_eq!(table.row_count(), 1);
    }

    #[test]
    fn component_tables_snapshot_total_rows() {
        let mut tables = ComponentTablesSnapshot::empty();
        let mut t1 = ComponentTableSnapshot::new(1, "COMP_TRANSFORM_V1");
        t1.set(1, "{}");
        t1.set(2, "{}");
        let mut t2 = ComponentTableSnapshot::new(2, "COMP_IDENTITY_V1");
        t2.set(1, "{}");
        tables.set_table(t1);
        tables.set_table(t2);
        assert_eq!(tables.total_row_count(), 3);
        assert_eq!(tables.table_count(), 2);
    }

    #[test]
    fn event_queue_state_empty() {
        let eq = EventQueueState::empty();
        assert!(eq.is_empty());
        assert_eq!(eq.pending_count(), 0);
    }

    #[test]
    fn mutation_queue_state_empty() {
        let mq = MutationQueueState::empty();
        assert!(mq.is_empty());
        assert_eq!(mq.total_pending(), 0);
    }

    #[test]
    fn mutation_queue_with_pending_not_empty() {
        let mut mq = MutationQueueState::empty();
        mq.pending_spawns.push("spawn_request_json".into());
        assert!(!mq.is_empty());
        assert_eq!(mq.total_pending(), 1);
    }

    #[test]
    fn snapshot_is_clean_by_default() {
        let snap = WorldSnapshot::empty("0.1.0", 1, 42);
        assert!(snap.is_clean);
    }

    #[test]
    fn total_component_count_delegates_correctly() {
        let mut snap = test_snapshot();
        let mut table = ComponentTableSnapshot::new(1, "COMP_TRANSFORM_V1");
        snap.entity_store_snapshot.entities.push(
            EntityRecord::new(1, EntityState::Active, 0)
        );
        snap.entity_store_snapshot.next_entity_id = 2;
        table.set(1, "{}");
        snap.component_tables_snapshot.set_table(table);
        assert_eq!(snap.total_component_count(), 1);
    }
}