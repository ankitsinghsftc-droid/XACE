//! Semantic event to engine playback binding model.
//!
//! Bindings are data, not engine behavior. They say "when this semantic event
//! happens, request this animation/audio/VFX asset for this entity." Adapters
//! remain responsible for actual playback in Godot, Unity, Unreal, or other
//! engines.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

use crate::assets::{AssetReference, AssetType};
use crate::entity_id::EntityID;
use crate::events::event_struct::Event;
use crate::events::semantic_event_registry::{
    event_type_semantic_name, get_semantic_event, SemanticBindingTarget,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum SemanticPlaybackKind {
    Animation,
    Audio,
    Vfx,
}

impl SemanticPlaybackKind {
    pub fn binding_target(self) -> SemanticBindingTarget {
        match self {
            Self::Animation => SemanticBindingTarget::Animation,
            Self::Audio => SemanticBindingTarget::Audio,
            Self::Vfx => SemanticBindingTarget::Vfx,
        }
    }

    pub fn accepts_asset_type(self, asset_type: &AssetType) -> bool {
        match self {
            Self::Animation => matches!(
                asset_type,
                AssetType::AnimationController | AssetType::AnimationClip
            ),
            Self::Audio => asset_type.is_audio(),
            Self::Vfx => matches!(asset_type, AssetType::Particle),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum BindingEntitySelector {
    SourceEntity,
    TargetEntity,
    PayloadEntity { key: String },
    FixedEntity(EntityID),
}

impl BindingEntitySelector {
    pub fn resolve(&self, event: &Event) -> Option<EntityID> {
        match self {
            Self::SourceEntity => Some(event.source_entity_id),
            Self::TargetEntity => event.is_directed().then_some(event.target_entity_id),
            Self::PayloadEntity { key } => event.get_payload_u64(key),
            Self::FixedEntity(entity_id) => (*entity_id != 0).then_some(*entity_id),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SemanticAssetBinding {
    pub binding_id: String,
    pub event_name: String,
    pub playback_kind: SemanticPlaybackKind,
    pub asset: AssetReference,
    #[serde(default)]
    pub semantic_action: String,
    pub entity_selector: BindingEntitySelector,
    #[serde(default)]
    pub parameters: BTreeMap<String, String>,
    #[serde(default = "default_true")]
    pub enabled: bool,
    #[serde(default)]
    pub priority: i32,
}

impl SemanticAssetBinding {
    pub fn new(
        binding_id: impl Into<String>,
        event_name: impl Into<String>,
        playback_kind: SemanticPlaybackKind,
        asset: AssetReference,
        entity_selector: BindingEntitySelector,
    ) -> Self {
        Self {
            binding_id: binding_id.into(),
            event_name: event_name.into(),
            playback_kind,
            asset,
            semantic_action: String::new(),
            entity_selector,
            parameters: BTreeMap::new(),
            enabled: true,
            priority: 0,
        }
    }

    pub fn with_semantic_action(mut self, semantic_action: impl Into<String>) -> Self {
        self.semantic_action = semantic_action.into();
        self
    }

    pub fn with_parameter(mut self, key: impl Into<String>, value: impl Into<String>) -> Self {
        self.parameters.insert(key.into(), value.into());
        self
    }

    pub fn validate(&self) -> Result<(), SemanticBindingError> {
        if self.binding_id.trim().is_empty() {
            return Err(SemanticBindingError::InvalidBindingId);
        }
        let Some(definition) = get_semantic_event(&self.event_name) else {
            return Err(SemanticBindingError::UnknownEvent(self.event_name.clone()));
        };
        if !definition.supports_binding_target(self.playback_kind.binding_target()) {
            return Err(SemanticBindingError::UnsupportedBindingTarget {
                event_name: self.event_name.clone(),
                playback_kind: self.playback_kind,
            });
        }
        if !self
            .playback_kind
            .accepts_asset_type(&self.asset.asset_type)
        {
            return Err(SemanticBindingError::WrongAssetType {
                playback_kind: self.playback_kind,
                asset_type: self.asset.asset_type.clone(),
            });
        }
        if !self.asset.is_committable() {
            return Err(SemanticBindingError::UncommittableAsset(
                self.asset.id.clone(),
            ));
        }
        if let BindingEntitySelector::PayloadEntity { key } = &self.entity_selector {
            if key.trim().is_empty() {
                return Err(SemanticBindingError::InvalidPayloadEntityKey);
            }
        }
        Ok(())
    }

    pub fn resolve(&self, event: &Event) -> Option<PlaybackCommandRequest> {
        if !self.enabled || self.validate().is_err() {
            return None;
        }
        let event_name = event_type_semantic_name(&event.event_type)?;
        if event_name != self.event_name {
            return None;
        }
        let entity_id = self.entity_selector.resolve(event)?;
        Some(PlaybackCommandRequest {
            binding_id: self.binding_id.clone(),
            event_name: self.event_name.clone(),
            playback_kind: self.playback_kind,
            entity_id,
            asset: self.asset.clone(),
            semantic_action: self.semantic_action.clone(),
            parameters: self.parameters.clone(),
            priority: self.priority,
        })
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PlaybackCommandRequest {
    pub binding_id: String,
    pub event_name: String,
    pub playback_kind: SemanticPlaybackKind,
    pub entity_id: EntityID,
    pub asset: AssetReference,
    #[serde(default)]
    pub semantic_action: String,
    #[serde(default)]
    pub parameters: BTreeMap<String, String>,
    #[serde(default)]
    pub priority: i32,
}

#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct SemanticBindingTable {
    #[serde(default)]
    pub bindings: Vec<SemanticAssetBinding>,
}

impl SemanticBindingTable {
    pub fn new(bindings: Vec<SemanticAssetBinding>) -> Self {
        let mut table = Self { bindings };
        table.sort_deterministically();
        table
    }

    pub fn validate(&self) -> Result<(), SemanticBindingError> {
        let mut ids = std::collections::BTreeSet::new();
        for binding in &self.bindings {
            binding.validate()?;
            if !ids.insert(binding.binding_id.as_str()) {
                return Err(SemanticBindingError::DuplicateBindingId(
                    binding.binding_id.clone(),
                ));
            }
        }
        Ok(())
    }

    pub fn commands_for_event(&self, event: &Event) -> Vec<PlaybackCommandRequest> {
        let mut commands = self
            .bindings
            .iter()
            .filter_map(|binding| binding.resolve(event))
            .collect::<Vec<_>>();
        commands.sort_by(|left, right| {
            left.priority
                .cmp(&right.priority)
                .then_with(|| left.binding_id.cmp(&right.binding_id))
        });
        commands
    }

    fn sort_deterministically(&mut self) {
        self.bindings.sort_by(|left, right| {
            left.priority
                .cmp(&right.priority)
                .then_with(|| left.binding_id.cmp(&right.binding_id))
        });
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SemanticBindingError {
    InvalidBindingId,
    UnknownEvent(String),
    UnsupportedBindingTarget {
        event_name: String,
        playback_kind: SemanticPlaybackKind,
    },
    WrongAssetType {
        playback_kind: SemanticPlaybackKind,
        asset_type: AssetType,
    },
    UncommittableAsset(String),
    InvalidPayloadEntityKey,
    DuplicateBindingId(String),
}

impl std::fmt::Display for SemanticBindingError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidBindingId => write!(f, "binding_id must not be empty"),
            Self::UnknownEvent(event_name) => {
                write!(f, "unknown semantic event '{}'", event_name)
            }
            Self::UnsupportedBindingTarget {
                event_name,
                playback_kind,
            } => write!(
                f,
                "event '{}' does not support {:?} bindings",
                event_name, playback_kind
            ),
            Self::WrongAssetType {
                playback_kind,
                asset_type,
            } => write!(
                f,
                "{:?} binding cannot use asset type {:?}",
                playback_kind, asset_type
            ),
            Self::UncommittableAsset(asset_id) => {
                write!(f, "asset '{}' cannot be committed", asset_id)
            }
            Self::InvalidPayloadEntityKey => write!(f, "payload entity selector key is empty"),
            Self::DuplicateBindingId(binding_id) => {
                write!(f, "duplicate semantic binding id '{}'", binding_id)
            }
        }
    }
}

impl std::error::Error for SemanticBindingError {}

fn default_true() -> bool {
    true
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::assets::AssetStatus;
    use crate::events::semantic_event_registry::{
        domain_event, INTERACTION_ACCEPTED, INVENTORY_EQUIPPED,
    };
    use crate::runtime::phase_enum::PhaseEnum;

    fn event(name: &str) -> Event {
        Event::directed(1, 2, domain_event(name), 10, PhaseEnum::Simulation)
            .with_payload("actor_entity_id", "1")
            .with_payload("target_entity_id", "2")
            .with_payload("item_entity_id", "3")
    }

    #[test]
    fn animation_binding_accepts_animation_clip() {
        let binding = SemanticAssetBinding::new(
            "bind_pickup_anim",
            INTERACTION_ACCEPTED,
            SemanticPlaybackKind::Animation,
            AssetReference::placeholder("character_pickup_anim_clip_v1", AssetType::AnimationClip),
            BindingEntitySelector::SourceEntity,
        );

        assert_eq!(binding.validate(), Ok(()));
        let command = binding.resolve(&event(INTERACTION_ACCEPTED)).unwrap();
        assert_eq!(command.entity_id, 1);
        assert_eq!(command.playback_kind, SemanticPlaybackKind::Animation);
    }

    #[test]
    fn audio_binding_uses_payload_entity_selector() {
        let binding = SemanticAssetBinding::new(
            "bind_equip_sfx",
            INVENTORY_EQUIPPED,
            SemanticPlaybackKind::Audio,
            AssetReference::placeholder("item_equip_sfx_v1", AssetType::AudioClip),
            BindingEntitySelector::PayloadEntity {
                key: "item_entity_id".to_string(),
            },
        );

        let command = binding.resolve(&event(INVENTORY_EQUIPPED)).unwrap();
        assert_eq!(command.entity_id, 3);
    }

    #[test]
    fn wrong_asset_type_is_rejected() {
        let binding = SemanticAssetBinding::new(
            "bind_bad_audio",
            INVENTORY_EQUIPPED,
            SemanticPlaybackKind::Audio,
            AssetReference::placeholder("bad_mesh_v1", AssetType::Mesh),
            BindingEntitySelector::SourceEntity,
        );

        assert!(matches!(
            binding.validate(),
            Err(SemanticBindingError::WrongAssetType { .. })
        ));
    }

    #[test]
    fn disabled_binding_emits_no_command() {
        let mut binding = SemanticAssetBinding::new(
            "bind_disabled",
            INTERACTION_ACCEPTED,
            SemanticPlaybackKind::Vfx,
            AssetReference::placeholder("interaction_spark_particle_v1", AssetType::Particle),
            BindingEntitySelector::TargetEntity,
        );
        binding.enabled = false;

        assert!(binding.resolve(&event(INTERACTION_ACCEPTED)).is_none());
    }

    #[test]
    fn table_orders_commands_deterministically() {
        let mut first = SemanticAssetBinding::new(
            "b",
            INTERACTION_ACCEPTED,
            SemanticPlaybackKind::Vfx,
            AssetReference::placeholder("interaction_spark_particle_v1", AssetType::Particle),
            BindingEntitySelector::TargetEntity,
        );
        first.priority = 10;
        let second = SemanticAssetBinding::new(
            "a",
            INTERACTION_ACCEPTED,
            SemanticPlaybackKind::Audio,
            AssetReference::placeholder("interaction_sfx_v1", AssetType::AudioClip),
            BindingEntitySelector::SourceEntity,
        );
        let table = SemanticBindingTable::new(vec![first, second]);

        let commands = table.commands_for_event(&event(INTERACTION_ACCEPTED));
        assert_eq!(commands.len(), 2);
        assert_eq!(commands[0].binding_id, "a");
        assert_eq!(commands[1].binding_id, "b");
    }

    #[test]
    fn uncommittable_asset_is_rejected() {
        let mut asset = AssetReference::placeholder("missing_anim_v1", AssetType::AnimationClip);
        asset.status = AssetStatus::Unresolved;
        let binding = SemanticAssetBinding::new(
            "bind_unresolved",
            INTERACTION_ACCEPTED,
            SemanticPlaybackKind::Animation,
            asset,
            BindingEntitySelector::SourceEntity,
        );

        assert!(matches!(
            binding.validate(),
            Err(SemanticBindingError::UncommittableAsset(_))
        ));
    }
}
