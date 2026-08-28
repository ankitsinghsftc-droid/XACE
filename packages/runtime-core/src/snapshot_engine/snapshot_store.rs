//! # Snapshot Store
//!
//! Stores WorldSnapshots keyed by tick with a configurable retention policy.
//!
//! ## Retention Policies
//! KEEP_LAST_N — keeps only the N most recent snapshots.
//!               Oldest are purged when limit exceeded.
//!               Used for real-time gameplay (rollback window).
//!
//! CHECKPOINT  — keeps snapshots at explicitly marked checkpoints only.
//!               Used for save files and replay anchors.
//!
//! KEEP_ALL    — retains every snapshot. Used for testing and replay recording.
//!               Warning: unbounded memory growth in long sessions.
//!
//! ## Determinism
//! BTreeMap<Tick, WorldSnapshot> guarantees tick-ascending iteration (D11).
//! Snapshot retrieval is deterministic — same tick always returns same snapshot.

use std::collections::BTreeMap;
use xace_core::entity_metadata::Tick;
use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::runtime::world_snapshot::WorldSnapshot;

// ── Retention Policy ──────────────────────────────────────────────────────────

/// Controls how many snapshots the store retains.
#[derive(Debug, Clone)]
pub enum RetentionPolicy {
    /// Keep only the N most recent snapshots.
    /// When a new snapshot is stored and count exceeds N,
    /// the oldest snapshot is purged.
    KeepLastN(usize),

    /// Keep only explicitly checkpointed snapshots.
    /// Non-checkpoint snapshots are discarded immediately.
    Checkpoint,

    /// Retain all snapshots — no purging.
    /// Use only for testing or short sessions.
    KeepAll,
}

// ── Snapshot Store ────────────────────────────────────────────────────────────

/// Retention-policy-aware WorldSnapshot storage.
///
/// Stores snapshots keyed by tick. Applies retention policy
/// on every store() call to prevent unbounded memory growth.
pub struct SnapshotStore {
    /// tick → WorldSnapshot. BTreeMap = tick-ascending order (D11).
    snapshots: BTreeMap<Tick, WorldSnapshot>,

    /// Which ticks are marked as checkpoints.
    checkpoint_ticks: BTreeMap<Tick, bool>,

    /// Retention policy controlling purge behavior.
    policy: RetentionPolicy,

    /// Total snapshots stored across the session (including purged).
    total_stored: u64,

    /// Total snapshots purged across the session.
    total_purged: u64,
}

impl SnapshotStore {
    /// Creates a new SnapshotStore with the given retention policy.
    pub fn new(policy: RetentionPolicy) -> Self {
        Self {
            snapshots: BTreeMap::new(),
            checkpoint_ticks: BTreeMap::new(),
            policy,
            total_stored: 0,
            total_purged: 0,
        }
    }

    /// Creates a store with KeepLastN(8) — standard gameplay rollback window.
    pub fn standard() -> Self {
        Self::new(RetentionPolicy::KeepLastN(8))
    }

    /// Creates a store with KeepAll — for testing and replay recording.
    pub fn keep_all() -> Self {
        Self::new(RetentionPolicy::KeepAll)
    }

    // ── Storage ────────────────────────────────────────────────────────────

    /// Stores a snapshot according to the retention policy.
    ///
    /// Returns error if a snapshot already exists for this tick.
    pub fn store(&mut self, snapshot: WorldSnapshot) -> Result<(), XaceError> {
        let tick = snapshot.tick;

        if self.snapshots.contains_key(&tick) {
            return Err(XaceError::ValidationFailure {
                message: format!(
                    "Snapshot already exists for tick {} — \
                     cannot overwrite existing snapshot",
                    tick
                ),
                context: ErrorContext::new("SnapshotStore", "store"),
                rule_violated: "no_snapshot_overwrite".into(),
                failed_path: format!("tick:{}", tick),
            });
        }

        match &self.policy {
            RetentionPolicy::Checkpoint => {
                // Only store if this tick is a checkpoint
                if !self.checkpoint_ticks.contains_key(&tick) {
                    return Ok(()); // Silently discard non-checkpoint snapshots
                }
            }
            RetentionPolicy::KeepLastN(n) => {
                let max = *n;
                self.snapshots.insert(tick, snapshot);
                self.total_stored += 1;
                self.apply_keep_last_n(max);
                return Ok(());
            }
            RetentionPolicy::KeepAll => {}
        }

        self.snapshots.insert(tick, snapshot);
        self.total_stored += 1;
        Ok(())
    }

    /// Marks a tick as a checkpoint.
    ///
    /// Checkpointed ticks are never purged by KeepLastN policy.
    /// Required before store() in Checkpoint policy mode.
    pub fn mark_checkpoint(&mut self, tick: Tick) {
        self.checkpoint_ticks.insert(tick, true);
    }

    /// Returns true if the given tick is marked as a checkpoint.
    pub fn is_checkpoint(&self, tick: Tick) -> bool {
        self.checkpoint_ticks.contains_key(&tick)
    }

    // ── Retrieval ──────────────────────────────────────────────────────────

    /// Returns the snapshot for the given tick, if stored.
    pub fn get(&self, tick: Tick) -> Option<&WorldSnapshot> {
        self.snapshots.get(&tick)
    }

    /// Returns the most recent stored snapshot.
    /// Returns None if no snapshots have been stored.
    pub fn latest(&self) -> Option<&WorldSnapshot> {
        self.snapshots.values().next_back()
    }

    /// Returns the oldest stored snapshot.
    pub fn oldest(&self) -> Option<&WorldSnapshot> {
        self.snapshots.values().next()
    }

    /// Returns true if a snapshot exists for the given tick.
    pub fn has_snapshot(&self, tick: Tick) -> bool {
        self.snapshots.contains_key(&tick)
    }

    /// Returns all stored ticks in ascending order (D11).
    pub fn stored_ticks(&self) -> Vec<Tick> {
        self.snapshots.keys().copied().collect()
    }

    /// Returns the number of currently stored snapshots.
    pub fn count(&self) -> usize {
        self.snapshots.len()
    }

    /// Returns true if no snapshots are stored.
    pub fn is_empty(&self) -> bool {
        self.snapshots.is_empty()
    }

    /// Returns the nearest snapshot at or before the given tick.
    ///
    /// Used by the rollback system to find the best restore point
    /// when rolling back to an arbitrary tick.
    pub fn nearest_before_or_at(&self, tick: Tick) -> Option<&WorldSnapshot> {
        self.snapshots
            .range(..=tick)
            .next_back()
            .map(|(_, snap)| snap)
    }

    // ── Purge ──────────────────────────────────────────────────────────────

    /// Manually purges snapshots older than the given tick.
    ///
    /// Checkpoint-marked snapshots are never purged.
    pub fn purge_before(&mut self, tick: Tick) {
        let to_remove: Vec<Tick> = self
            .snapshots
            .range(..tick)
            .filter(|(t, _)| !self.checkpoint_ticks.contains_key(t))
            .map(|(t, _)| *t)
            .collect();

        for t in to_remove {
            self.snapshots.remove(&t);
            self.total_purged += 1;
        }
    }

    /// Manually purges snapshots at or after the given tick.
    ///
    /// Used by clean-boundary rollback before deterministic resimulation so
    /// future rollback anchors are rebuilt from the corrected timeline.
    pub fn purge_at_or_after(&mut self, tick: Tick) {
        let to_remove: Vec<Tick> = self.snapshots.range(tick..).map(|(t, _)| *t).collect();

        for t in to_remove {
            self.snapshots.remove(&t);
            self.checkpoint_ticks.remove(&t);
            self.total_purged += 1;
        }
    }

    /// Clears all stored snapshots. Used for snapshot restore.
    pub fn clear(&mut self) {
        self.total_purged += self.snapshots.len() as u64;
        self.snapshots.clear();
        self.checkpoint_ticks.clear();
    }

    // ── Stats ──────────────────────────────────────────────────────────────

    /// Returns total snapshots stored this session (including purged).
    pub fn total_stored(&self) -> u64 {
        self.total_stored
    }

    /// Returns total snapshots purged this session.
    pub fn total_purged(&self) -> u64 {
        self.total_purged
    }

    // ── Internal ───────────────────────────────────────────────────────────

    fn apply_keep_last_n(&mut self, max: usize) {
        while self.snapshots.len() > max {
            // Find oldest non-checkpoint tick to remove
            let oldest_non_checkpoint = self
                .snapshots
                .keys()
                .find(|t| !self.checkpoint_ticks.contains_key(t))
                .copied();

            match oldest_non_checkpoint {
                Some(tick) => {
                    self.snapshots.remove(&tick);
                    self.total_purged += 1;
                }
                None => break, // All remaining are checkpoints — stop purging
            }
        }
    }
}

impl Default for SnapshotStore {
    fn default() -> Self {
        Self::standard()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::runtime::world_snapshot::WorldSnapshot;

    fn snap(tick: u64) -> WorldSnapshot {
        WorldSnapshot::minimal(tick, "0.1.0".into(), "".into())
    }

    #[test]
    fn store_and_retrieve() {
        let mut store = SnapshotStore::keep_all();
        store.store(snap(10)).unwrap();
        assert!(store.has_snapshot(10));
        assert_eq!(store.get(10).unwrap().tick, 10);
    }

    #[test]
    fn duplicate_tick_rejected() {
        let mut store = SnapshotStore::keep_all();
        store.store(snap(10)).unwrap();
        assert!(store.store(snap(10)).is_err());
    }

    #[test]
    fn latest_returns_highest_tick() {
        let mut store = SnapshotStore::keep_all();
        store.store(snap(10)).unwrap();
        store.store(snap(5)).unwrap();
        store.store(snap(20)).unwrap();
        assert_eq!(store.latest().unwrap().tick, 20);
    }

    #[test]
    fn oldest_returns_lowest_tick() {
        let mut store = SnapshotStore::keep_all();
        store.store(snap(10)).unwrap();
        store.store(snap(5)).unwrap();
        store.store(snap(20)).unwrap();
        assert_eq!(store.oldest().unwrap().tick, 5);
    }

    #[test]
    fn keep_last_n_purges_oldest() {
        let mut store = SnapshotStore::new(RetentionPolicy::KeepLastN(3));
        for tick in 1u64..=5 {
            store.store(snap(tick)).unwrap();
        }
        assert_eq!(store.count(), 3);
        assert!(!store.has_snapshot(1));
        assert!(!store.has_snapshot(2));
        assert!(store.has_snapshot(3));
        assert!(store.has_snapshot(4));
        assert!(store.has_snapshot(5));
    }

    #[test]
    fn keep_last_n_preserves_checkpoints() {
        let mut store = SnapshotStore::new(RetentionPolicy::KeepLastN(2));
        store.mark_checkpoint(1);
        store.store(snap(1)).unwrap();
        store.store(snap(2)).unwrap();
        store.store(snap(3)).unwrap(); // Would normally evict tick=1
                                       // tick=1 is a checkpoint — must not be purged
        assert!(store.has_snapshot(1));
    }

    #[test]
    fn checkpoint_policy_discards_non_checkpoints() {
        let mut store = SnapshotStore::new(RetentionPolicy::Checkpoint);
        store.mark_checkpoint(10);
        store.store(snap(5)).unwrap(); // Not a checkpoint — discarded
        store.store(snap(10)).unwrap(); // Checkpoint — kept
        assert!(!store.has_snapshot(5));
        assert!(store.has_snapshot(10));
    }

    #[test]
    fn nearest_before_or_at_returns_closest() {
        let mut store = SnapshotStore::keep_all();
        store.store(snap(10)).unwrap();
        store.store(snap(20)).unwrap();
        store.store(snap(30)).unwrap();
        let nearest = store.nearest_before_or_at(25);
        assert_eq!(nearest.unwrap().tick, 20);
    }

    #[test]
    fn nearest_before_or_at_exact_tick() {
        let mut store = SnapshotStore::keep_all();
        store.store(snap(10)).unwrap();
        store.store(snap(20)).unwrap();
        let nearest = store.nearest_before_or_at(20);
        assert_eq!(nearest.unwrap().tick, 20);
    }

    #[test]
    fn nearest_before_or_at_none_if_all_later() {
        let mut store = SnapshotStore::keep_all();
        store.store(snap(20)).unwrap();
        store.store(snap(30)).unwrap();
        assert!(store.nearest_before_or_at(10).is_none());
    }

    #[test]
    fn purge_before_removes_old_snapshots() {
        let mut store = SnapshotStore::keep_all();
        for tick in [5, 10, 15, 20u64] {
            store.store(snap(tick)).unwrap();
        }
        store.purge_before(15);
        assert!(!store.has_snapshot(5));
        assert!(!store.has_snapshot(10));
        assert!(store.has_snapshot(15));
        assert!(store.has_snapshot(20));
    }

    #[test]
    fn purge_before_spares_checkpoints() {
        let mut store = SnapshotStore::keep_all();
        store.mark_checkpoint(5);
        for tick in [5, 10, 15u64] {
            store.store(snap(tick)).unwrap();
        }
        store.purge_before(15);
        assert!(store.has_snapshot(5)); // Checkpoint — spared
        assert!(!store.has_snapshot(10));
    }

    #[test]
    fn stored_ticks_sorted_ascending() {
        let mut store = SnapshotStore::keep_all();
        for tick in [30, 10, 20u64] {
            store.store(snap(tick)).unwrap();
        }
        assert_eq!(store.stored_ticks(), vec![10, 20, 30]);
    }

    #[test]
    fn stats_tracked_correctly() {
        let mut store = SnapshotStore::new(RetentionPolicy::KeepLastN(2));
        for tick in 1u64..=4 {
            store.store(snap(tick)).unwrap();
        }
        assert_eq!(store.total_stored(), 4);
        assert_eq!(store.total_purged(), 2);
    }

    #[test]
    fn clear_removes_all() {
        let mut store = SnapshotStore::keep_all();
        store.store(snap(1)).unwrap();
        store.store(snap(2)).unwrap();
        store.clear();
        assert!(store.is_empty());
        assert_eq!(store.count(), 0);
    }
}
