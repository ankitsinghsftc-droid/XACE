use std::collections::{BTreeMap, BTreeSet};

use serde::{Deserialize, Serialize};

use crate::{EntityId, NetworkError, PeerId};

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub enum InterestZoneShape {
    Global,
    Circle {
        x: f32,
        z: f32,
        radius: f32,
    },
    Aabb {
        min_x: f32,
        min_z: f32,
        max_x: f32,
        max_z: f32,
    },
}

impl InterestZoneShape {
    pub fn contains(self, x: f32, z: f32) -> bool {
        match self {
            Self::Global => true,
            Self::Circle {
                x: center_x,
                z: center_z,
                radius,
            } => {
                let dx = x - center_x;
                let dz = z - center_z;
                dx.mul_add(dx, dz * dz) <= radius * radius
            }
            Self::Aabb {
                min_x,
                min_z,
                max_x,
                max_z,
            } => x >= min_x && x <= max_x && z >= min_z && z <= max_z,
        }
    }

    pub fn validate(self) -> Result<(), NetworkError> {
        match self {
            Self::Global => Ok(()),
            Self::Circle { x, z, radius } => {
                if !x.is_finite() || !z.is_finite() || !radius.is_finite() || radius < 0.0 {
                    return Err(NetworkError::InvalidOperation(
                        "interest zone circle has invalid bounds".to_string(),
                    ));
                }
                Ok(())
            }
            Self::Aabb {
                min_x,
                min_z,
                max_x,
                max_z,
            } => {
                if !min_x.is_finite()
                    || !min_z.is_finite()
                    || !max_x.is_finite()
                    || !max_z.is_finite()
                    || min_x > max_x
                    || min_z > max_z
                {
                    return Err(NetworkError::InvalidOperation(
                        "interest zone aabb has invalid bounds".to_string(),
                    ));
                }
                Ok(())
            }
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct InterestZone {
    pub zone_id: String,
    pub entity_ids: BTreeSet<EntityId>,
    pub peer_ids: BTreeSet<PeerId>,
    pub shape: InterestZoneShape,
    pub priority: u16,
    pub always_relevant: bool,
}

impl InterestZone {
    pub fn new(zone_id: impl Into<String>) -> Self {
        Self {
            zone_id: zone_id.into(),
            entity_ids: BTreeSet::new(),
            peer_ids: BTreeSet::new(),
            shape: InterestZoneShape::Global,
            priority: 0,
            always_relevant: false,
        }
    }

    pub fn with_shape(mut self, shape: InterestZoneShape) -> Self {
        self.shape = shape;
        self
    }

    pub fn with_priority(mut self, priority: u16) -> Self {
        self.priority = priority;
        self
    }

    pub fn always_relevant(mut self) -> Self {
        self.always_relevant = true;
        self
    }

    pub fn add_entity(&mut self, entity_id: EntityId) -> Result<(), NetworkError> {
        validate_entity_id(entity_id)?;
        self.entity_ids.insert(entity_id);
        Ok(())
    }

    pub fn remove_entity(&mut self, entity_id: EntityId) -> bool {
        self.entity_ids.remove(&entity_id)
    }

    pub fn add_peer(&mut self, peer_id: PeerId) -> Result<(), NetworkError> {
        validate_peer_id(peer_id)?;
        self.peer_ids.insert(peer_id);
        Ok(())
    }

    pub fn remove_peer(&mut self, peer_id: PeerId) -> bool {
        self.peer_ids.remove(&peer_id)
    }

    pub fn contains_position(&self, x: f32, z: f32) -> bool {
        self.shape.contains(x, z)
    }

    pub fn validate(&self) -> Result<(), NetworkError> {
        if self.zone_id.trim().is_empty() {
            return Err(NetworkError::InvalidOperation(
                "interest zone id cannot be empty".to_string(),
            ));
        }
        self.shape.validate()?;
        for entity_id in &self.entity_ids {
            validate_entity_id(*entity_id)?;
        }
        for peer_id in &self.peer_ids {
            validate_peer_id(*peer_id)?;
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InterestZoneDiff {
    pub zone_id: String,
    pub added_entities: BTreeSet<EntityId>,
    pub removed_entities: BTreeSet<EntityId>,
    pub added_peers: BTreeSet<PeerId>,
    pub removed_peers: BTreeSet<PeerId>,
}

impl InterestZoneDiff {
    fn empty(zone_id: impl Into<String>) -> Self {
        Self {
            zone_id: zone_id.into(),
            added_entities: BTreeSet::new(),
            removed_entities: BTreeSet::new(),
            added_peers: BTreeSet::new(),
            removed_peers: BTreeSet::new(),
        }
    }

    pub fn is_empty(&self) -> bool {
        self.added_entities.is_empty()
            && self.removed_entities.is_empty()
            && self.added_peers.is_empty()
            && self.removed_peers.is_empty()
    }
}

#[derive(Debug, Clone, Default)]
pub struct InterestZoneManager {
    zones: BTreeMap<String, InterestZone>,
    peer_zones: BTreeMap<PeerId, BTreeSet<String>>,
    entity_zones: BTreeMap<EntityId, BTreeSet<String>>,
}

impl InterestZoneManager {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn upsert_zone(&mut self, zone: InterestZone) {
        let _ = self.upsert_zone_result(zone);
    }

    pub fn upsert_zone_result(
        &mut self,
        zone: InterestZone,
    ) -> Result<InterestZoneDiff, NetworkError> {
        zone.validate()?;
        let zone_id = zone.zone_id.clone();
        let mut diff = InterestZoneDiff::empty(zone_id.clone());

        if let Some(previous) = self.zones.remove(&zone_id) {
            diff.added_entities = zone
                .entity_ids
                .difference(&previous.entity_ids)
                .copied()
                .collect();
            diff.removed_entities = previous
                .entity_ids
                .difference(&zone.entity_ids)
                .copied()
                .collect();
            diff.added_peers = zone
                .peer_ids
                .difference(&previous.peer_ids)
                .copied()
                .collect();
            diff.removed_peers = previous
                .peer_ids
                .difference(&zone.peer_ids)
                .copied()
                .collect();
            self.deindex_zone(&previous);
        } else {
            diff.added_entities = zone.entity_ids.clone();
            diff.added_peers = zone.peer_ids.clone();
        }

        self.index_zone(&zone);
        self.zones.insert(zone_id, zone);
        Ok(diff)
    }

    pub fn remove_zone(&mut self, zone_id: &str) -> Option<InterestZone> {
        let zone = self.zones.remove(zone_id)?;
        self.deindex_zone(&zone);
        Some(zone)
    }

    pub fn add_entity_to_zone(
        &mut self,
        zone_id: &str,
        entity_id: EntityId,
    ) -> Result<bool, NetworkError> {
        validate_entity_id(entity_id)?;
        let zone = self.require_zone_mut(zone_id)?;
        let inserted = zone.entity_ids.insert(entity_id);
        if inserted {
            self.entity_zones
                .entry(entity_id)
                .or_default()
                .insert(zone_id.to_string());
        }
        Ok(inserted)
    }

    pub fn remove_entity_from_zone(
        &mut self,
        zone_id: &str,
        entity_id: EntityId,
    ) -> Result<bool, NetworkError> {
        let zone = self.require_zone_mut(zone_id)?;
        let removed = zone.entity_ids.remove(&entity_id);
        if removed {
            remove_index_value(&mut self.entity_zones, entity_id, zone_id);
        }
        Ok(removed)
    }

    pub fn add_peer_to_zone(
        &mut self,
        zone_id: &str,
        peer_id: PeerId,
    ) -> Result<bool, NetworkError> {
        validate_peer_id(peer_id)?;
        let zone = self.require_zone_mut(zone_id)?;
        let inserted = zone.peer_ids.insert(peer_id);
        if inserted {
            self.peer_zones
                .entry(peer_id)
                .or_default()
                .insert(zone_id.to_string());
        }
        Ok(inserted)
    }

    pub fn remove_peer_from_zone(
        &mut self,
        zone_id: &str,
        peer_id: PeerId,
    ) -> Result<bool, NetworkError> {
        let zone = self.require_zone_mut(zone_id)?;
        let removed = zone.peer_ids.remove(&peer_id);
        if removed {
            remove_index_value(&mut self.peer_zones, peer_id, zone_id);
        }
        Ok(removed)
    }

    pub fn zones_containing_position(&self, x: f32, z: f32) -> Vec<&InterestZone> {
        self.zones
            .values()
            .filter(|zone| zone.contains_position(x, z))
            .collect()
    }

    pub fn relevant_entities_for_peer(&self, peer_id: PeerId) -> BTreeSet<EntityId> {
        let Some(zone_ids) = self.peer_zones.get(&peer_id) else {
            return BTreeSet::new();
        };
        let mut entities = BTreeSet::new();
        for zone_id in zone_ids {
            if let Some(zone) = self.zones.get(zone_id) {
                entities.extend(zone.entity_ids.iter().copied());
            }
        }
        entities
    }

    pub fn relevant_peers_for_entity(&self, entity_id: EntityId) -> BTreeSet<PeerId> {
        let Some(zone_ids) = self.entity_zones.get(&entity_id) else {
            return BTreeSet::new();
        };
        let mut peers = BTreeSet::new();
        for zone_id in zone_ids {
            if let Some(zone) = self.zones.get(zone_id) {
                peers.extend(zone.peer_ids.iter().copied());
            }
        }
        peers
    }

    pub fn zone_ids_for_peer(&self, peer_id: PeerId) -> BTreeSet<String> {
        self.peer_zones.get(&peer_id).cloned().unwrap_or_default()
    }

    pub fn zone_ids_for_entity(&self, entity_id: EntityId) -> BTreeSet<String> {
        self.entity_zones
            .get(&entity_id)
            .cloned()
            .unwrap_or_default()
    }

    pub fn zone(&self, zone_id: &str) -> Option<&InterestZone> {
        self.zones.get(zone_id)
    }

    pub fn zones(&self) -> impl Iterator<Item = &InterestZone> {
        self.zones.values()
    }

    pub fn len(&self) -> usize {
        self.zones.len()
    }

    pub fn is_empty(&self) -> bool {
        self.zones.is_empty()
    }

    fn require_zone_mut(&mut self, zone_id: &str) -> Result<&mut InterestZone, NetworkError> {
        self.zones.get_mut(zone_id).ok_or_else(|| {
            NetworkError::InvalidOperation(format!("interest zone {zone_id} does not exist"))
        })
    }

    fn index_zone(&mut self, zone: &InterestZone) {
        for entity_id in &zone.entity_ids {
            self.entity_zones
                .entry(*entity_id)
                .or_default()
                .insert(zone.zone_id.clone());
        }
        for peer_id in &zone.peer_ids {
            self.peer_zones
                .entry(*peer_id)
                .or_default()
                .insert(zone.zone_id.clone());
        }
    }

    fn deindex_zone(&mut self, zone: &InterestZone) {
        for entity_id in &zone.entity_ids {
            remove_index_value(&mut self.entity_zones, *entity_id, &zone.zone_id);
        }
        for peer_id in &zone.peer_ids {
            remove_index_value(&mut self.peer_zones, *peer_id, &zone.zone_id);
        }
    }
}

fn remove_index_value<K>(index: &mut BTreeMap<K, BTreeSet<String>>, key: K, zone_id: &str)
where
    K: Ord + Copy,
{
    if let Some(zone_ids) = index.get_mut(&key) {
        zone_ids.remove(zone_id);
        if zone_ids.is_empty() {
            index.remove(&key);
        }
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
