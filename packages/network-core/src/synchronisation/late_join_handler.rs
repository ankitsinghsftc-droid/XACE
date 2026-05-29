use std::collections::{BTreeMap, BTreeSet};

use serde::{Deserialize, Serialize};

use crate::{NetworkError, PeerId, Tick};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum LateJoinState {
    Planned,
    SnapshotQueued,
    CatchingUp,
    Live,
    Failed,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LateJoinConfig {
    pub max_catch_up_ticks: Tick,
    pub batch_size: usize,
    pub snapshot_grace_ticks: Tick,
}

impl Default for LateJoinConfig {
    fn default() -> Self {
        Self {
            max_catch_up_ticks: 600,
            batch_size: 32,
            snapshot_grace_ticks: 2,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CatchUpBatch {
    pub from_tick: Tick,
    pub to_tick: Tick,
    pub ticks: Vec<Tick>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LateJoinPlan {
    pub peer_id: PeerId,
    pub snapshot_tick: Tick,
    pub live_tick: Tick,
    pub catch_up_ticks: Vec<Tick>,
    pub batches: Vec<CatchUpBatch>,
    pub state: LateJoinState,
}

impl LateJoinPlan {
    pub fn is_caught_up(&self) -> bool {
        self.catch_up_ticks.is_empty() || self.state == LateJoinState::Live
    }
}

#[derive(Debug, Clone)]
pub struct LateJoinHandler {
    config: LateJoinConfig,
    plans: BTreeMap<PeerId, LateJoinPlan>,
}

impl Default for LateJoinHandler {
    fn default() -> Self {
        Self::new()
    }
}

impl LateJoinHandler {
    pub fn new() -> Self {
        Self::with_config(LateJoinConfig::default())
    }

    pub fn with_config(config: LateJoinConfig) -> Self {
        Self {
            config: LateJoinConfig {
                batch_size: config.batch_size.max(1),
                ..config
            },
            plans: BTreeMap::new(),
        }
    }

    pub fn plan(peer_id: PeerId, snapshot_tick: Tick, live_tick: Tick) -> LateJoinPlan {
        Self::build_plan(
            peer_id,
            snapshot_tick,
            live_tick,
            &LateJoinConfig::default(),
        )
        .unwrap_or_else(|_| LateJoinPlan {
            peer_id,
            snapshot_tick,
            live_tick,
            catch_up_ticks: Vec::new(),
            batches: Vec::new(),
            state: LateJoinState::Failed,
        })
    }

    pub fn plan_for_peer(
        &mut self,
        peer_id: PeerId,
        snapshot_tick: Tick,
        live_tick: Tick,
    ) -> Result<LateJoinPlan, NetworkError> {
        let plan = Self::build_plan(peer_id, snapshot_tick, live_tick, &self.config)?;
        self.plans.insert(peer_id, plan.clone());
        Ok(plan)
    }

    pub fn mark_snapshot_queued(&mut self, peer_id: PeerId) -> Result<(), NetworkError> {
        let plan = self.require_plan_mut(peer_id)?;
        plan.state = LateJoinState::SnapshotQueued;
        Ok(())
    }

    pub fn mark_catching_up(&mut self, peer_id: PeerId) -> Result<(), NetworkError> {
        let plan = self.require_plan_mut(peer_id)?;
        plan.state = LateJoinState::CatchingUp;
        Ok(())
    }

    pub fn consume_batch(&mut self, peer_id: PeerId) -> Result<Option<CatchUpBatch>, NetworkError> {
        let plan = self.require_plan_mut(peer_id)?;
        if plan.batches.is_empty() {
            plan.state = LateJoinState::Live;
            return Ok(None);
        }
        plan.state = LateJoinState::CatchingUp;
        let batch = plan.batches.remove(0);
        let consumed = batch.ticks.iter().copied().collect::<BTreeSet<_>>();
        plan.catch_up_ticks.retain(|tick| !consumed.contains(tick));
        if plan.batches.is_empty() && plan.catch_up_ticks.is_empty() {
            plan.state = LateJoinState::Live;
        }
        Ok(Some(batch))
    }

    pub fn fail(&mut self, peer_id: PeerId) -> Result<(), NetworkError> {
        let plan = self.require_plan_mut(peer_id)?;
        plan.state = LateJoinState::Failed;
        Ok(())
    }

    pub fn plan_for(&self, peer_id: PeerId) -> Option<&LateJoinPlan> {
        self.plans.get(&peer_id)
    }

    pub fn remove_plan(&mut self, peer_id: PeerId) -> Option<LateJoinPlan> {
        self.plans.remove(&peer_id)
    }

    pub fn active_peer_ids(&self) -> BTreeSet<PeerId> {
        self.plans
            .iter()
            .filter_map(|(&peer_id, plan)| {
                (!matches!(plan.state, LateJoinState::Live | LateJoinState::Failed))
                    .then_some(peer_id)
            })
            .collect()
    }

    pub fn config(&self) -> &LateJoinConfig {
        &self.config
    }

    fn build_plan(
        peer_id: PeerId,
        snapshot_tick: Tick,
        live_tick: Tick,
        config: &LateJoinConfig,
    ) -> Result<LateJoinPlan, NetworkError> {
        validate_peer_id(peer_id)?;
        if snapshot_tick > live_tick.saturating_add(config.snapshot_grace_ticks) {
            return Err(NetworkError::InvalidOperation(format!(
                "late join snapshot tick {} is ahead of live tick {}",
                snapshot_tick, live_tick
            )));
        }
        let catch_up_ticks = if live_tick > snapshot_tick {
            ((snapshot_tick + 1)..=live_tick).collect::<Vec<_>>()
        } else {
            Vec::new()
        };
        if catch_up_ticks.len() as u64 > config.max_catch_up_ticks {
            return Err(NetworkError::InvalidOperation(format!(
                "late join catch-up span {} exceeds limit {}",
                catch_up_ticks.len(),
                config.max_catch_up_ticks
            )));
        }
        let batches = catch_up_ticks
            .chunks(config.batch_size.max(1))
            .map(|chunk| CatchUpBatch {
                from_tick: *chunk.first().expect("chunk is non-empty"),
                to_tick: *chunk.last().expect("chunk is non-empty"),
                ticks: chunk.to_vec(),
            })
            .collect();
        Ok(LateJoinPlan {
            peer_id,
            snapshot_tick,
            live_tick,
            catch_up_ticks,
            batches,
            state: LateJoinState::Planned,
        })
    }

    fn require_plan_mut(&mut self, peer_id: PeerId) -> Result<&mut LateJoinPlan, NetworkError> {
        validate_peer_id(peer_id)?;
        self.plans.get_mut(&peer_id).ok_or_else(|| {
            NetworkError::InvalidOperation(format!("no late join plan for peer {}", peer_id))
        })
    }
}

fn validate_peer_id(peer_id: PeerId) -> Result<(), NetworkError> {
    if peer_id == 0 {
        return Err(NetworkError::InvalidOperation(
            "peer_id 0 is reserved".to_string(),
        ));
    }
    Ok(())
}
