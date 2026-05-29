use std::collections::{BTreeMap, BTreeSet};

use serde::{Deserialize, Serialize};

use crate::{EntityId, NetworkError, PeerId, Tick};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ReplicationConfig {
    pub min_delta_interval_ticks: Tick,
    pub full_snapshot_interval_ticks: Tick,
    pub max_entities_per_peer_per_tick: usize,
    pub forget_invisible_after_ticks: Tick,
}

impl Default for ReplicationConfig {
    fn default() -> Self {
        Self {
            min_delta_interval_ticks: 1,
            full_snapshot_interval_ticks: 120,
            max_entities_per_peer_per_tick: 256,
            forget_invisible_after_ticks: 300,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub enum ReplicationPriority {
    Low = 0,
    Normal = 1,
    High = 2,
    Critical = 3,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ReplicationReason {
    BecameVisible,
    Dirty,
    FullRefresh,
    Forced,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ReplicationWorkItem {
    pub peer_id: PeerId,
    pub entity_id: EntityId,
    pub reason: ReplicationReason,
    pub priority: ReplicationPriority,
    pub last_sent_tick: Option<Tick>,
    pub dirty_since_tick: Option<Tick>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ReplicationAck {
    pub peer_id: PeerId,
    pub entity_id: EntityId,
    pub sent_tick: Tick,
    pub ack_tick: Tick,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct EntityReplicationState {
    priority: ReplicationPriority,
    dirty_since_tick: Option<Tick>,
    last_changed_tick: Tick,
    force_full_snapshot: bool,
}

impl EntityReplicationState {
    fn new(tick: Tick) -> Self {
        Self {
            priority: ReplicationPriority::Normal,
            dirty_since_tick: Some(tick),
            last_changed_tick: tick,
            force_full_snapshot: true,
        }
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
struct PeerEntityReplicationState {
    last_sent_tick: Option<Tick>,
    last_ack_tick: Option<Tick>,
    became_visible_tick: Option<Tick>,
    became_invisible_tick: Option<Tick>,
    awaiting_ack: bool,
}

#[derive(Debug, Clone, Default)]
pub struct ReplicationManager {
    config: ReplicationConfig,
    last_sent_tick: BTreeMap<(PeerId, EntityId), Tick>,
    visible_entities: BTreeMap<PeerId, BTreeSet<EntityId>>,
    entity_state: BTreeMap<EntityId, EntityReplicationState>,
    peer_entity_state: BTreeMap<(PeerId, EntityId), PeerEntityReplicationState>,
}

impl ReplicationManager {
    pub fn new() -> Self {
        Self::with_config(ReplicationConfig::default())
    }

    pub fn with_config(config: ReplicationConfig) -> Self {
        Self {
            config,
            last_sent_tick: BTreeMap::new(),
            visible_entities: BTreeMap::new(),
            entity_state: BTreeMap::new(),
            peer_entity_state: BTreeMap::new(),
        }
    }

    pub fn update_interest(&mut self, peer_id: PeerId, entities: BTreeSet<EntityId>) {
        let _ = self.update_interest_at(peer_id, entities, 0);
    }

    pub fn update_interest_at(
        &mut self,
        peer_id: PeerId,
        entities: BTreeSet<EntityId>,
        tick: Tick,
    ) -> Result<InterestUpdate, NetworkError> {
        validate_peer_id(peer_id)?;
        for entity_id in &entities {
            validate_entity_id(*entity_id)?;
        }

        let previous = self
            .visible_entities
            .get(&peer_id)
            .cloned()
            .unwrap_or_default();
        let entered = entities
            .difference(&previous)
            .copied()
            .collect::<BTreeSet<_>>();
        let left = previous
            .difference(&entities)
            .copied()
            .collect::<BTreeSet<_>>();

        for entity_id in &entered {
            let state = self
                .peer_entity_state
                .entry((peer_id, *entity_id))
                .or_default();
            state.became_visible_tick = Some(tick);
            state.became_invisible_tick = None;
            self.entity_state
                .entry(*entity_id)
                .or_insert_with(|| EntityReplicationState::new(tick));
        }

        for entity_id in &left {
            let state = self
                .peer_entity_state
                .entry((peer_id, *entity_id))
                .or_default();
            state.became_invisible_tick = Some(tick);
        }

        self.visible_entities.insert(peer_id, entities);
        Ok(InterestUpdate {
            peer_id,
            entered,
            left,
        })
    }

    pub fn mark_entity_changed(
        &mut self,
        entity_id: EntityId,
        tick: Tick,
    ) -> Result<(), NetworkError> {
        self.mark_entity_changed_with_priority(entity_id, tick, ReplicationPriority::Normal)
    }

    pub fn mark_entity_changed_with_priority(
        &mut self,
        entity_id: EntityId,
        tick: Tick,
        priority: ReplicationPriority,
    ) -> Result<(), NetworkError> {
        validate_entity_id(entity_id)?;
        let state = self
            .entity_state
            .entry(entity_id)
            .or_insert_with(|| EntityReplicationState::new(tick));
        state.dirty_since_tick = state.dirty_since_tick.or(Some(tick));
        state.last_changed_tick = state.last_changed_tick.max(tick);
        state.priority = state.priority.max(priority);
        Ok(())
    }

    pub fn force_full_snapshot(&mut self, entity_id: EntityId) -> Result<(), NetworkError> {
        validate_entity_id(entity_id)?;
        self.entity_state
            .entry(entity_id)
            .or_insert_with(|| EntityReplicationState::new(0))
            .force_full_snapshot = true;
        Ok(())
    }

    pub fn entities_due_for_peer(
        &self,
        peer_id: PeerId,
        changed_entities: &BTreeSet<EntityId>,
    ) -> Vec<EntityId> {
        let Some(visible) = self.visible_entities.get(&peer_id) else {
            return Vec::new();
        };
        visible.intersection(changed_entities).copied().collect()
    }

    pub fn work_items_for_peer(
        &self,
        peer_id: PeerId,
        tick: Tick,
    ) -> Result<Vec<ReplicationWorkItem>, NetworkError> {
        validate_peer_id(peer_id)?;
        let Some(visible) = self.visible_entities.get(&peer_id) else {
            return Ok(Vec::new());
        };

        let mut work = Vec::new();
        for entity_id in visible {
            if let Some(item) = self.work_item_for_entity(peer_id, *entity_id, tick)? {
                work.push(item);
            }
        }

        work.sort_by(|left, right| {
            right
                .priority
                .cmp(&left.priority)
                .then_with(|| reason_rank(right.reason).cmp(&reason_rank(left.reason)))
                .then_with(|| {
                    left.last_sent_tick
                        .unwrap_or(0)
                        .cmp(&right.last_sent_tick.unwrap_or(0))
                })
                .then_with(|| left.entity_id.cmp(&right.entity_id))
        });
        work.truncate(self.config.max_entities_per_peer_per_tick);
        Ok(work)
    }

    pub fn work_items_for_all_peers(
        &self,
        tick: Tick,
    ) -> Result<BTreeMap<PeerId, Vec<ReplicationWorkItem>>, NetworkError> {
        let mut all = BTreeMap::new();
        for peer_id in self.visible_entities.keys().copied() {
            all.insert(peer_id, self.work_items_for_peer(peer_id, tick)?);
        }
        Ok(all)
    }

    pub fn mark_sent(&mut self, peer_id: PeerId, entity_id: EntityId, tick: Tick) {
        let _ = self.mark_sent_result(peer_id, entity_id, tick);
    }

    pub fn mark_sent_result(
        &mut self,
        peer_id: PeerId,
        entity_id: EntityId,
        tick: Tick,
    ) -> Result<(), NetworkError> {
        validate_peer_id(peer_id)?;
        validate_entity_id(entity_id)?;
        self.last_sent_tick.insert((peer_id, entity_id), tick);
        let peer_state = self
            .peer_entity_state
            .entry((peer_id, entity_id))
            .or_default();
        peer_state.last_sent_tick = Some(tick);
        peer_state.awaiting_ack = true;

        if self
            .visible_entities
            .values()
            .any(|entities| entities.contains(&entity_id))
        {
            if let Some(entity_state) = self.entity_state.get_mut(&entity_id) {
                entity_state.force_full_snapshot = false;
                if self
                    .visible_entities
                    .iter()
                    .filter(|(_, entities)| entities.contains(&entity_id))
                    .all(|(&visible_peer, _)| {
                        self.peer_entity_state
                            .get(&(visible_peer, entity_id))
                            .and_then(|state| state.last_sent_tick)
                            .is_some_and(|last_sent| {
                                entity_state
                                    .dirty_since_tick
                                    .is_none_or(|dirty_since| last_sent >= dirty_since)
                            })
                    })
                {
                    entity_state.dirty_since_tick = None;
                    entity_state.priority = ReplicationPriority::Normal;
                }
            }
        }
        Ok(())
    }

    pub fn acknowledge(
        &mut self,
        peer_id: PeerId,
        entity_id: EntityId,
        sent_tick: Tick,
        ack_tick: Tick,
    ) -> Result<ReplicationAck, NetworkError> {
        validate_peer_id(peer_id)?;
        validate_entity_id(entity_id)?;
        let state = self
            .peer_entity_state
            .entry((peer_id, entity_id))
            .or_default();
        if state.last_sent_tick != Some(sent_tick) {
            return Err(NetworkError::InvalidOperation(format!(
                "ack peer={} entity={} sent_tick={} does not match last sent {:?}",
                peer_id, entity_id, sent_tick, state.last_sent_tick
            )));
        }
        state.last_ack_tick = Some(ack_tick);
        state.awaiting_ack = false;
        Ok(ReplicationAck {
            peer_id,
            entity_id,
            sent_tick,
            ack_tick,
        })
    }

    pub fn prune_invisible(&mut self, tick: Tick) -> usize {
        let mut removed = Vec::new();
        for (&key, state) in &self.peer_entity_state {
            let Some(invisible_tick) = state.became_invisible_tick else {
                continue;
            };
            if tick.saturating_sub(invisible_tick) >= self.config.forget_invisible_after_ticks {
                removed.push(key);
            }
        }
        for key in &removed {
            self.peer_entity_state.remove(key);
            self.last_sent_tick.remove(key);
        }
        removed.len()
    }

    pub fn last_sent_tick(&self, peer_id: PeerId, entity_id: EntityId) -> Option<Tick> {
        self.last_sent_tick.get(&(peer_id, entity_id)).copied()
    }

    pub fn visible_entities_for_peer(&self, peer_id: PeerId) -> BTreeSet<EntityId> {
        self.visible_entities
            .get(&peer_id)
            .cloned()
            .unwrap_or_default()
    }

    pub fn dirty_entities(&self) -> BTreeSet<EntityId> {
        self.entity_state
            .iter()
            .filter_map(|(&entity_id, state)| state.dirty_since_tick.is_some().then_some(entity_id))
            .collect()
    }

    pub fn config(&self) -> &ReplicationConfig {
        &self.config
    }

    pub fn config_mut(&mut self) -> &mut ReplicationConfig {
        &mut self.config
    }

    fn work_item_for_entity(
        &self,
        peer_id: PeerId,
        entity_id: EntityId,
        tick: Tick,
    ) -> Result<Option<ReplicationWorkItem>, NetworkError> {
        validate_entity_id(entity_id)?;
        let entity_state = self.entity_state.get(&entity_id);
        let peer_state = self.peer_entity_state.get(&(peer_id, entity_id));
        let last_sent_tick = peer_state.and_then(|state| state.last_sent_tick);

        let reason = if last_sent_tick.is_none() {
            Some(ReplicationReason::BecameVisible)
        } else if entity_state.is_some_and(|state| state.force_full_snapshot) {
            Some(ReplicationReason::Forced)
        } else if should_full_refresh(
            last_sent_tick,
            tick,
            self.config.full_snapshot_interval_ticks,
        ) {
            Some(ReplicationReason::FullRefresh)
        } else if entity_state.is_some_and(|state| state.dirty_since_tick.is_some())
            && last_sent_tick.is_none_or(|last_sent| {
                tick.saturating_sub(last_sent) >= self.config.min_delta_interval_ticks
            })
        {
            Some(ReplicationReason::Dirty)
        } else {
            None
        };

        let Some(reason) = reason else {
            return Ok(None);
        };

        Ok(Some(ReplicationWorkItem {
            peer_id,
            entity_id,
            reason,
            priority: entity_state
                .map(|state| state.priority)
                .unwrap_or(ReplicationPriority::Normal),
            last_sent_tick,
            dirty_since_tick: entity_state.and_then(|state| state.dirty_since_tick),
        }))
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct InterestUpdate {
    pub peer_id: PeerId,
    pub entered: BTreeSet<EntityId>,
    pub left: BTreeSet<EntityId>,
}

fn should_full_refresh(last_sent_tick: Option<Tick>, tick: Tick, interval: Tick) -> bool {
    interval > 0
        && last_sent_tick.is_some_and(|last_sent| tick.saturating_sub(last_sent) >= interval)
}

fn reason_rank(reason: ReplicationReason) -> u8 {
    match reason {
        ReplicationReason::Forced => 4,
        ReplicationReason::BecameVisible => 3,
        ReplicationReason::FullRefresh => 2,
        ReplicationReason::Dirty => 1,
    }
}

fn validate_entity_id(entity_id: EntityId) -> Result<(), NetworkError> {
    if entity_id == 0 {
        return Err(NetworkError::InvalidOperation(
            "entity_id 0 is reserved".to_string(),
        ));
    }
    Ok(())
}

fn validate_peer_id(peer_id: PeerId) -> Result<(), NetworkError> {
    if peer_id == 0 {
        return Err(NetworkError::InvalidOperation(
            "peer_id 0 is reserved".to_string(),
        ));
    }
    Ok(())
}
