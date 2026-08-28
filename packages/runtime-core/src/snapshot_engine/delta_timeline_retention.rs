//! Delta-compressed authoritative timeline retention for debugger scrubbing.
//!
//! X10-047 keeps a bounded scrub window without retaining a full
//! `WorldSnapshot` for every tick. The store keeps deterministic full-snapshot
//! anchors and per-tick snapshot deltas. Any retained tick reconstructs back to
//! a complete `WorldSnapshot` and validates against the canonical world hash
//! before it can be used by the runtime restore path.

use std::collections::{BTreeMap, BTreeSet};

use serde::{Deserialize, Serialize};
use xace_core::entity_id::EntityID;
use xace_core::entity_metadata::Tick;
use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::fixed_point::Fixed64;
use xace_core::runtime::world_snapshot::{
    ComponentTableSnapshot, EntityRecord, EventQueueState, MutationQueueState, RngState,
    WorldSnapshot,
};

use crate::determinism_guard::world_hasher::WorldHasher;

use super::snapshot_serializer::SnapshotSerializer;

pub const X10_047_MIN_SCRUB_TICKS: Tick = 1_000;
pub const DEFAULT_DELTA_ANCHOR_INTERVAL_TICKS: Tick = 64;
pub const DEFAULT_DELTA_TIMELINE_MAX_BYTES: usize = 64 * 1024 * 1024;
pub const DELTA_TIMELINE_STATS_SCHEMA: &str = "xace.delta_timeline_retention_stats.v1";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct DeltaTimelineRetentionConfig {
    pub max_retained_ticks: Tick,
    pub anchor_interval_ticks: Tick,
    pub max_retained_bytes: usize,
}

impl Default for DeltaTimelineRetentionConfig {
    fn default() -> Self {
        Self {
            max_retained_ticks: X10_047_MIN_SCRUB_TICKS,
            anchor_interval_ticks: DEFAULT_DELTA_ANCHOR_INTERVAL_TICKS,
            max_retained_bytes: DEFAULT_DELTA_TIMELINE_MAX_BYTES,
        }
    }
}

impl DeltaTimelineRetentionConfig {
    pub fn validate(&self) -> Result<(), XaceError> {
        if self.max_retained_ticks == 0 {
            return Err(timeline_error(
                "validate_config",
                0,
                "delta timeline max_retained_ticks must be greater than zero",
                "config.max_retained_ticks",
            ));
        }
        if self.anchor_interval_ticks == 0 {
            return Err(timeline_error(
                "validate_config",
                0,
                "delta timeline anchor_interval_ticks must be greater than zero",
                "config.anchor_interval_ticks",
            ));
        }
        if self.max_retained_bytes == 0 {
            return Err(timeline_error(
                "validate_config",
                0,
                "delta timeline max_retained_bytes must be greater than zero",
                "config.max_retained_bytes",
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DeltaTimelineRetentionStats {
    pub schema: String,
    pub oldest_tick: Option<Tick>,
    pub latest_tick: Option<Tick>,
    pub retained_ticks: usize,
    pub anchor_count: usize,
    pub delta_count: usize,
    pub retained_bytes: usize,
    pub full_snapshot_bytes: usize,
    pub max_retained_ticks: Tick,
    pub max_retained_bytes: usize,
    pub anchor_interval_ticks: Tick,
    pub total_snapshots_observed: u64,
    pub total_promoted_anchors: u64,
    pub total_pruned_entries: u64,
    pub first_entry_is_anchor: bool,
    pub contiguous_restore_chain: bool,
    pub compression_ratio_ppm: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DeltaTimelineRestoreProof {
    pub schema: String,
    pub requested_tick: Tick,
    pub anchor_tick: Tick,
    pub restored_tick: Tick,
    pub applied_delta_count: usize,
    pub expected_world_hash: String,
    pub restored_world_hash: String,
    pub retained_bytes: usize,
}

#[derive(Debug, Clone)]
pub struct DeltaCompressedTimelineRetention {
    config: DeltaTimelineRetentionConfig,
    entries: BTreeMap<Tick, TimelineEntry>,
    full_snapshot_bytes: BTreeMap<Tick, usize>,
    latest_snapshot: Option<WorldSnapshot>,
    total_snapshots_observed: u64,
    total_promoted_anchors: u64,
    total_pruned_entries: u64,
    serializer: SnapshotSerializer,
}

impl DeltaCompressedTimelineRetention {
    pub fn with_config(config: DeltaTimelineRetentionConfig) -> Result<Self, XaceError> {
        config.validate()?;
        Ok(Self {
            config,
            entries: BTreeMap::new(),
            full_snapshot_bytes: BTreeMap::new(),
            latest_snapshot: None,
            total_snapshots_observed: 0,
            total_promoted_anchors: 0,
            total_pruned_entries: 0,
            serializer: SnapshotSerializer::new(),
        })
    }

    pub fn new() -> Self {
        Self::with_config(DeltaTimelineRetentionConfig::default())
            .expect("default delta timeline retention config must be valid")
    }

    pub fn config(&self) -> DeltaTimelineRetentionConfig {
        self.config
    }

    pub fn remember_snapshot(&mut self, snapshot: WorldSnapshot) -> Result<(), XaceError> {
        let tick = snapshot.tick;
        let full_bytes = self.serialized_snapshot_len(&snapshot)?;

        if self.entries.contains_key(&tick) {
            let existing = self.restore_snapshot(tick)?;
            if existing.world_hash == snapshot.world_hash {
                return Ok(());
            }
            self.prune_at_or_after(tick)?;
        } else if self.latest_tick().is_some_and(|latest| tick <= latest) {
            self.prune_at_or_after(tick)?;
        }

        let should_anchor = self.should_store_anchor(&snapshot);
        let entry = if should_anchor {
            TimelineEntry::Anchor {
                stored_bytes: full_bytes,
                snapshot: snapshot.clone(),
            }
        } else {
            let previous = self.latest_snapshot.as_ref().ok_or_else(|| {
                timeline_error(
                    "remember_snapshot",
                    tick,
                    "delta timeline cannot encode a delta without a previous snapshot",
                    "latest_snapshot",
                )
            })?;
            let delta = SnapshotTimelineDelta::between(previous, &snapshot)?;
            let stored_bytes = serialized_delta_len(&delta)?;
            TimelineEntry::Delta {
                stored_bytes,
                delta,
            }
        };

        self.entries.insert(tick, entry);
        self.full_snapshot_bytes.insert(tick, full_bytes);
        self.latest_snapshot = Some(snapshot);
        self.total_snapshots_observed += 1;
        self.enforce_limits()?;
        Ok(())
    }

    pub fn restore_snapshot(&self, tick: Tick) -> Result<WorldSnapshot, XaceError> {
        let Some(_) = self.entries.get(&tick) else {
            return Err(timeline_error(
                "restore_snapshot",
                tick,
                format!("delta timeline does not retain tick {tick}"),
                "entries",
            ));
        };

        let anchor_tick = self.anchor_tick_for(tick)?;
        let mut restored = match self.entries.get(&anchor_tick) {
            Some(TimelineEntry::Anchor { snapshot, .. }) => snapshot.clone(),
            _ => {
                return Err(timeline_error(
                    "restore_snapshot",
                    tick,
                    format!("delta timeline anchor {anchor_tick} is missing"),
                    "entries.anchor",
                ))
            }
        };

        if anchor_tick < tick {
            for (entry_tick, entry) in self.entries.range((anchor_tick + 1)..=tick) {
                match entry {
                    TimelineEntry::Anchor { snapshot, .. } => {
                        restored = snapshot.clone();
                    }
                    TimelineEntry::Delta { delta, .. } => {
                        if *entry_tick != delta.to_tick {
                            return Err(timeline_error(
                                "restore_snapshot",
                                tick,
                                format!(
                                    "delta timeline entry key {} does not match delta target {}",
                                    entry_tick, delta.to_tick
                                ),
                                "entries.delta.to_tick",
                            ));
                        }
                        restored = delta.apply(&restored)?;
                    }
                }
            }
        }

        if restored.tick != tick {
            return Err(timeline_error(
                "restore_snapshot",
                tick,
                format!(
                    "delta timeline restored tick {} instead of requested tick {}",
                    restored.tick, tick
                ),
                "restored.tick",
            ));
        }
        Ok(restored)
    }

    pub fn restore_proof(&self, tick: Tick) -> Result<DeltaTimelineRestoreProof, XaceError> {
        let anchor_tick = self.anchor_tick_for(tick)?;
        let restored = self.restore_snapshot(tick)?;
        let applied_delta_count = if anchor_tick < tick {
            self.entries
                .range((anchor_tick + 1)..=tick)
                .filter(|(_, entry)| matches!(entry, TimelineEntry::Delta { .. }))
                .count()
        } else {
            0
        };
        Ok(DeltaTimelineRestoreProof {
            schema: "xace.delta_timeline_restore_proof.v1".to_string(),
            requested_tick: tick,
            anchor_tick,
            restored_tick: restored.tick,
            applied_delta_count,
            expected_world_hash: restored.world_hash.clone(),
            restored_world_hash: WorldHasher::compute(&restored),
            retained_bytes: self.retained_bytes(),
        })
    }

    pub fn can_restore_tick(&self, tick: Tick) -> bool {
        self.restore_snapshot(tick).is_ok()
    }

    pub fn retained_ticks(&self) -> Vec<Tick> {
        self.entries.keys().copied().collect()
    }

    pub fn oldest_tick(&self) -> Option<Tick> {
        self.entries.keys().next().copied()
    }

    pub fn latest_tick(&self) -> Option<Tick> {
        self.entries.keys().next_back().copied()
    }

    pub fn retained_bytes(&self) -> usize {
        self.entries.values().map(TimelineEntry::stored_bytes).sum()
    }

    pub fn stats(&self) -> DeltaTimelineRetentionStats {
        let full_snapshot_bytes = self.full_snapshot_bytes.values().sum::<usize>();
        let retained_bytes = self.retained_bytes();
        let compression_ratio_ppm = if full_snapshot_bytes == 0 {
            0
        } else {
            ((retained_bytes as u128 * 1_000_000u128) / full_snapshot_bytes as u128) as u64
        };
        DeltaTimelineRetentionStats {
            schema: DELTA_TIMELINE_STATS_SCHEMA.to_string(),
            oldest_tick: self.oldest_tick(),
            latest_tick: self.latest_tick(),
            retained_ticks: self.entries.len(),
            anchor_count: self.anchor_count(),
            delta_count: self.delta_count(),
            retained_bytes,
            full_snapshot_bytes,
            max_retained_ticks: self.config.max_retained_ticks,
            max_retained_bytes: self.config.max_retained_bytes,
            anchor_interval_ticks: self.config.anchor_interval_ticks,
            total_snapshots_observed: self.total_snapshots_observed,
            total_promoted_anchors: self.total_promoted_anchors,
            total_pruned_entries: self.total_pruned_entries,
            first_entry_is_anchor: self.first_entry_is_anchor(),
            contiguous_restore_chain: self.contiguous_restore_chain(),
            compression_ratio_ppm,
        }
    }

    pub fn prune_at_or_after(&mut self, tick: Tick) -> Result<(), XaceError> {
        let to_remove = self
            .entries
            .range(tick..)
            .map(|(entry_tick, _)| *entry_tick)
            .collect::<Vec<_>>();
        for entry_tick in to_remove {
            self.entries.remove(&entry_tick);
            self.full_snapshot_bytes.remove(&entry_tick);
            self.total_pruned_entries += 1;
        }
        self.refresh_latest_snapshot()
    }

    fn should_store_anchor(&self, snapshot: &WorldSnapshot) -> bool {
        let Some(previous) = self.latest_snapshot.as_ref() else {
            return true;
        };
        previous.tick.saturating_add(1) != snapshot.tick
            || snapshot.tick % self.config.anchor_interval_ticks == 0
            || previous.schema_version != snapshot.schema_version
            || previous.execution_plan_version != snapshot.execution_plan_version
            || previous.cgs_hash != snapshot.cgs_hash
    }

    fn enforce_limits(&mut self) -> Result<(), XaceError> {
        if let Some(latest) = self.latest_tick() {
            let min_tick = latest.saturating_sub(self.config.max_retained_ticks.saturating_sub(1));
            self.prune_before(min_tick)?;
        }

        while self.retained_bytes() > self.config.max_retained_bytes && self.entries.len() > 1 {
            let Some(next_tick) = self.entries.keys().nth(1).copied() else {
                break;
            };
            let before_len = self.entries.len();
            self.prune_before(next_tick)?;
            if self.entries.len() >= before_len {
                break;
            }
        }
        Ok(())
    }

    fn prune_before(&mut self, min_tick: Tick) -> Result<(), XaceError> {
        let Some(first_keep_tick) = self.entries.range(min_tick..).next().map(|(tick, _)| *tick)
        else {
            let removed = self.entries.len() as u64;
            self.entries.clear();
            self.full_snapshot_bytes.clear();
            self.latest_snapshot = None;
            self.total_pruned_entries += removed;
            return Ok(());
        };

        let first_keep_snapshot = if self.entry_is_anchor(first_keep_tick) {
            None
        } else {
            Some(self.restore_snapshot(first_keep_tick)?)
        };

        let to_remove = self
            .entries
            .range(..min_tick)
            .map(|(tick, _)| *tick)
            .collect::<Vec<_>>();
        for tick in to_remove {
            self.entries.remove(&tick);
            self.full_snapshot_bytes.remove(&tick);
            self.total_pruned_entries += 1;
        }

        if let Some(snapshot) = first_keep_snapshot {
            let stored_bytes = self.serialized_snapshot_len(&snapshot)?;
            self.entries.insert(
                first_keep_tick,
                TimelineEntry::Anchor {
                    stored_bytes,
                    snapshot,
                },
            );
            self.total_promoted_anchors += 1;
        }

        self.refresh_latest_snapshot()
    }

    fn refresh_latest_snapshot(&mut self) -> Result<(), XaceError> {
        self.latest_snapshot = match self.latest_tick() {
            Some(tick) => Some(self.restore_snapshot(tick)?),
            None => None,
        };
        Ok(())
    }

    fn anchor_tick_for(&self, tick: Tick) -> Result<Tick, XaceError> {
        self.entries
            .range(..=tick)
            .rev()
            .find_map(|(entry_tick, entry)| match entry {
                TimelineEntry::Anchor { .. } => Some(*entry_tick),
                TimelineEntry::Delta { .. } => None,
            })
            .ok_or_else(|| {
                timeline_error(
                    "anchor_tick_for",
                    tick,
                    format!("delta timeline has no full snapshot anchor for tick {tick}"),
                    "entries.anchor",
                )
            })
    }

    fn entry_is_anchor(&self, tick: Tick) -> bool {
        matches!(self.entries.get(&tick), Some(TimelineEntry::Anchor { .. }))
    }

    fn first_entry_is_anchor(&self) -> bool {
        self.oldest_tick()
            .is_none_or(|tick| self.entry_is_anchor(tick))
    }

    fn contiguous_restore_chain(&self) -> bool {
        let ticks = self.retained_ticks();
        if ticks.is_empty() {
            return true;
        }
        if !self.first_entry_is_anchor() {
            return false;
        }
        ticks
            .windows(2)
            .all(|pair| pair[0].saturating_add(1) == pair[1])
    }

    fn anchor_count(&self) -> usize {
        self.entries
            .values()
            .filter(|entry| matches!(entry, TimelineEntry::Anchor { .. }))
            .count()
    }

    fn delta_count(&self) -> usize {
        self.entries
            .values()
            .filter(|entry| matches!(entry, TimelineEntry::Delta { .. }))
            .count()
    }

    fn serialized_snapshot_len(&self, snapshot: &WorldSnapshot) -> Result<usize, XaceError> {
        self.serializer.serialize(snapshot).map(|json| json.len())
    }
}

impl Default for DeltaCompressedTimelineRetention {
    fn default() -> Self {
        Self::new()
    }
}

#[derive(Debug, Clone)]
enum TimelineEntry {
    Anchor {
        snapshot: WorldSnapshot,
        stored_bytes: usize,
    },
    Delta {
        delta: SnapshotTimelineDelta,
        stored_bytes: usize,
    },
}

impl TimelineEntry {
    fn stored_bytes(&self) -> usize {
        match self {
            Self::Anchor { stored_bytes, .. } | Self::Delta { stored_bytes, .. } => *stored_bytes,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SnapshotTimelineDelta {
    pub schema: String,
    pub from_tick: Tick,
    pub to_tick: Tick,
    pub expected_from_hash: String,
    pub expected_to_hash: String,
    pub time_seconds: Fixed64,
    pub schema_version: String,
    pub execution_plan_version: u32,
    pub cgs_hash: String,
    pub is_clean: bool,
    pub next_entity_id: EntityID,
    pub entity_record_changes: BTreeMap<EntityID, Option<EntityRecord>>,
    pub removed_component_tables: Vec<u32>,
    pub component_table_changes: BTreeMap<u32, ComponentTableDelta>,
    pub rng_state: RngState,
    pub event_queue_state: EventQueueState,
    pub mutation_queue_state: MutationQueueState,
}

impl SnapshotTimelineDelta {
    pub fn between(before: &WorldSnapshot, after: &WorldSnapshot) -> Result<Self, XaceError> {
        if before.world_hash.is_empty() || after.world_hash.is_empty() {
            return Err(timeline_error(
                "delta_between",
                after.tick,
                "snapshot timeline delta requires canonical world_hash values",
                "world_hash",
            ));
        }
        if before.tick.saturating_add(1) != after.tick {
            return Err(timeline_error(
                "delta_between",
                after.tick,
                format!(
                    "snapshot timeline delta requires consecutive ticks, got {} -> {}",
                    before.tick, after.tick
                ),
                "tick",
            ));
        }
        if before.schema_version != after.schema_version
            || before.execution_plan_version != after.execution_plan_version
            || before.cgs_hash != after.cgs_hash
        {
            return Err(timeline_error(
                "delta_between",
                after.tick,
                "snapshot timeline delta cannot cross schema, plan, or CGS hash boundaries",
                "schema_version",
            ));
        }

        Ok(Self {
            schema: "xace.snapshot_timeline_delta.v1".to_string(),
            from_tick: before.tick,
            to_tick: after.tick,
            expected_from_hash: before.world_hash.clone(),
            expected_to_hash: after.world_hash.clone(),
            time_seconds: after.time_seconds,
            schema_version: after.schema_version.clone(),
            execution_plan_version: after.execution_plan_version,
            cgs_hash: after.cgs_hash.clone(),
            is_clean: after.is_clean,
            next_entity_id: after.entity_store_snapshot.next_entity_id,
            entity_record_changes: entity_record_changes(before, after),
            removed_component_tables: removed_component_tables(before, after),
            component_table_changes: component_table_changes(before, after),
            rng_state: after.rng_state.clone(),
            event_queue_state: after.event_queue_state.clone(),
            mutation_queue_state: after.mutation_queue_state.clone(),
        })
    }

    pub fn apply(&self, base: &WorldSnapshot) -> Result<WorldSnapshot, XaceError> {
        if base.tick != self.from_tick {
            return Err(timeline_error(
                "delta_apply",
                self.to_tick,
                format!(
                    "snapshot timeline delta expected base tick {}, got {}",
                    self.from_tick, base.tick
                ),
                "base.tick",
            ));
        }
        if base.world_hash != self.expected_from_hash {
            return Err(timeline_error(
                "delta_apply",
                self.to_tick,
                "snapshot timeline delta base hash mismatch",
                "base.world_hash",
            ));
        }

        let mut snapshot = base.clone();
        snapshot.tick = self.to_tick;
        snapshot.time_seconds = self.time_seconds;
        snapshot.schema_version = self.schema_version.clone();
        snapshot.execution_plan_version = self.execution_plan_version;
        snapshot.cgs_hash = self.cgs_hash.clone();
        snapshot.is_clean = self.is_clean;
        snapshot.entity_store_snapshot.next_entity_id = self.next_entity_id;
        snapshot.rng_state = self.rng_state.clone();
        snapshot.event_queue_state = self.event_queue_state.clone();
        snapshot.mutation_queue_state = self.mutation_queue_state.clone();

        let mut entity_records = snapshot
            .entity_store_snapshot
            .entities
            .iter()
            .cloned()
            .map(|record| (record.entity_id, record))
            .collect::<BTreeMap<_, _>>();
        for (entity_id, change) in &self.entity_record_changes {
            match change {
                Some(record) => {
                    entity_records.insert(*entity_id, record.clone());
                }
                None => {
                    entity_records.remove(entity_id);
                }
            }
        }
        snapshot.entity_store_snapshot.entities = entity_records.into_values().collect();

        for type_id in &self.removed_component_tables {
            snapshot.component_tables_snapshot.tables.remove(type_id);
        }
        for (type_id, delta) in &self.component_table_changes {
            let table = snapshot
                .component_tables_snapshot
                .tables
                .entry(*type_id)
                .or_insert_with(|| {
                    ComponentTableSnapshot::new(*type_id, delta.component_type_name.clone())
                });
            table.component_type_name = delta.component_type_name.clone();
            for (entity_id, row_change) in &delta.row_changes {
                match row_change {
                    Some(component_json) => {
                        table.rows.insert(*entity_id, component_json.clone());
                    }
                    None => {
                        table.rows.remove(entity_id);
                    }
                }
            }
            if table.rows.is_empty() {
                snapshot.component_tables_snapshot.tables.remove(type_id);
            }
        }

        snapshot.world_hash.clear();
        let computed = WorldHasher::compute(&snapshot);
        if computed != self.expected_to_hash {
            return Err(timeline_error(
                "delta_apply",
                self.to_tick,
                format!(
                    "snapshot timeline delta restored hash mismatch: expected {}, got {}",
                    self.expected_to_hash, computed
                ),
                "world_hash",
            ));
        }
        snapshot.world_hash = computed;
        Ok(snapshot)
    }

    pub fn operation_count(&self) -> usize {
        self.entity_record_changes.len()
            + self.removed_component_tables.len()
            + self
                .component_table_changes
                .values()
                .map(|change| change.row_changes.len().max(1))
                .sum::<usize>()
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ComponentTableDelta {
    pub component_type_id: u32,
    pub component_type_name: String,
    pub row_changes: BTreeMap<EntityID, Option<String>>,
}

fn entity_record_changes(
    before: &WorldSnapshot,
    after: &WorldSnapshot,
) -> BTreeMap<EntityID, Option<EntityRecord>> {
    let before_records = before
        .entity_store_snapshot
        .entities
        .iter()
        .map(|record| (record.entity_id, record))
        .collect::<BTreeMap<_, _>>();
    let after_records = after
        .entity_store_snapshot
        .entities
        .iter()
        .map(|record| (record.entity_id, record))
        .collect::<BTreeMap<_, _>>();
    let ids = before_records
        .keys()
        .chain(after_records.keys())
        .copied()
        .collect::<BTreeSet<_>>();
    ids.into_iter()
        .filter_map(|entity_id| {
            let before_record = before_records.get(&entity_id).copied();
            let after_record = after_records.get(&entity_id).copied();
            if before_record == after_record {
                None
            } else {
                Some((entity_id, after_record.cloned()))
            }
        })
        .collect()
}

fn removed_component_tables(before: &WorldSnapshot, after: &WorldSnapshot) -> Vec<u32> {
    before
        .component_tables_snapshot
        .tables
        .keys()
        .filter(|type_id| !after.component_tables_snapshot.tables.contains_key(type_id))
        .copied()
        .collect()
}

fn component_table_changes(
    before: &WorldSnapshot,
    after: &WorldSnapshot,
) -> BTreeMap<u32, ComponentTableDelta> {
    let type_ids = before
        .component_tables_snapshot
        .tables
        .keys()
        .chain(after.component_tables_snapshot.tables.keys())
        .copied()
        .collect::<BTreeSet<_>>();
    let mut changes = BTreeMap::new();
    for type_id in type_ids {
        let before_table = before.component_tables_snapshot.tables.get(&type_id);
        let Some(after_table) = after.component_tables_snapshot.tables.get(&type_id) else {
            continue;
        };
        let row_ids = before_table
            .into_iter()
            .flat_map(|table| table.rows.keys())
            .chain(after_table.rows.keys())
            .copied()
            .collect::<BTreeSet<_>>();
        let mut row_changes = BTreeMap::new();
        for entity_id in row_ids {
            let before_row = before_table.and_then(|table| table.rows.get(&entity_id));
            let after_row = after_table.rows.get(&entity_id);
            if before_row != after_row {
                row_changes.insert(entity_id, after_row.cloned());
            }
        }
        let metadata_changed = before_table
            .map(|table| table.component_type_name.as_str())
            .unwrap_or_default()
            != after_table.component_type_name;
        if metadata_changed || !row_changes.is_empty() {
            changes.insert(
                type_id,
                ComponentTableDelta {
                    component_type_id: type_id,
                    component_type_name: after_table.component_type_name.clone(),
                    row_changes,
                },
            );
        }
    }
    changes
}

fn serialized_delta_len(delta: &SnapshotTimelineDelta) -> Result<usize, XaceError> {
    serde_json::to_string(delta)
        .map(|json| json.len())
        .map_err(|err| {
            timeline_error(
                "serialize_delta",
                delta.to_tick,
                format!("failed to serialize snapshot timeline delta: {err}"),
                "delta",
            )
        })
}

fn timeline_error(
    operation: &'static str,
    tick: Tick,
    message: impl Into<String>,
    failed_path: impl Into<String>,
) -> XaceError {
    XaceError::ValidationFailure {
        message: message.into(),
        context: ErrorContext::new("DeltaCompressedTimelineRetention", operation).with_tick(tick),
        rule_violated: "X10-047".into(),
        failed_path: failed_path.into(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::entity_state::EntityState;
    use xace_core::runtime::world_snapshot::{
        ComponentTablesSnapshot, EntityStoreSnapshot, EventQueueState, MutationQueueState, RngState,
    };

    fn synthetic_snapshot(tick: Tick) -> WorldSnapshot {
        let mut entities = Vec::new();
        for entity_id in 1..=24 {
            let mut record = EntityRecord::new(entity_id, EntityState::Active, 0);
            record.tags = vec![format!("entity_{entity_id:02}")];
            entities.push(record);
        }
        let mut transform = ComponentTableSnapshot::new(1, "COMP_TRANSFORM_V1");
        for entity_id in 1..=24 {
            let counter = if entity_id == 1 { tick } else { entity_id };
            transform.set(
                entity_id,
                format!(
                    r#"{{"counter":{},"stable_entity":{},"x":{},"y":0,"z":0}}"#,
                    counter,
                    entity_id,
                    entity_id * 1_000
                ),
            );
        }
        let mut tables = ComponentTablesSnapshot::empty();
        tables.set_table(transform);
        let mut snapshot = WorldSnapshot {
            tick,
            time_seconds: Fixed64::from_u64_ratio(tick, 60).unwrap_or(Fixed64::MAX),
            schema_version: "0.1.0".to_string(),
            execution_plan_version: 1,
            cgs_hash: "c".repeat(64),
            entity_store_snapshot: EntityStoreSnapshot {
                entities,
                next_entity_id: 25,
            },
            component_tables_snapshot: tables,
            rng_state: RngState::new(42),
            event_queue_state: EventQueueState::empty(),
            mutation_queue_state: MutationQueueState::empty(),
            world_hash: String::new(),
            is_clean: true,
        };
        snapshot.world_hash = WorldHasher::compute(&snapshot);
        snapshot
    }

    fn assert_authoritative_snapshot_eq(expected: &WorldSnapshot, actual: &WorldSnapshot) {
        assert_eq!(actual.tick, expected.tick);
        assert_eq!(actual.time_seconds, expected.time_seconds);
        assert_eq!(actual.schema_version, expected.schema_version);
        assert_eq!(
            actual.execution_plan_version,
            expected.execution_plan_version
        );
        assert_eq!(actual.cgs_hash, expected.cgs_hash);
        assert_eq!(actual.entity_store_snapshot, expected.entity_store_snapshot);
        assert_eq!(
            actual.component_tables_snapshot,
            expected.component_tables_snapshot
        );
        assert_eq!(actual.rng_state, expected.rng_state);
        assert_eq!(actual.event_queue_state, expected.event_queue_state);
        assert_eq!(actual.mutation_queue_state, expected.mutation_queue_state);
        assert_eq!(actual.world_hash, expected.world_hash);
        assert_eq!(actual.is_clean, expected.is_clean);
        assert_eq!(WorldHasher::compute(actual), expected.world_hash);
    }

    #[test]
    fn x10_047_delta_roundtrip_restores_authoritative_snapshot_fields() {
        let before = synthetic_snapshot(7);
        let after = synthetic_snapshot(8);
        let delta = SnapshotTimelineDelta::between(&before, &after).unwrap();

        assert!(delta.operation_count() > 0);
        assert!(delta.operation_count() < after.total_component_count());

        let restored = delta.apply(&before).unwrap();
        assert_authoritative_snapshot_eq(&after, &restored);
    }

    #[test]
    fn x10_047_memory_bounded_scrub_window_restores_1000_ticks() {
        let mut retention =
            DeltaCompressedTimelineRetention::with_config(DeltaTimelineRetentionConfig {
                max_retained_ticks: X10_047_MIN_SCRUB_TICKS,
                anchor_interval_ticks: 37,
                max_retained_bytes: 32 * 1024 * 1024,
            })
            .unwrap();
        let mut expected = BTreeMap::new();

        for tick in 0..1_100 {
            let snapshot = synthetic_snapshot(tick);
            expected.insert(tick, snapshot.clone());
            retention.remember_snapshot(snapshot).unwrap();
        }

        let stats = retention.stats();
        assert_eq!(stats.retained_ticks, X10_047_MIN_SCRUB_TICKS as usize);
        assert_eq!(stats.oldest_tick, Some(100));
        assert_eq!(stats.latest_tick, Some(1_099));
        assert!(stats.first_entry_is_anchor);
        assert!(stats.contiguous_restore_chain);
        assert!(stats.anchor_count < stats.retained_ticks / 4);
        assert!(stats.delta_count > 900);
        assert!(stats.retained_bytes <= stats.max_retained_bytes);
        assert!(stats.retained_bytes < stats.full_snapshot_bytes);
        assert!(stats.compression_ratio_ppm < 1_000_000);

        for tick in retention.retained_ticks() {
            let restored = retention.restore_snapshot(tick).unwrap();
            assert_authoritative_snapshot_eq(expected.get(&tick).unwrap(), &restored);
            let proof = retention.restore_proof(tick).unwrap();
            assert_eq!(proof.restored_tick, tick);
            assert_eq!(proof.expected_world_hash, proof.restored_world_hash);
        }
    }

    #[test]
    fn x10_047_byte_budget_prunes_only_complete_restore_chains() {
        let mut retention =
            DeltaCompressedTimelineRetention::with_config(DeltaTimelineRetentionConfig {
                max_retained_ticks: 250,
                anchor_interval_ticks: 19,
                max_retained_bytes: 80_000,
            })
            .unwrap();
        let mut expected = BTreeMap::new();

        for tick in 0..300 {
            let snapshot = synthetic_snapshot(tick);
            expected.insert(tick, snapshot.clone());
            retention.remember_snapshot(snapshot).unwrap();
        }

        let stats = retention.stats();
        assert!(stats.retained_ticks <= 250);
        assert!(stats.retained_bytes <= stats.max_retained_bytes || stats.retained_ticks == 1);
        assert!(stats.first_entry_is_anchor);
        assert!(stats.contiguous_restore_chain);
        assert!(stats.delta_count > 0);

        for tick in retention.retained_ticks() {
            let restored = retention.restore_snapshot(tick).unwrap();
            assert_authoritative_snapshot_eq(expected.get(&tick).unwrap(), &restored);
        }
    }
}
