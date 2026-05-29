use std::collections::{BTreeMap, BTreeSet};

use serde::{Deserialize, Serialize};

use crate::{EntityId, NetworkError, PeerId, Tick};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum AuthorityScope {
    Exclusive,
    Shared,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum AuthoritySource {
    Explicit,
    ServerFallback,
    Shared,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AuthorityRecord {
    pub entity_id: EntityId,
    pub owner_peer: Option<PeerId>,
    pub fallback_peer: Option<PeerId>,
    pub shared_peers: BTreeSet<PeerId>,
    pub scope: AuthorityScope,
    pub version: u64,
    pub assigned_tick: Tick,
    pub updated_tick: Tick,
    pub transfer_locked: bool,
    pub source: AuthoritySource,
}

impl AuthorityRecord {
    pub fn exclusive(
        entity_id: EntityId,
        owner_peer: PeerId,
        assigned_tick: Tick,
        version: u64,
    ) -> Self {
        Self {
            entity_id,
            owner_peer: Some(owner_peer),
            fallback_peer: None,
            shared_peers: BTreeSet::new(),
            scope: AuthorityScope::Exclusive,
            version,
            assigned_tick,
            updated_tick: assigned_tick,
            transfer_locked: false,
            source: AuthoritySource::Explicit,
        }
    }

    pub fn shared(
        entity_id: EntityId,
        shared_peers: BTreeSet<PeerId>,
        assigned_tick: Tick,
        version: u64,
    ) -> Self {
        Self {
            entity_id,
            owner_peer: None,
            fallback_peer: None,
            shared_peers,
            scope: AuthorityScope::Shared,
            version,
            assigned_tick,
            updated_tick: assigned_tick,
            transfer_locked: false,
            source: AuthoritySource::Shared,
        }
    }

    pub fn primary_authority(&self) -> Option<PeerId> {
        self.owner_peer.or(self.fallback_peer)
    }

    pub fn permits_peer(&self, peer_id: PeerId) -> bool {
        match self.scope {
            AuthorityScope::Exclusive => self.primary_authority() == Some(peer_id),
            AuthorityScope::Shared => self.shared_peers.contains(&peer_id),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AuthoritySnapshot {
    pub server_peer: Option<PeerId>,
    pub generation: u64,
    pub records: Vec<AuthorityRecord>,
}

#[derive(Debug, Clone, Default)]
pub struct AuthorityResolver {
    entity_authority: BTreeMap<EntityId, AuthorityRecord>,
    server_peer: Option<PeerId>,
    generation: u64,
}

impl AuthorityResolver {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with_server(peer_id: PeerId) -> Result<Self, NetworkError> {
        let mut resolver = Self::new();
        resolver.try_set_server_peer(peer_id)?;
        Ok(resolver)
    }

    pub fn set_server_peer(&mut self, peer_id: PeerId) {
        if peer_id != 0 {
            self.server_peer = Some(peer_id);
            self.generation = self.generation.saturating_add(1);
        }
    }

    pub fn try_set_server_peer(&mut self, peer_id: PeerId) -> Result<(), NetworkError> {
        validate_peer_id(peer_id)?;
        self.server_peer = Some(peer_id);
        self.generation = self.generation.saturating_add(1);
        Ok(())
    }

    pub fn clear_server_peer(&mut self) {
        self.server_peer = None;
        self.generation = self.generation.saturating_add(1);
    }

    pub fn assign(&mut self, entity_id: EntityId, peer_id: PeerId) {
        if entity_id == 0 || peer_id == 0 {
            return;
        }
        let _ = self.assign_at(entity_id, peer_id, 0);
    }

    pub fn assign_at(
        &mut self,
        entity_id: EntityId,
        peer_id: PeerId,
        tick: Tick,
    ) -> Result<u64, NetworkError> {
        validate_entity_id(entity_id)?;
        validate_peer_id(peer_id)?;
        let next_version = self.next_version();
        match self.entity_authority.get_mut(&entity_id) {
            Some(record) => {
                if record.transfer_locked {
                    return Err(NetworkError::InvalidOperation(format!(
                        "entity {} authority is transfer locked",
                        entity_id
                    )));
                }
                record.owner_peer = Some(peer_id);
                record.fallback_peer = None;
                record.shared_peers.clear();
                record.scope = AuthorityScope::Exclusive;
                record.version = next_version;
                record.updated_tick = tick;
                record.source = AuthoritySource::Explicit;
            }
            None => {
                self.entity_authority.insert(
                    entity_id,
                    AuthorityRecord::exclusive(entity_id, peer_id, tick, next_version),
                );
            }
        }
        self.generation = next_version;
        Ok(next_version)
    }

    pub fn assign_with_server_fallback(
        &mut self,
        entity_id: EntityId,
        owner_peer: Option<PeerId>,
        fallback_peer: Option<PeerId>,
        tick: Tick,
    ) -> Result<u64, NetworkError> {
        validate_entity_id(entity_id)?;
        if let Some(peer_id) = owner_peer {
            validate_peer_id(peer_id)?;
        }
        if let Some(peer_id) = fallback_peer {
            validate_peer_id(peer_id)?;
        }
        let next_version = self.next_version();
        let fallback = fallback_peer.or(self.server_peer);
        let record = self
            .entity_authority
            .entry(entity_id)
            .or_insert_with(|| AuthorityRecord {
                entity_id,
                owner_peer,
                fallback_peer: fallback,
                shared_peers: BTreeSet::new(),
                scope: AuthorityScope::Exclusive,
                version: next_version,
                assigned_tick: tick,
                updated_tick: tick,
                transfer_locked: false,
                source: AuthoritySource::ServerFallback,
            });
        if record.transfer_locked {
            return Err(NetworkError::InvalidOperation(format!(
                "entity {} authority is transfer locked",
                entity_id
            )));
        }
        record.owner_peer = owner_peer;
        record.fallback_peer = fallback;
        record.shared_peers.clear();
        record.scope = AuthorityScope::Exclusive;
        record.version = next_version;
        record.updated_tick = tick;
        record.source = AuthoritySource::ServerFallback;
        self.generation = next_version;
        Ok(next_version)
    }

    pub fn assign_shared(
        &mut self,
        entity_id: EntityId,
        peers: impl IntoIterator<Item = PeerId>,
        tick: Tick,
    ) -> Result<u64, NetworkError> {
        validate_entity_id(entity_id)?;
        let shared_peers = peers
            .into_iter()
            .try_fold(BTreeSet::new(), |mut set, peer_id| {
                validate_peer_id(peer_id)?;
                set.insert(peer_id);
                Ok::<_, NetworkError>(set)
            })?;
        if shared_peers.is_empty() {
            return Err(NetworkError::InvalidOperation(
                "shared authority requires at least one peer".to_string(),
            ));
        }
        let next_version = self.next_version();
        match self.entity_authority.get_mut(&entity_id) {
            Some(record) => {
                if record.transfer_locked {
                    return Err(NetworkError::InvalidOperation(format!(
                        "entity {} authority is transfer locked",
                        entity_id
                    )));
                }
                *record = AuthorityRecord::shared(entity_id, shared_peers, tick, next_version);
            }
            None => {
                self.entity_authority.insert(
                    entity_id,
                    AuthorityRecord::shared(entity_id, shared_peers, tick, next_version),
                );
            }
        }
        self.generation = next_version;
        Ok(next_version)
    }

    pub fn release(
        &mut self,
        entity_id: EntityId,
    ) -> Result<Option<AuthorityRecord>, NetworkError> {
        validate_entity_id(entity_id)?;
        let removed = self.entity_authority.remove(&entity_id);
        if removed.is_some() {
            self.generation = self.generation.saturating_add(1);
        }
        Ok(removed)
    }

    pub fn transfer(
        &mut self,
        entity_id: EntityId,
        from_peer: PeerId,
        to_peer: PeerId,
        tick: Tick,
    ) -> Result<u64, NetworkError> {
        self.require_authority(entity_id, from_peer)?;
        self.assign_at(entity_id, to_peer, tick)
    }

    pub fn lock_entity(&mut self, entity_id: EntityId) -> Result<(), NetworkError> {
        let record = self.require_record_mut(entity_id)?;
        record.transfer_locked = true;
        self.generation = self.generation.saturating_add(1);
        Ok(())
    }

    pub fn unlock_entity(&mut self, entity_id: EntityId) -> Result<(), NetworkError> {
        let record = self.require_record_mut(entity_id)?;
        record.transfer_locked = false;
        self.generation = self.generation.saturating_add(1);
        Ok(())
    }

    pub fn authority_for(&self, entity_id: EntityId) -> Option<PeerId> {
        match self.entity_authority.get(&entity_id) {
            Some(record) if record.scope == AuthorityScope::Shared => None,
            Some(record) => record.primary_authority().or(self.server_peer),
            None => self.server_peer,
        }
    }

    pub fn can_peer_write(&self, entity_id: EntityId, peer_id: PeerId) -> bool {
        if peer_id == 0 {
            return false;
        }
        match self.entity_authority.get(&entity_id) {
            Some(record) => {
                record.permits_peer(peer_id)
                    || (record.scope == AuthorityScope::Exclusive
                        && record.primary_authority().is_none()
                        && self.server_peer == Some(peer_id))
            }
            None => self.server_peer == Some(peer_id),
        }
    }

    pub fn require_authority(
        &self,
        entity_id: EntityId,
        peer_id: PeerId,
    ) -> Result<(), NetworkError> {
        if self.can_peer_write(entity_id, peer_id) {
            Ok(())
        } else {
            Err(NetworkError::AuthorityDenied { entity_id, peer_id })
        }
    }

    pub fn record_for(&self, entity_id: EntityId) -> Option<&AuthorityRecord> {
        self.entity_authority.get(&entity_id)
    }

    pub fn require_record(&self, entity_id: EntityId) -> Result<&AuthorityRecord, NetworkError> {
        self.entity_authority.get(&entity_id).ok_or_else(|| {
            NetworkError::InvalidOperation(format!(
                "entity {} has no explicit authority record",
                entity_id
            ))
        })
    }

    pub fn entities_for_peer(&self, peer_id: PeerId) -> BTreeSet<EntityId> {
        self.entity_authority
            .iter()
            .filter_map(|(&entity_id, record)| record.permits_peer(peer_id).then_some(entity_id))
            .collect()
    }

    pub fn shared_entities_for_peer(&self, peer_id: PeerId) -> BTreeSet<EntityId> {
        self.entity_authority
            .iter()
            .filter_map(|(&entity_id, record)| {
                (record.scope == AuthorityScope::Shared && record.shared_peers.contains(&peer_id))
                    .then_some(entity_id)
            })
            .collect()
    }

    pub fn entity_ids(&self) -> BTreeSet<EntityId> {
        self.entity_authority.keys().copied().collect()
    }

    pub fn server_peer(&self) -> Option<PeerId> {
        self.server_peer
    }

    pub fn generation(&self) -> u64 {
        self.generation
    }

    pub fn is_transfer_locked(&self, entity_id: EntityId) -> bool {
        self.entity_authority
            .get(&entity_id)
            .is_some_and(|record| record.transfer_locked)
    }

    pub fn snapshot(&self) -> AuthoritySnapshot {
        AuthoritySnapshot {
            server_peer: self.server_peer,
            generation: self.generation,
            records: self.entity_authority.values().cloned().collect(),
        }
    }

    pub fn restore(snapshot: AuthoritySnapshot) -> Result<Self, NetworkError> {
        if let Some(peer_id) = snapshot.server_peer {
            validate_peer_id(peer_id)?;
        }
        let mut entity_authority = BTreeMap::new();
        for record in snapshot.records {
            validate_entity_id(record.entity_id)?;
            if let Some(peer_id) = record.owner_peer {
                validate_peer_id(peer_id)?;
            }
            if let Some(peer_id) = record.fallback_peer {
                validate_peer_id(peer_id)?;
            }
            for peer_id in &record.shared_peers {
                validate_peer_id(*peer_id)?;
            }
            if entity_authority.insert(record.entity_id, record).is_some() {
                return Err(NetworkError::InvalidOperation(
                    "duplicate authority record in snapshot".to_string(),
                ));
            }
        }
        Ok(Self {
            entity_authority,
            server_peer: snapshot.server_peer,
            generation: snapshot.generation,
        })
    }

    fn require_record_mut(
        &mut self,
        entity_id: EntityId,
    ) -> Result<&mut AuthorityRecord, NetworkError> {
        self.entity_authority.get_mut(&entity_id).ok_or_else(|| {
            NetworkError::InvalidOperation(format!(
                "entity {} has no explicit authority record",
                entity_id
            ))
        })
    }

    fn next_version(&self) -> u64 {
        self.generation.saturating_add(1)
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
