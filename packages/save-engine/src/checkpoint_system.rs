//! Runtime checkpoint state for Audit 7.
//!
//! Checkpoints are deterministic records keyed by ID. This module can persist
//! the active checkpoint as a session save and produce restore plans for load
//! or respawn flows.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use xace_core::entity_metadata::Tick;
use xace_core::runtime::world_snapshot::WorldSnapshot;

use crate::{FileSaveEngine, SaveResult};

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub enum CheckpointType {
    Manual,
    Auto,
    Story,
    Respawn,
}

impl CheckpointType {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Manual => "MANUAL",
            Self::Auto => "AUTO",
            Self::Story => "STORY",
            Self::Respawn => "RESPAWN",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct CheckpointRecord {
    pub checkpoint_id: String,
    pub checkpoint_type: CheckpointType,
    pub activation_tick: Tick,
    pub world_state_hash: String,
    pub respawn_position: [f32; 3],
    pub save_slot_id: String,
    pub display_name: String,
    pub triggers_autosave: bool,
}

impl CheckpointRecord {
    pub fn new(
        checkpoint_id: impl Into<String>,
        checkpoint_type: CheckpointType,
        activation_tick: Tick,
        world_state_hash: impl Into<String>,
        save_slot_id: impl Into<String>,
    ) -> Self {
        let checkpoint_id = checkpoint_id.into();
        Self {
            display_name: checkpoint_id.clone(),
            checkpoint_id,
            checkpoint_type,
            activation_tick,
            world_state_hash: world_state_hash.into(),
            respawn_position: [0.0, 0.0, 0.0],
            save_slot_id: save_slot_id.into(),
            triggers_autosave: true,
        }
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.checkpoint_id.trim().is_empty() {
            return Err("checkpoint_id must not be empty".into());
        }
        if self.world_state_hash.trim().is_empty() {
            return Err("world_state_hash must not be empty".into());
        }
        if self.save_slot_id.trim().is_empty() {
            return Err("save_slot_id must not be empty".into());
        }
        if self
            .respawn_position
            .iter()
            .any(|coordinate| !coordinate.is_finite())
        {
            return Err("respawn_position must contain finite coordinates".into());
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CheckpointSystemConfig {
    pub default_slot_prefix: String,
    pub keep_history_limit: usize,
}

impl Default for CheckpointSystemConfig {
    fn default() -> Self {
        Self {
            default_slot_prefix: "checkpoint".into(),
            keep_history_limit: 8,
        }
    }
}

impl CheckpointSystemConfig {
    pub fn validate(&self) -> Result<(), String> {
        if self.default_slot_prefix.trim().is_empty() {
            return Err("default_slot_prefix must not be empty".into());
        }
        if self.keep_history_limit == 0 {
            return Err("keep_history_limit must be greater than zero".into());
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct CheckpointRestorePlan {
    pub checkpoint_id: String,
    pub save_slot_id: String,
    pub expected_world_hash: String,
    pub respawn_position: [f32; 3],
}

#[derive(Debug, Clone)]
pub struct CheckpointSystem {
    config: CheckpointSystemConfig,
    records: BTreeMap<String, CheckpointRecord>,
    active_checkpoint_id: Option<String>,
}

impl CheckpointSystem {
    pub fn new(config: CheckpointSystemConfig) -> Result<Self, String> {
        config.validate()?;
        Ok(Self {
            config,
            records: BTreeMap::new(),
            active_checkpoint_id: None,
        })
    }

    pub fn activate_checkpoint(
        &mut self,
        mut record: CheckpointRecord,
        snapshot: &WorldSnapshot,
    ) -> Result<&CheckpointRecord, String> {
        if record.activation_tick != snapshot.tick {
            record.activation_tick = snapshot.tick;
        }
        if record.world_state_hash.trim().is_empty() {
            record.world_state_hash = snapshot.world_hash.clone();
        }
        record.validate()?;
        let checkpoint_id = record.checkpoint_id.clone();
        self.records.insert(checkpoint_id.clone(), record);
        self.active_checkpoint_id = Some(checkpoint_id.clone());
        self.trim_history();
        Ok(self
            .records
            .get(&checkpoint_id)
            .expect("inserted checkpoint must exist"))
    }

    pub fn activate_and_save(
        &mut self,
        engine: &FileSaveEngine,
        record: CheckpointRecord,
        snapshot: &WorldSnapshot,
    ) -> SaveResult<CheckpointRecord> {
        let activated = self
            .activate_checkpoint(record, snapshot)
            .map_err(crate::SaveEngineError::InvalidData)?
            .clone();
        if activated.triggers_autosave {
            engine.save_session(&activated.save_slot_id, &activated.display_name, snapshot)?;
        }
        Ok(activated)
    }

    pub fn latest_checkpoint(&self) -> Option<&CheckpointRecord> {
        self.active_checkpoint_id
            .as_ref()
            .and_then(|id| self.records.get(id))
    }

    pub fn checkpoint(&self, checkpoint_id: &str) -> Option<&CheckpointRecord> {
        self.records.get(checkpoint_id)
    }

    pub fn restore_plan(&self, checkpoint_id: Option<&str>) -> Option<CheckpointRestorePlan> {
        let record = match checkpoint_id {
            Some(id) => self.records.get(id)?,
            None => self.latest_checkpoint()?,
        };
        Some(CheckpointRestorePlan {
            checkpoint_id: record.checkpoint_id.clone(),
            save_slot_id: record.save_slot_id.clone(),
            expected_world_hash: record.world_state_hash.clone(),
            respawn_position: record.respawn_position,
        })
    }

    pub fn load_restore_snapshot(
        &self,
        engine: &FileSaveEngine,
        checkpoint_id: Option<&str>,
    ) -> SaveResult<Option<WorldSnapshot>> {
        let Some(plan) = self.restore_plan(checkpoint_id) else {
            return Ok(None);
        };
        let snapshot = engine.load_session(&plan.save_slot_id)?;
        Ok(Some(snapshot))
    }

    pub fn checkpoint_count(&self) -> usize {
        self.records.len()
    }

    fn trim_history(&mut self) {
        while self.records.len() > self.config.keep_history_limit {
            let protected = self.active_checkpoint_id.as_deref();
            let remove_key = self
                .records
                .keys()
                .find(|key| Some(key.as_str()) != protected)
                .cloned();
            if let Some(key) = remove_key {
                self.records.remove(&key);
            } else {
                break;
            }
        }
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
    fn activate_checkpoint_tracks_latest() {
        let mut system = CheckpointSystem::new(CheckpointSystemConfig::default()).unwrap();
        let record = CheckpointRecord::new(
            "cp_1",
            CheckpointType::Manual,
            0,
            format!("{:064x}", 10),
            "slot_cp_1",
        );
        system.activate_checkpoint(record, &snapshot(10)).unwrap();
        let latest = system.latest_checkpoint().unwrap();
        assert_eq!(latest.checkpoint_id, "cp_1");
        assert_eq!(latest.activation_tick, 10);
    }

    #[test]
    fn restore_plan_uses_latest_when_not_specified() {
        let mut system = CheckpointSystem::new(CheckpointSystemConfig::default()).unwrap();
        let record = CheckpointRecord::new(
            "cp_1",
            CheckpointType::Respawn,
            10,
            format!("{:064x}", 10),
            "slot_cp_1",
        );
        system.activate_checkpoint(record, &snapshot(10)).unwrap();
        let plan = system.restore_plan(None).unwrap();
        assert_eq!(plan.save_slot_id, "slot_cp_1");
        assert_eq!(plan.expected_world_hash, format!("{:064x}", 10));
    }

    #[test]
    fn history_limit_trims_old_records() {
        let mut config = CheckpointSystemConfig::default();
        config.keep_history_limit = 2;
        let mut system = CheckpointSystem::new(config).unwrap();
        for tick in 1..=3 {
            let record = CheckpointRecord::new(
                format!("cp_{tick}"),
                CheckpointType::Auto,
                tick,
                format!("{tick:064x}"),
                format!("slot_{tick}"),
            );
            system.activate_checkpoint(record, &snapshot(tick)).unwrap();
        }
        assert_eq!(system.checkpoint_count(), 2);
        assert!(system.checkpoint("cp_3").is_some());
    }
}
