use std::collections::{BTreeMap, BTreeSet};

use serde::{Deserialize, Serialize};

use crate::{EntityId, NetworkError, PeerId};

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct EntityRelevance {
    pub entity_id: EntityId,
    pub x: f32,
    pub z: f32,
    pub radius: f32,
    pub team_id: u32,
}

impl EntityRelevance {
    pub fn validate(self) -> Result<(), NetworkError> {
        if self.entity_id == 0 {
            return Err(NetworkError::InvalidOperation(
                "entity_id 0 is reserved".to_string(),
            ));
        }
        if !self.x.is_finite()
            || !self.z.is_finite()
            || !self.radius.is_finite()
            || self.radius < 0.0
        {
            return Err(NetworkError::InvalidOperation(format!(
                "entity {} has invalid relevance bounds",
                self.entity_id
            )));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct PeerRelevanceContext {
    pub peer_id: PeerId,
    pub x: f32,
    pub z: f32,
    pub team_id: Option<u32>,
    pub controlled_entity: Option<EntityId>,
}

impl PeerRelevanceContext {
    pub fn new(peer_id: PeerId, x: f32, z: f32) -> Self {
        Self {
            peer_id,
            x,
            z,
            team_id: None,
            controlled_entity: None,
        }
    }

    pub fn validate(self) -> Result<(), NetworkError> {
        if self.peer_id == 0 {
            return Err(NetworkError::InvalidOperation(
                "peer_id 0 is reserved".to_string(),
            ));
        }
        if !self.x.is_finite() || !self.z.is_finite() {
            return Err(NetworkError::InvalidOperation(format!(
                "peer {} has invalid relevance position",
                self.peer_id
            )));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RelevanceFilterConfig {
    pub max_entities_per_peer: usize,
    pub same_team_bonus: i32,
    pub controlled_entity_bonus: i32,
    pub always_relevant_bonus: i32,
    pub distance_penalty_per_unit: i32,
    pub include_out_of_range_owned_entities: bool,
}

impl Default for RelevanceFilterConfig {
    fn default() -> Self {
        Self {
            max_entities_per_peer: 512,
            same_team_bonus: 100,
            controlled_entity_bonus: 1_000,
            always_relevant_bonus: 10_000,
            distance_penalty_per_unit: 1,
            include_out_of_range_owned_entities: true,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum RelevanceReason {
    InRange,
    AlwaysRelevant,
    ControlledEntity,
    ExplicitInterest,
    SharedTeam,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RelevanceDecision {
    pub entity_id: EntityId,
    pub distance_sq: f32,
    pub score: i32,
    pub reason: RelevanceReason,
}

#[derive(Debug, Clone)]
pub struct RelevanceFilter {
    config: RelevanceFilterConfig,
    always_relevant: BTreeSet<EntityId>,
    explicit_peer_interest: BTreeMap<PeerId, BTreeSet<EntityId>>,
}

impl Default for RelevanceFilter {
    fn default() -> Self {
        Self {
            config: RelevanceFilterConfig::default(),
            always_relevant: BTreeSet::new(),
            explicit_peer_interest: BTreeMap::new(),
        }
    }
}

impl RelevanceFilter {
    pub fn new(config: RelevanceFilterConfig) -> Self {
        Self {
            config,
            always_relevant: BTreeSet::new(),
            explicit_peer_interest: BTreeMap::new(),
        }
    }

    pub fn filter_by_distance(
        peer_id: PeerId,
        peer_position: (f32, f32),
        entities: &[EntityRelevance],
    ) -> Vec<EntityId> {
        let context = PeerRelevanceContext::new(peer_id, peer_position.0, peer_position.1);
        let filter = Self::default();
        filter
            .rank_entities(&context, entities)
            .unwrap_or_default()
            .into_iter()
            .filter(|decision| decision.reason == RelevanceReason::InRange)
            .map(|decision| decision.entity_id)
            .collect()
    }

    pub fn set_always_relevant(&mut self, entity_id: EntityId, enabled: bool) {
        if entity_id == 0 {
            return;
        }
        if enabled {
            self.always_relevant.insert(entity_id);
        } else {
            self.always_relevant.remove(&entity_id);
        }
    }

    pub fn add_explicit_interest(
        &mut self,
        peer_id: PeerId,
        entity_id: EntityId,
    ) -> Result<bool, NetworkError> {
        validate_peer_entity(peer_id, entity_id)?;
        Ok(self
            .explicit_peer_interest
            .entry(peer_id)
            .or_default()
            .insert(entity_id))
    }

    pub fn remove_explicit_interest(&mut self, peer_id: PeerId, entity_id: EntityId) -> bool {
        let Some(entities) = self.explicit_peer_interest.get_mut(&peer_id) else {
            return false;
        };
        let removed = entities.remove(&entity_id);
        if entities.is_empty() {
            self.explicit_peer_interest.remove(&peer_id);
        }
        removed
    }

    pub fn rank_entities(
        &self,
        context: &PeerRelevanceContext,
        entities: &[EntityRelevance],
    ) -> Result<Vec<RelevanceDecision>, NetworkError> {
        context.validate()?;
        let mut decisions = Vec::new();

        for entity in entities {
            entity.validate()?;
            let decision = self.decision_for_entity(context, *entity);
            if let Some(decision) = decision {
                decisions.push(decision);
            }
        }

        decisions.sort_by(|left, right| {
            right
                .score
                .cmp(&left.score)
                .then_with(|| {
                    left.distance_sq
                        .partial_cmp(&right.distance_sq)
                        .unwrap_or(std::cmp::Ordering::Equal)
                })
                .then_with(|| left.entity_id.cmp(&right.entity_id))
        });
        decisions.truncate(self.config.max_entities_per_peer);
        Ok(decisions)
    }

    pub fn relevant_entities(
        &self,
        context: &PeerRelevanceContext,
        entities: &[EntityRelevance],
    ) -> Result<BTreeSet<EntityId>, NetworkError> {
        Ok(self
            .rank_entities(context, entities)?
            .into_iter()
            .map(|decision| decision.entity_id)
            .collect())
    }

    pub fn config(&self) -> &RelevanceFilterConfig {
        &self.config
    }

    pub fn config_mut(&mut self) -> &mut RelevanceFilterConfig {
        &mut self.config
    }

    fn decision_for_entity(
        &self,
        context: &PeerRelevanceContext,
        entity: EntityRelevance,
    ) -> Option<RelevanceDecision> {
        let dx = entity.x - context.x;
        let dz = entity.z - context.z;
        let distance_sq = dx.mul_add(dx, dz * dz);
        let in_range = distance_sq <= entity.radius * entity.radius;
        let controlled = context.controlled_entity == Some(entity.entity_id);
        let explicit = self
            .explicit_peer_interest
            .get(&context.peer_id)
            .is_some_and(|entities| entities.contains(&entity.entity_id));
        let always_relevant = self.always_relevant.contains(&entity.entity_id);
        let same_team = context
            .team_id
            .is_some_and(|team_id| team_id == entity.team_id);

        if !in_range
            && !always_relevant
            && !explicit
            && !(controlled && self.config.include_out_of_range_owned_entities)
        {
            return None;
        }

        let mut score = 0;
        let mut reason = RelevanceReason::InRange;
        if in_range {
            score += 100;
        }
        if same_team {
            score += self.config.same_team_bonus;
            reason = RelevanceReason::SharedTeam;
        }
        if explicit {
            score += 500;
            reason = RelevanceReason::ExplicitInterest;
        }
        if controlled {
            score += self.config.controlled_entity_bonus;
            reason = RelevanceReason::ControlledEntity;
        }
        if always_relevant {
            score += self.config.always_relevant_bonus;
            reason = RelevanceReason::AlwaysRelevant;
        }

        let distance = distance_sq.sqrt();
        score -= distance.round() as i32 * self.config.distance_penalty_per_unit;

        Some(RelevanceDecision {
            entity_id: entity.entity_id,
            distance_sq,
            score,
            reason,
        })
    }
}

fn validate_peer_entity(peer_id: PeerId, entity_id: EntityId) -> Result<(), NetworkError> {
    if peer_id == 0 {
        return Err(NetworkError::InvalidOperation(
            "peer_id 0 is reserved".to_string(),
        ));
    }
    if entity_id == 0 {
        return Err(NetworkError::InvalidOperation(
            "entity_id 0 is reserved".to_string(),
        ));
    }
    Ok(())
}
