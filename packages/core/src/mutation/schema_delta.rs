//! # Schema Delta
//!
//! Records the difference between two CGS versions produced by a
//! MutationTransaction. A SchemaDelta is the permanent, immutable
//! record of exactly what changed in the CGS and when.
//!
//! ## What a Schema Delta Is
//! A SchemaDelta is created after a MutationTransaction is successfully
//! committed. It captures the before/after state of the CGS version,
//! the operations that produced the change, and the resulting CGS hash.
//!
//! ## Audit Trail
//! Every committed mutation produces exactly one SchemaDelta.
//! The chain of SchemaDeltas is the complete history of a game's design.
//! The Schema Factory uses this chain for:
//! - Save file migration (old saves reference older CGS versions)
//! - Replay validation (replays reference the CGS version they were recorded on)
//! - Design Mentor context (understanding what changed recently)
//! - Rollback (reverting to a specific CGS version)
//!
//! ## Immutability
//! Once created, a SchemaDelta is never modified.
//! It is appended to the delta chain and permanently retained.
//! The CGS hash after commit is the definitive fingerprint (D11).

use serde::{Deserialize, Serialize};
use crate::mutation::dsl_operation::DslOperation;
use crate::mutation::usmc_categories::UsmcCategory;

// ── Delta Entry ───────────────────────────────────────────────────────────────

/// A single field change recorded in a SchemaDelta.
///
/// Captures the before and after value of one CGS field that was
/// modified by a MutationTransaction operation. Used by the
/// Schema Migration engine to generate migration rules for old saves.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DeltaEntry {
    /// The fully qualified path to the field that changed.
    pub target_path: String,

    /// The value before the mutation. Serialized as JSON string.
    /// Empty string if the field did not exist before (new field).
    pub value_before: String,

    /// The value after the mutation. Serialized as JSON string.
    /// Empty string if the field was deleted by this operation.
    pub value_after: String,

    /// Whether this entry represents a new field being created.
    pub is_addition: bool,

    /// Whether this entry represents a field being deleted.
    pub is_deletion: bool,
}

impl DeltaEntry {
    /// Creates a delta entry for a field modification.
    pub fn modification(
        target_path: impl Into<String>,
        value_before: impl Into<String>,
        value_after: impl Into<String>,
    ) -> Self {
        Self {
            target_path: target_path.into(),
            value_before: value_before.into(),
            value_after: value_after.into(),
            is_addition: false,
            is_deletion: false,
        }
    }

    /// Creates a delta entry for a new field being added.
    pub fn addition(
        target_path: impl Into<String>,
        value_after: impl Into<String>,
    ) -> Self {
        Self {
            target_path: target_path.into(),
            value_before: String::new(),
            value_after: value_after.into(),
            is_addition: true,
            is_deletion: false,
        }
    }

    /// Creates a delta entry for a field being deleted.
    pub fn deletion(
        target_path: impl Into<String>,
        value_before: impl Into<String>,
    ) -> Self {
        Self {
            target_path: target_path.into(),
            value_before: value_before.into(),
            value_after: String::new(),
            is_addition: false,
            is_deletion: true,
        }
    }

    /// Returns true if this entry records a pure value change
    /// (neither addition nor deletion).
    pub fn is_modification(&self) -> bool {
        !self.is_addition && !self.is_deletion
    }
}

// ── Schema Delta ──────────────────────────────────────────────────────────────

/// The immutable record of one CGS mutation event.
///
/// Created by the GDE after a MutationTransaction is successfully
/// committed to the CGS. Never modified after creation.
///
/// ## Chain Integrity
/// Each SchemaDelta references the CGS hash before and after commit.
/// The chain is valid if: delta[n].cgs_hash_after == delta[n+1].cgs_hash_before.
/// A broken chain indicates corruption or unauthorized CGS modification.
///
/// ## Migration Support (Audit 7)
/// When loading a save file built on an older CGS version, the Save System
/// walks the delta chain from the save's version to the current version
/// and applies each delta's inverse operations to migrate the save data.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SchemaDelta {
    /// Unique identifier for this delta. Matches the originating transaction ID.
    pub delta_id: String,

    /// The CGS semantic version before this mutation was applied.
    /// Format: "MAJOR.MINOR.PATCH"
    pub version_before: String,

    /// The CGS semantic version after this mutation was applied.
    /// Format: "MAJOR.MINOR.PATCH"
    pub version_after: String,

    /// The deterministic CGS hash before this mutation.
    /// Used to verify chain integrity and detect unauthorized changes.
    pub cgs_hash_before: String,

    /// The deterministic CGS hash after this mutation.
    /// Computed by the Schema Factory after commit using stable key ordering (D11).
    /// Embedded in the next ExecutionPlan for runtime validation (D10).
    pub cgs_hash_after: String,

    /// The ordered operations that produced this delta.
    /// Same operations as the originating MutationTransaction.
    /// Stored here for migration rule generation and rollback support.
    pub operations: Vec<DslOperation>,

    /// Field-level change records for each operation in this delta.
    /// Used by the Schema Migration engine to generate inverse operations.
    pub entries: Vec<DeltaEntry>,

    /// The USMC category of the originating transaction.
    pub usmc_category: UsmcCategory,

    /// Where the originating transaction came from.
    /// Preserved for audit trail completeness.
    pub source_description: String,

    /// ISO 8601 timestamp when this delta was committed.
    pub committed_at: String,

    /// Whether this delta required SGC recompilation.
    pub required_recompile: bool,
}

impl SchemaDelta {
    /// Creates a new SchemaDelta from a committed transaction.
    pub fn new(
        delta_id: impl Into<String>,
        version_before: impl Into<String>,
        version_after: impl Into<String>,
        cgs_hash_before: impl Into<String>,
        cgs_hash_after: impl Into<String>,
        operations: Vec<DslOperation>,
        usmc_category: UsmcCategory,
        source_description: impl Into<String>,
        committed_at: impl Into<String>,
        required_recompile: bool,
    ) -> Self {
        Self {
            delta_id: delta_id.into(),
            version_before: version_before.into(),
            version_after: version_after.into(),
            cgs_hash_before: cgs_hash_before.into(),
            cgs_hash_after: cgs_hash_after.into(),
            operations,
            entries: Vec::new(),
            usmc_category,
            source_description: source_description.into(),
            committed_at: committed_at.into(),
            required_recompile,
        }
    }

    /// Adds a field-level change entry to this delta.
    /// Called by the GDE as it applies each operation to the CGS.
    pub fn add_entry(&mut self, entry: DeltaEntry) {
        self.entries.push(entry);
    }

    /// Returns the number of field-level changes in this delta.
    pub fn change_count(&self) -> usize {
        self.entries.len()
    }

    /// Returns all addition entries — new fields created by this delta.
    pub fn additions(&self) -> Vec<&DeltaEntry> {
        self.entries.iter().filter(|e| e.is_addition).collect()
    }

    /// Returns all deletion entries — fields removed by this delta.
    pub fn deletions(&self) -> Vec<&DeltaEntry> {
        self.entries.iter().filter(|e| e.is_deletion).collect()
    }

    /// Returns all modification entries — fields changed by this delta.
    pub fn modifications(&self) -> Vec<&DeltaEntry> {
        self.entries.iter().filter(|e| e.is_modification()).collect()
    }

    /// Returns true if this delta is structurally valid.
    ///
    /// Checks:
    /// - delta_id is not empty
    /// - version_before and version_after are not empty
    /// - cgs_hash_before and cgs_hash_after are not empty
    /// - At least one operation exists
    /// - version_before != version_after (delta must change version)
    pub fn is_valid(&self) -> bool {
        !self.delta_id.is_empty()
            && !self.version_before.is_empty()
            && !self.version_after.is_empty()
            && !self.cgs_hash_before.is_empty()
            && !self.cgs_hash_after.is_empty()
            && !self.operations.is_empty()
            && self.version_before != self.version_after
    }

    /// Returns true if this delta links correctly to the previous delta.
    /// The previous delta's cgs_hash_after must match this delta's cgs_hash_before.
    /// Used by the Schema Factory to validate chain integrity.
    pub fn links_to_previous(&self, previous: &SchemaDelta) -> bool {
        self.cgs_hash_before == previous.cgs_hash_after
    }

    /// Returns a plain-English summary of this delta.
    /// Used by NLTL translation layer and Design Mentor.
    /// Zero technical vocabulary — describes what changed, not how.
    pub fn plain_english_summary(&self) -> String {
        let additions = self.additions().len();
        let deletions = self.deletions().len();
        let modifications = self.modifications().len();

        let mut parts = Vec::new();

        if additions > 0 {
            parts.push(format!(
                "{} thing{} added",
                additions,
                if additions == 1 { "" } else { "s" }
            ));
        }
        if modifications > 0 {
            parts.push(format!(
                "{} thing{} changed",
                modifications,
                if modifications == 1 { "" } else { "s" }
            ));
        }
        if deletions > 0 {
            parts.push(format!(
                "{} thing{} removed",
                deletions,
                if deletions == 1 { "" } else { "s" }
            ));
        }

        if parts.is_empty() {
            return "No visible changes recorded".into();
        }

        parts.join(", ")
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mutation::dsl_operation::{DslValue, TypeHint};

    fn test_operation() -> DslOperation {
        DslOperation::set(
            "modes.mode_arena.actors.actor_player.stats.move_speed",
            DslValue::Float(5.0),
            TypeHint::Float,
        )
    }

    fn test_delta() -> SchemaDelta {
        SchemaDelta::new(
            "delta-001",
            "0.1.0",
            "0.1.1",
            "hash_before_abc",
            "hash_after_xyz",
            vec![test_operation()],
            UsmcCategory::Modify,
            "ManualDsl(author=test)",
            "2026-01-01T00:00:00Z",
            false,
        )
    }

    #[test]
    fn valid_delta_passes_check() {
        assert!(test_delta().is_valid());
    }

    #[test]
    fn empty_delta_id_fails() {
        let mut delta = test_delta();
        delta.delta_id = String::new();
        assert!(!delta.is_valid());
    }

    #[test]
    fn same_version_before_after_fails() {
        let mut delta = test_delta();
        delta.version_after = delta.version_before.clone();
        assert!(!delta.is_valid());
    }

    #[test]
    fn empty_hash_fails() {
        let mut delta = test_delta();
        delta.cgs_hash_after = String::new();
        assert!(!delta.is_valid());
    }

    #[test]
    fn no_operations_fails() {
        let mut delta = test_delta();
        delta.operations.clear();
        assert!(!delta.is_valid());
    }

    #[test]
    fn add_entries_and_count() {
        let mut delta = test_delta();
        delta.add_entry(DeltaEntry::modification(
            "modes.mode_arena.actors.actor_player.stats.move_speed",
            "3.0",
            "5.0",
        ));
        delta.add_entry(DeltaEntry::addition(
            "modes.mode_arena.actors.actor_zombie.stats.health",
            "100.0",
        ));
        assert_eq!(delta.change_count(), 2);
    }

    #[test]
    fn additions_filter_works() {
        let mut delta = test_delta();
        delta.add_entry(DeltaEntry::addition("path.a", "val"));
        delta.add_entry(DeltaEntry::modification("path.b", "old", "new"));
        assert_eq!(delta.additions().len(), 1);
    }

    #[test]
    fn deletions_filter_works() {
        let mut delta = test_delta();
        delta.add_entry(DeltaEntry::deletion("path.a", "old_val"));
        delta.add_entry(DeltaEntry::modification("path.b", "old", "new"));
        assert_eq!(delta.deletions().len(), 1);
    }

    #[test]
    fn modifications_filter_works() {
        let mut delta = test_delta();
        delta.add_entry(DeltaEntry::modification("path.a", "old", "new"));
        delta.add_entry(DeltaEntry::addition("path.b", "val"));
        assert_eq!(delta.modifications().len(), 1);
    }

    #[test]
    fn chain_link_valid_when_hashes_match() {
        let delta1 = test_delta();
        let mut delta2 = test_delta();
        delta2.delta_id = "delta-002".into();
        delta2.version_before = "0.1.1".into();
        delta2.version_after = "0.1.2".into();
        delta2.cgs_hash_before = "hash_after_xyz".into();
        delta2.cgs_hash_after = "hash_after_pqr".into();
        assert!(delta2.links_to_previous(&delta1));
    }

    #[test]
    fn chain_link_invalid_when_hashes_mismatch() {
        let delta1 = test_delta();
        let mut delta2 = test_delta();
        delta2.delta_id = "delta-002".into();
        delta2.version_before = "0.1.1".into();
        delta2.version_after = "0.1.2".into();
        delta2.cgs_hash_before = "wrong_hash".into();
        delta2.cgs_hash_after = "hash_after_pqr".into();
        assert!(!delta2.links_to_previous(&delta1));
    }

    #[test]
    fn plain_english_summary_no_entries() {
        let delta = test_delta();
        assert_eq!(
            delta.plain_english_summary(),
            "No visible changes recorded"
        );
    }

    #[test]
    fn plain_english_summary_with_entries() {
        let mut delta = test_delta();
        delta.add_entry(DeltaEntry::modification("path.a", "1", "2"));
        delta.add_entry(DeltaEntry::addition("path.b", "new"));
        let summary = delta.plain_english_summary();
        assert!(summary.contains("added"));
        assert!(summary.contains("changed"));
    }

    #[test]
    fn delta_entry_modification_is_not_addition_or_deletion() {
        let entry = DeltaEntry::modification("path.x", "old", "new");
        assert!(entry.is_modification());
        assert!(!entry.is_addition);
        assert!(!entry.is_deletion);
    }

    #[test]
    fn delta_entry_addition_has_empty_before() {
        let entry = DeltaEntry::addition("path.x", "new_val");
        assert!(entry.value_before.is_empty());
        assert!(entry.is_addition);
    }

    #[test]
    fn delta_entry_deletion_has_empty_after() {
        let entry = DeltaEntry::deletion("path.x", "old_val");
        assert!(entry.value_after.is_empty());
        assert!(entry.is_deletion);
    }

    #[test]
    fn recompile_flag_stored_correctly() {
        let mut delta = test_delta();
        assert!(!delta.required_recompile);
        delta.required_recompile = true;
        assert!(delta.required_recompile);
    }
}