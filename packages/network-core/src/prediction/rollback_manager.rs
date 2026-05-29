use std::collections::{BTreeMap, BTreeSet};

use serde::{Deserialize, Serialize};

use crate::{NetworkError, Tick};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RollbackConfig {
    pub max_replay_ticks: Tick,
    pub snapshot_retention_ticks: Tick,
    pub max_snapshots: usize,
}

impl Default for RollbackConfig {
    fn default() -> Self {
        Self {
            max_replay_ticks: 240,
            snapshot_retention_ticks: 600,
            max_snapshots: 256,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RollbackSnapshotMeta {
    pub tick: Tick,
    pub state_hash: Option<String>,
    pub byte_len: Option<usize>,
    pub stable: bool,
}

impl RollbackSnapshotMeta {
    pub fn new(tick: Tick) -> Self {
        Self {
            tick,
            state_hash: None,
            byte_len: None,
            stable: true,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum RollbackReason {
    AuthoritativeCorrection,
    DesyncRecovery,
    LateInput,
    Resimulation,
    Manual,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RollbackPlan {
    pub restore_tick: Tick,
    pub replay_ticks: Vec<Tick>,
    pub target_tick: Tick,
    pub live_tick: Tick,
    pub reason: RollbackReason,
    pub snapshot_hash: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RollbackRecord {
    pub plan: RollbackPlan,
    pub requested_tick: Tick,
    pub completed_tick: Option<Tick>,
}

#[derive(Debug, Clone)]
pub struct RollbackManager {
    config: RollbackConfig,
    snapshots: BTreeMap<Tick, RollbackSnapshotMeta>,
    records: Vec<RollbackRecord>,
}

impl RollbackManager {
    pub fn new() -> Self {
        Self::with_config(RollbackConfig::default())
    }

    pub fn with_config(config: RollbackConfig) -> Self {
        Self {
            config: RollbackConfig {
                max_snapshots: config.max_snapshots.max(1),
                ..config
            },
            snapshots: BTreeMap::new(),
            records: Vec::new(),
        }
    }

    pub fn record_snapshot(&mut self, tick: Tick) {
        let _ = self.record_snapshot_meta(RollbackSnapshotMeta::new(tick));
    }

    pub fn record_snapshot_with_hash(
        &mut self,
        tick: Tick,
        state_hash: impl Into<String>,
        byte_len: usize,
    ) -> Result<(), NetworkError> {
        self.record_snapshot_meta(RollbackSnapshotMeta {
            tick,
            state_hash: Some(state_hash.into()),
            byte_len: Some(byte_len),
            stable: true,
        })
    }

    pub fn record_snapshot_meta(
        &mut self,
        snapshot: RollbackSnapshotMeta,
    ) -> Result<(), NetworkError> {
        if snapshot.tick == 0 {
            return Err(NetworkError::InvalidOperation(
                "rollback snapshot tick 0 is reserved".to_string(),
            ));
        }
        self.snapshots.insert(snapshot.tick, snapshot);
        self.enforce_snapshot_limits();
        Ok(())
    }

    pub fn mark_snapshot_unstable(&mut self, tick: Tick) -> Result<(), NetworkError> {
        let snapshot = self
            .snapshots
            .get_mut(&tick)
            .ok_or(NetworkError::RollbackSnapshotMissing(tick))?;
        snapshot.stable = false;
        Ok(())
    }

    pub fn plan(&self, target_tick: Tick, live_tick: Tick) -> Result<RollbackPlan, NetworkError> {
        self.plan_with_reason(target_tick, live_tick, RollbackReason::Manual)
    }

    pub fn plan_with_reason(
        &self,
        target_tick: Tick,
        live_tick: Tick,
        reason: RollbackReason,
    ) -> Result<RollbackPlan, NetworkError> {
        if target_tick > live_tick {
            return Err(NetworkError::InvalidOperation(format!(
                "rollback target tick {} is after live tick {}",
                target_tick, live_tick
            )));
        }
        let restore = self
            .snapshots
            .range(..=target_tick)
            .rev()
            .find(|(_, snapshot)| snapshot.stable)
            .map(|(_, snapshot)| snapshot)
            .ok_or(NetworkError::RollbackSnapshotMissing(target_tick))?;

        let replay_span = live_tick.saturating_sub(restore.tick);
        if replay_span > self.config.max_replay_ticks {
            return Err(NetworkError::InvalidOperation(format!(
                "rollback replay span {} exceeds limit {}",
                replay_span, self.config.max_replay_ticks
            )));
        }

        let replay_ticks = if live_tick > restore.tick {
            ((restore.tick + 1)..=live_tick).collect()
        } else {
            Vec::new()
        };
        Ok(RollbackPlan {
            restore_tick: restore.tick,
            replay_ticks,
            target_tick,
            live_tick,
            reason,
            snapshot_hash: restore.state_hash.clone(),
        })
    }

    pub fn begin_rollback(
        &mut self,
        target_tick: Tick,
        live_tick: Tick,
        requested_tick: Tick,
        reason: RollbackReason,
    ) -> Result<RollbackPlan, NetworkError> {
        let plan = self.plan_with_reason(target_tick, live_tick, reason)?;
        self.records.push(RollbackRecord {
            plan: plan.clone(),
            requested_tick,
            completed_tick: None,
        });
        Ok(plan)
    }

    pub fn complete_latest(&mut self, completed_tick: Tick) -> Result<(), NetworkError> {
        let record = self
            .records
            .iter_mut()
            .rev()
            .find(|record| record.completed_tick.is_none())
            .ok_or_else(|| {
                NetworkError::InvalidOperation("no rollback is currently pending".to_string())
            })?;
        record.completed_tick = Some(completed_tick);
        Ok(())
    }

    pub fn prune_before(&mut self, tick: Tick) -> Vec<Tick> {
        let to_remove = self
            .snapshots
            .range(..tick)
            .map(|(&snapshot_tick, _)| snapshot_tick)
            .collect::<Vec<_>>();
        for snapshot_tick in &to_remove {
            self.snapshots.remove(snapshot_tick);
        }
        to_remove
    }

    pub fn snapshot_ticks(&self) -> BTreeSet<Tick> {
        self.snapshots.keys().copied().collect()
    }

    pub fn snapshot(&self, tick: Tick) -> Option<&RollbackSnapshotMeta> {
        self.snapshots.get(&tick)
    }

    pub fn records(&self) -> &[RollbackRecord] {
        &self.records
    }

    pub fn pending_record(&self) -> Option<&RollbackRecord> {
        self.records
            .iter()
            .rev()
            .find(|record| record.completed_tick.is_none())
    }

    pub fn config(&self) -> &RollbackConfig {
        &self.config
    }

    fn enforce_snapshot_limits(&mut self) {
        while self.snapshots.len() > self.config.max_snapshots {
            let Some(oldest_tick) = self.snapshots.keys().next().copied() else {
                break;
            };
            self.snapshots.remove(&oldest_tick);
        }

        let Some(latest_tick) = self.snapshots.keys().next_back().copied() else {
            return;
        };
        if self.config.snapshot_retention_ticks == 0 {
            return;
        }
        let min_tick = latest_tick.saturating_sub(self.config.snapshot_retention_ticks);
        self.prune_before(min_tick);
    }
}

impl Default for RollbackManager {
    fn default() -> Self {
        Self::new()
    }
}
