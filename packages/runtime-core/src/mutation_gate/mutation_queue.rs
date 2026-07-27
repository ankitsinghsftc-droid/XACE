//! # Mutation Queue
//!
//! Per-type deferred mutation queues. The MutationGate maintains five
//! queues — one per mutation operation type. All mutations submitted
//! during a phase are deferred here and applied in deterministic order at phase
//! end. MutationGate captures and restores these queues as part of its
//! apply-time atomic rollback contract.
//!
//! ## Queue Types (D4 application order)
//! 1. spawn_queue    — new entity creation with initial components
//! 2. add_queue      — component addition to existing entities
//! 3. modify_queue   — component field updates on existing entities
//! 4. remove_queue   — component removal from entities
//! 5. destroy_queue  — entity destruction
//!
//! ## Deferred Application (D4)
//! Systems never modify world state directly. They submit requests
//! to these queues during phase execution. The PhaseOrchestrator
//! calls MutationGate.apply_all() after each phase completes.
//!
//! ## Ordering Within Each Queue
//! Within each queue, operations are applied in submission order.
//! The MutationValidator pre-validates before enqueueing to prevent
//! invalid operations from reaching apply time.

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use xace_core::entity_id::EntityID;

// ── Spawn Request ─────────────────────────────────────────────────────────────

/// A request to spawn a new entity with initial component data.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SpawnRequest {
    /// The actor definition ID this entity is spawned from.
    /// Empty string if spawned without a blueprint.
    pub actor_id: String,

    /// Initial component data keyed by component_type_id.
    /// BTreeMap guarantees deterministic processing order (D11).
    pub initial_components: BTreeMap<u32, String>,

    /// The tick on which this spawn was requested.
    pub requested_tick: u64,
}

// ── Component Add Request ─────────────────────────────────────────────────────

/// A request to add a component to an existing entity.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ComponentAddRequest {
    pub entity_id: EntityID,
    pub component_type_id: u32,
    pub component_json: String,
    pub requested_tick: u64,
}

// ── Component Modify Request ──────────────────────────────────────────────────

/// A request to update a component on an existing entity.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ComponentModifyRequest {
    pub entity_id: EntityID,
    pub component_type_id: u32,
    pub component_json: String,
    pub requested_tick: u64,
}

// ── Component Remove Request ──────────────────────────────────────────────────

/// A request to remove a component from an entity.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ComponentRemoveRequest {
    pub entity_id: EntityID,
    pub component_type_id: u32,
    pub requested_tick: u64,
}

// ── Destroy Request ───────────────────────────────────────────────────────────

/// A request to destroy an entity.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DestroyRequest {
    pub entity_id: EntityID,
    pub requested_tick: u64,
}

// ── Mutation Queues ───────────────────────────────────────────────────────────

/// All five deferred mutation queues for one phase.
///
/// Queues accumulate during phase execution.
/// Applied in strict order by MutationGate.apply_all() (D4).
#[derive(Clone, Default, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct MutationQueues {
    /// Queue 1 — entity spawns (applied first)
    pub spawn_queue: Vec<SpawnRequest>,

    /// Queue 2 — component additions (applied second)
    pub add_queue: Vec<ComponentAddRequest>,

    /// Queue 3 — component modifications (applied third)
    pub modify_queue: Vec<ComponentModifyRequest>,

    /// Queue 4 — component removals (applied fourth)
    pub remove_queue: Vec<ComponentRemoveRequest>,

    /// Queue 5 — entity destructions (applied last)
    pub destroy_queue: Vec<DestroyRequest>,
}

impl MutationQueues {
    pub fn new() -> Self {
        Self::default()
    }

    /// Returns the total number of pending mutations across all queues.
    pub fn total_pending(&self) -> usize {
        self.spawn_queue.len()
            + self.add_queue.len()
            + self.modify_queue.len()
            + self.remove_queue.len()
            + self.destroy_queue.len()
    }

    /// Returns true if all queues are empty.
    pub fn is_empty(&self) -> bool {
        self.spawn_queue.is_empty()
            && self.add_queue.is_empty()
            && self.modify_queue.is_empty()
            && self.remove_queue.is_empty()
            && self.destroy_queue.is_empty()
    }

    /// Clears all queues without applying them.
    /// Atomic apply-time rollback restores the captured queue image before
    /// reporting failure; callers may still explicitly discard a failed batch.
    pub fn discard_all(&mut self) {
        self.spawn_queue.clear();
        self.add_queue.clear();
        self.modify_queue.clear();
        self.remove_queue.clear();
        self.destroy_queue.clear();
    }

    /// Returns counts per queue for debugging.
    pub fn counts(&self) -> (usize, usize, usize, usize, usize) {
        (
            self.spawn_queue.len(),
            self.add_queue.len(),
            self.modify_queue.len(),
            self.remove_queue.len(),
            self.destroy_queue.len(),
        )
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn new_queues_are_empty() {
        let q = MutationQueues::new();
        assert!(q.is_empty());
        assert_eq!(q.total_pending(), 0);
    }

    #[test]
    fn total_pending_sums_all_queues() {
        let mut q = MutationQueues::new();
        q.spawn_queue.push(SpawnRequest {
            actor_id: "actor_player".into(),
            initial_components: BTreeMap::new(),
            requested_tick: 0,
        });
        q.add_queue.push(ComponentAddRequest {
            entity_id: 1,
            component_type_id: 1,
            component_json: "{}".into(),
            requested_tick: 0,
        });
        q.destroy_queue.push(DestroyRequest {
            entity_id: 2,
            requested_tick: 0,
        });
        assert_eq!(q.total_pending(), 3);
    }

    #[test]
    fn discard_all_clears_queues() {
        let mut q = MutationQueues::new();
        q.spawn_queue.push(SpawnRequest {
            actor_id: "test".into(),
            initial_components: BTreeMap::new(),
            requested_tick: 0,
        });
        q.destroy_queue.push(DestroyRequest {
            entity_id: 1,
            requested_tick: 0,
        });
        q.discard_all();
        assert!(q.is_empty());
        assert_eq!(q.total_pending(), 0);
    }

    #[test]
    fn counts_returns_correct_tuple() {
        let mut q = MutationQueues::new();
        q.spawn_queue.push(SpawnRequest {
            actor_id: "a".into(),
            initial_components: BTreeMap::new(),
            requested_tick: 0,
        });
        q.modify_queue.push(ComponentModifyRequest {
            entity_id: 1,
            component_type_id: 1,
            component_json: "{}".into(),
            requested_tick: 0,
        });
        q.modify_queue.push(ComponentModifyRequest {
            entity_id: 2,
            component_type_id: 1,
            component_json: "{}".into(),
            requested_tick: 0,
        });
        let (s, a, m, r, d) = q.counts();
        assert_eq!((s, a, m, r, d), (1, 0, 2, 0, 0));
    }
}
