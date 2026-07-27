//! Runtime autosave scheduling for Audit 7.
//!
//! Game systems mark persistence records dirty during normal gameplay phases.
//! This module only commits saves at a configured safe phase, normally Cleanup,
//! after simulation writes and event dispatch have completed.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use xace_core::entity_metadata::Tick;
use xace_core::runtime::phase_enum::PhaseEnum;
use xace_core::runtime::world_snapshot::WorldSnapshot;

use crate::{FileSaveEngine, SaveResult};

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub enum SaveLayerRequest {
    Session,
    Progress,
    World,
}

impl SaveLayerRequest {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Session => "Session",
            Self::Progress => "Progress",
            Self::World => "World",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DirtyPersistenceRecord {
    pub save_key: String,
    pub layer: SaveLayerRequest,
    pub dirty_tick: Tick,
    pub last_saved_tick: Tick,
    pub auto_save: bool,
}

impl DirtyPersistenceRecord {
    pub fn new(
        save_key: impl Into<String>,
        layer: SaveLayerRequest,
        dirty_tick: Tick,
        last_saved_tick: Tick,
    ) -> Self {
        Self {
            save_key: save_key.into(),
            layer,
            dirty_tick,
            last_saved_tick,
            auto_save: true,
        }
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.save_key.trim().is_empty() {
            return Err("save_key must not be empty".into());
        }
        if self.last_saved_tick > self.dirty_tick {
            return Err("last_saved_tick must not be greater than dirty_tick".into());
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AutosaveTriggerSystemConfig {
    pub slot_id: String,
    pub display_name: String,
    pub safe_phase: PhaseEnum,
    pub min_interval_ticks: Tick,
    pub max_dirty_records_per_save: usize,
}

impl AutosaveTriggerSystemConfig {
    pub fn new(slot_id: impl Into<String>, display_name: impl Into<String>) -> Self {
        Self {
            slot_id: slot_id.into(),
            display_name: display_name.into(),
            safe_phase: PhaseEnum::Cleanup,
            min_interval_ticks: 1,
            max_dirty_records_per_save: usize::MAX,
        }
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.slot_id.trim().is_empty() {
            return Err("slot_id must not be empty".into());
        }
        if self.display_name.trim().is_empty() {
            return Err("display_name must not be empty".into());
        }
        if self.max_dirty_records_per_save == 0 {
            return Err("max_dirty_records_per_save must be greater than zero".into());
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AutosaveDecision {
    pub slot_id: String,
    pub display_name: String,
    pub due_tick: Tick,
    pub dirty_records: Vec<DirtyPersistenceRecord>,
    pub reason: String,
}

#[derive(Debug, Clone)]
pub struct AutosaveTriggerSystem {
    config: AutosaveTriggerSystemConfig,
    dirty_records: BTreeMap<String, DirtyPersistenceRecord>,
    last_save_tick: Option<Tick>,
    pending_decision: Option<AutosaveDecision>,
}

impl AutosaveTriggerSystem {
    pub fn new(config: AutosaveTriggerSystemConfig) -> Result<Self, String> {
        config.validate()?;
        Ok(Self {
            config,
            dirty_records: BTreeMap::new(),
            last_save_tick: None,
            pending_decision: None,
        })
    }

    pub fn config(&self) -> &AutosaveTriggerSystemConfig {
        &self.config
    }

    pub fn mark_dirty(&mut self, record: DirtyPersistenceRecord) -> Result<(), String> {
        record.validate()?;
        if !record.auto_save {
            return Ok(());
        }
        self.dirty_records.insert(record.save_key.clone(), record);
        Ok(())
    }

    pub fn clear_record(&mut self, save_key: &str) {
        self.dirty_records.remove(save_key);
    }

    pub fn dirty_count(&self) -> usize {
        self.dirty_records.len()
    }

    pub fn pending_decision(&self) -> Option<&AutosaveDecision> {
        self.pending_decision.as_ref()
    }

    pub fn evaluate_phase(
        &mut self,
        snapshot: &WorldSnapshot,
        phase: PhaseEnum,
    ) -> Option<AutosaveDecision> {
        if phase != self.config.safe_phase {
            return None;
        }
        if !snapshot.is_clean || snapshot.has_pending_mutations() {
            return None;
        }
        if self.dirty_records.is_empty() {
            return None;
        }
        if let Some(last) = self.last_save_tick {
            if snapshot.tick.saturating_sub(last) < self.config.min_interval_ticks {
                return None;
            }
        }

        let dirty_records = self
            .dirty_records
            .values()
            .take(self.config.max_dirty_records_per_save)
            .cloned()
            .collect::<Vec<_>>();
        let decision = AutosaveDecision {
            slot_id: self.config.slot_id.clone(),
            display_name: self.config.display_name.clone(),
            due_tick: snapshot.tick,
            dirty_records,
            reason: "dirty persistence records reached safe phase".into(),
        };
        self.pending_decision = Some(decision.clone());
        Some(decision)
    }

    pub fn execute_pending_save(
        &mut self,
        engine: &FileSaveEngine,
        snapshot: &WorldSnapshot,
    ) -> SaveResult<Option<AutosaveDecision>> {
        let Some(decision) = self.pending_decision.take() else {
            return Ok(None);
        };
        engine.save_session(&decision.slot_id, &decision.display_name, snapshot)?;
        for record in &decision.dirty_records {
            self.dirty_records.remove(&record.save_key);
        }
        self.last_save_tick = Some(snapshot.tick);
        Ok(Some(decision))
    }

    pub fn force_save_now(
        &mut self,
        engine: &FileSaveEngine,
        snapshot: &WorldSnapshot,
    ) -> SaveResult<Option<AutosaveDecision>> {
        if self.dirty_records.is_empty() {
            return Ok(None);
        }
        let dirty_records = self.dirty_records.values().cloned().collect::<Vec<_>>();
        let decision = AutosaveDecision {
            slot_id: self.config.slot_id.clone(),
            display_name: self.config.display_name.clone(),
            due_tick: snapshot.tick,
            dirty_records,
            reason: "manual autosave flush".into(),
        };
        engine.save_session(&decision.slot_id, &decision.display_name, snapshot)?;
        self.dirty_records.clear();
        self.last_save_tick = Some(snapshot.tick);
        Ok(Some(decision))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn snapshot(tick: Tick) -> WorldSnapshot {
        let mut snapshot = WorldSnapshot::empty("0.1.0", 1, 42);
        snapshot.tick = tick;
        snapshot.world_hash = format!("{tick:064x}");
        snapshot
    }

    #[test]
    fn dirty_records_schedule_only_at_safe_phase() {
        let mut system =
            AutosaveTriggerSystem::new(AutosaveTriggerSystemConfig::new("slot_1", "Slot 1"))
                .unwrap();
        system
            .mark_dirty(DirtyPersistenceRecord::new(
                "door_1",
                SaveLayerRequest::World,
                10,
                0,
            ))
            .unwrap();

        assert!(system
            .evaluate_phase(&snapshot(10), PhaseEnum::Simulation)
            .is_none());
        assert!(system
            .evaluate_phase(&snapshot(10), PhaseEnum::Cleanup)
            .is_some());
    }

    #[test]
    fn interval_blocks_too_frequent_saves() {
        let mut config = AutosaveTriggerSystemConfig::new("slot_1", "Slot 1");
        config.min_interval_ticks = 10;
        let mut system = AutosaveTriggerSystem::new(config).unwrap();
        system.last_save_tick = Some(10);
        system
            .mark_dirty(DirtyPersistenceRecord::new(
                "door_1",
                SaveLayerRequest::World,
                15,
                0,
            ))
            .unwrap();

        assert!(system
            .evaluate_phase(&snapshot(15), PhaseEnum::Cleanup)
            .is_none());
        assert!(system
            .evaluate_phase(&snapshot(20), PhaseEnum::Cleanup)
            .is_some());
    }
}
