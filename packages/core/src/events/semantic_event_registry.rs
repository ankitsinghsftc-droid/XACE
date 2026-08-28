//! Canonical semantic event registry.
//!
//! Domain events still travel through `EventType::Domain(String)`, but creator
//! tools need more than raw strings. This registry gives builder, adapters, and
//! binding tools a stable list of event names, required payload keys, and valid
//! semantic binding targets.

use crate::events::event_type::EventType;

pub const MOVEMENT_JUMP_STARTED: &str = "movement.jump_started";
pub const MOVEMENT_LANDED: &str = "movement.landed";

pub const INTERACTION_FOCUSED: &str = "interaction.focused";
pub const INTERACTION_UNFOCUSED: &str = "interaction.unfocused";
pub const INTERACTION_INTERACTED: &str = "interaction.interacted";
pub const INTERACTION_ACCEPTED: &str = "interaction.accepted";

pub const INVENTORY_PICKUP_REQUESTED: &str = "inventory.pickup_requested";
pub const INVENTORY_PICKUP_ACCEPTED: &str = "inventory.pickup_accepted";
pub const INVENTORY_PICKUP_REJECTED: &str = "inventory.pickup_rejected";
pub const INVENTORY_EQUIPPED: &str = "inventory.equipped";
pub const INVENTORY_EQUIP_REJECTED: &str = "inventory.equip_rejected";
pub const INVENTORY_DROPPED: &str = "inventory.dropped";
pub const INVENTORY_DROP_REJECTED: &str = "inventory.drop_rejected";

pub const COMBAT_ATTACK_STARTED: &str = "combat.attack_started";
pub const COMBAT_HIT_CONFIRMED: &str = "combat.hit_confirmed";
pub const COMBAT_BLOCKED: &str = "combat.blocked";
pub const COMBAT_PARRIED: &str = "combat.parried";
pub const COMBAT_KILLED: &str = "combat.killed";

pub const ANIMATION_COMMAND_REQUESTED: &str = "animation.command_requested";
pub const ANIMATION_PLAYBACK_STARTED: &str = "animation.playback_started";
pub const ANIMATION_PLAYBACK_COMPLETED: &str = "animation.playback_completed";

pub const AUDIO_PLAYBACK_REQUESTED: &str = "audio.playback_requested";
pub const AUDIO_PLAYBACK_COMPLETED: &str = "audio.playback_completed";

pub const VFX_PLAYBACK_REQUESTED: &str = "vfx.playback_requested";
pub const VFX_PLAYBACK_COMPLETED: &str = "vfx.playback_completed";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum SemanticEventCategory {
    Movement,
    Interaction,
    Inventory,
    Combat,
    Animation,
    Audio,
    Vfx,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum SemanticBindingTarget {
    GameplaySystem,
    BuilderTimeline,
    Animation,
    Audio,
    Vfx,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SemanticEventDefinition {
    pub name: &'static str,
    pub domain: &'static str,
    pub category: SemanticEventCategory,
    pub summary: &'static str,
    pub required_payload_keys: &'static [&'static str],
    pub binding_targets: &'static [SemanticBindingTarget],
    pub persistent: bool,
    pub replay_relevant: bool,
}

impl SemanticEventDefinition {
    pub fn event_type(&self) -> EventType {
        EventType::Domain(self.name.to_string())
    }

    pub fn supports_binding_target(&self, target: SemanticBindingTarget) -> bool {
        self.binding_targets.contains(&target)
    }
}

const TIMELINE: &[SemanticBindingTarget] = &[
    SemanticBindingTarget::GameplaySystem,
    SemanticBindingTarget::BuilderTimeline,
];

const AV_TIMELINE: &[SemanticBindingTarget] = &[
    SemanticBindingTarget::GameplaySystem,
    SemanticBindingTarget::BuilderTimeline,
    SemanticBindingTarget::Animation,
    SemanticBindingTarget::Audio,
    SemanticBindingTarget::Vfx,
];

const ANIMATION_BINDING: &[SemanticBindingTarget] = &[
    SemanticBindingTarget::BuilderTimeline,
    SemanticBindingTarget::Animation,
];

const AUDIO_BINDING: &[SemanticBindingTarget] = &[
    SemanticBindingTarget::BuilderTimeline,
    SemanticBindingTarget::Audio,
];

const VFX_BINDING: &[SemanticBindingTarget] = &[
    SemanticBindingTarget::BuilderTimeline,
    SemanticBindingTarget::Vfx,
];

pub const BUILTIN_SEMANTIC_EVENTS: &[SemanticEventDefinition] = &[
    SemanticEventDefinition {
        name: MOVEMENT_JUMP_STARTED,
        domain: "movement",
        category: SemanticEventCategory::Movement,
        summary: "A kinematic actor consumed a jump request.",
        required_payload_keys: &["actor_entity_id", "movement_state"],
        binding_targets: AV_TIMELINE,
        persistent: false,
        replay_relevant: true,
    },
    SemanticEventDefinition {
        name: MOVEMENT_LANDED,
        domain: "movement",
        category: SemanticEventCategory::Movement,
        summary: "A kinematic actor transitioned from airborne to grounded.",
        required_payload_keys: &["actor_entity_id", "movement_state"],
        binding_targets: AV_TIMELINE,
        persistent: false,
        replay_relevant: true,
    },
    SemanticEventDefinition {
        name: INTERACTION_FOCUSED,
        domain: "interaction",
        category: SemanticEventCategory::Interaction,
        summary: "An actor focused an interactable target.",
        required_payload_keys: &["actor_entity_id", "target_entity_id", "interaction_state"],
        binding_targets: TIMELINE,
        persistent: false,
        replay_relevant: true,
    },
    SemanticEventDefinition {
        name: INTERACTION_UNFOCUSED,
        domain: "interaction",
        category: SemanticEventCategory::Interaction,
        summary: "An actor stopped focusing an interactable target.",
        required_payload_keys: &["actor_entity_id", "target_entity_id", "interaction_state"],
        binding_targets: TIMELINE,
        persistent: false,
        replay_relevant: true,
    },
    SemanticEventDefinition {
        name: INTERACTION_INTERACTED,
        domain: "interaction",
        category: SemanticEventCategory::Interaction,
        summary: "An actor performed an interaction intent on a target.",
        required_payload_keys: &[
            "actor_entity_id",
            "target_entity_id",
            "interaction_state",
            "interaction_type",
        ],
        binding_targets: AV_TIMELINE,
        persistent: false,
        replay_relevant: true,
    },
    SemanticEventDefinition {
        name: INTERACTION_ACCEPTED,
        domain: "interaction",
        category: SemanticEventCategory::Interaction,
        summary: "A target accepted an actor interaction.",
        required_payload_keys: &[
            "actor_entity_id",
            "target_entity_id",
            "interaction_state",
            "interaction_type",
        ],
        binding_targets: AV_TIMELINE,
        persistent: false,
        replay_relevant: true,
    },
    SemanticEventDefinition {
        name: INVENTORY_PICKUP_REQUESTED,
        domain: "inventory",
        category: SemanticEventCategory::Inventory,
        summary: "An actor requested to pick up an item.",
        required_payload_keys: &["actor_entity_id", "item_entity_id", "inventory_state"],
        binding_targets: TIMELINE,
        persistent: false,
        replay_relevant: true,
    },
    SemanticEventDefinition {
        name: INVENTORY_PICKUP_ACCEPTED,
        domain: "inventory",
        category: SemanticEventCategory::Inventory,
        summary: "An item was added to an actor inventory.",
        required_payload_keys: &["actor_entity_id", "item_entity_id", "inventory_state"],
        binding_targets: AV_TIMELINE,
        persistent: true,
        replay_relevant: true,
    },
    SemanticEventDefinition {
        name: INVENTORY_PICKUP_REJECTED,
        domain: "inventory",
        category: SemanticEventCategory::Inventory,
        summary: "A pickup request was rejected.",
        required_payload_keys: &[
            "actor_entity_id",
            "item_entity_id",
            "inventory_state",
            "reason",
        ],
        binding_targets: TIMELINE,
        persistent: false,
        replay_relevant: true,
    },
    SemanticEventDefinition {
        name: INVENTORY_EQUIPPED,
        domain: "inventory",
        category: SemanticEventCategory::Inventory,
        summary: "An actor equipped an inventory item.",
        required_payload_keys: &["actor_entity_id", "item_entity_id", "inventory_state"],
        binding_targets: AV_TIMELINE,
        persistent: true,
        replay_relevant: true,
    },
    SemanticEventDefinition {
        name: INVENTORY_EQUIP_REJECTED,
        domain: "inventory",
        category: SemanticEventCategory::Inventory,
        summary: "An equip request was rejected.",
        required_payload_keys: &[
            "actor_entity_id",
            "item_entity_id",
            "inventory_state",
            "reason",
        ],
        binding_targets: TIMELINE,
        persistent: false,
        replay_relevant: true,
    },
    SemanticEventDefinition {
        name: INVENTORY_DROPPED,
        domain: "inventory",
        category: SemanticEventCategory::Inventory,
        summary: "An actor dropped an inventory item into the world.",
        required_payload_keys: &["actor_entity_id", "item_entity_id", "inventory_state"],
        binding_targets: AV_TIMELINE,
        persistent: true,
        replay_relevant: true,
    },
    SemanticEventDefinition {
        name: INVENTORY_DROP_REJECTED,
        domain: "inventory",
        category: SemanticEventCategory::Inventory,
        summary: "A drop request was rejected.",
        required_payload_keys: &[
            "actor_entity_id",
            "item_entity_id",
            "inventory_state",
            "reason",
        ],
        binding_targets: TIMELINE,
        persistent: false,
        replay_relevant: true,
    },
    SemanticEventDefinition {
        name: COMBAT_ATTACK_STARTED,
        domain: "combat",
        category: SemanticEventCategory::Combat,
        summary: "An actor started a generic attack action.",
        required_payload_keys: &["actor_entity_id"],
        binding_targets: AV_TIMELINE,
        persistent: false,
        replay_relevant: true,
    },
    SemanticEventDefinition {
        name: COMBAT_HIT_CONFIRMED,
        domain: "combat",
        category: SemanticEventCategory::Combat,
        summary: "A hit was confirmed by combat rules.",
        required_payload_keys: &["source_entity_id", "target_entity_id"],
        binding_targets: AV_TIMELINE,
        persistent: false,
        replay_relevant: true,
    },
    SemanticEventDefinition {
        name: COMBAT_BLOCKED,
        domain: "combat",
        category: SemanticEventCategory::Combat,
        summary: "A hit was blocked.",
        required_payload_keys: &["source_entity_id", "target_entity_id"],
        binding_targets: AV_TIMELINE,
        persistent: false,
        replay_relevant: true,
    },
    SemanticEventDefinition {
        name: COMBAT_PARRIED,
        domain: "combat",
        category: SemanticEventCategory::Combat,
        summary: "A hit was parried or countered by rules.",
        required_payload_keys: &["source_entity_id", "target_entity_id"],
        binding_targets: AV_TIMELINE,
        persistent: false,
        replay_relevant: true,
    },
    SemanticEventDefinition {
        name: COMBAT_KILLED,
        domain: "combat",
        category: SemanticEventCategory::Combat,
        summary: "An entity was defeated by combat rules.",
        required_payload_keys: &["source_entity_id", "target_entity_id"],
        binding_targets: AV_TIMELINE,
        persistent: true,
        replay_relevant: true,
    },
    SemanticEventDefinition {
        name: ANIMATION_COMMAND_REQUESTED,
        domain: "animation",
        category: SemanticEventCategory::Animation,
        summary: "Runtime requested semantic animation playback.",
        required_payload_keys: &["entity_id"],
        binding_targets: ANIMATION_BINDING,
        persistent: false,
        replay_relevant: true,
    },
    SemanticEventDefinition {
        name: ANIMATION_PLAYBACK_STARTED,
        domain: "animation",
        category: SemanticEventCategory::Animation,
        summary: "Engine reported animation playback started.",
        required_payload_keys: &["entity_id"],
        binding_targets: ANIMATION_BINDING,
        persistent: false,
        replay_relevant: false,
    },
    SemanticEventDefinition {
        name: ANIMATION_PLAYBACK_COMPLETED,
        domain: "animation",
        category: SemanticEventCategory::Animation,
        summary: "Engine reported animation playback completed.",
        required_payload_keys: &["entity_id"],
        binding_targets: ANIMATION_BINDING,
        persistent: false,
        replay_relevant: false,
    },
    SemanticEventDefinition {
        name: AUDIO_PLAYBACK_REQUESTED,
        domain: "audio",
        category: SemanticEventCategory::Audio,
        summary: "Runtime requested semantic audio playback.",
        required_payload_keys: &["entity_id"],
        binding_targets: AUDIO_BINDING,
        persistent: false,
        replay_relevant: true,
    },
    SemanticEventDefinition {
        name: AUDIO_PLAYBACK_COMPLETED,
        domain: "audio",
        category: SemanticEventCategory::Audio,
        summary: "Engine reported audio playback completed.",
        required_payload_keys: &["entity_id"],
        binding_targets: AUDIO_BINDING,
        persistent: false,
        replay_relevant: false,
    },
    SemanticEventDefinition {
        name: VFX_PLAYBACK_REQUESTED,
        domain: "vfx",
        category: SemanticEventCategory::Vfx,
        summary: "Runtime requested semantic VFX playback.",
        required_payload_keys: &["entity_id"],
        binding_targets: VFX_BINDING,
        persistent: false,
        replay_relevant: true,
    },
    SemanticEventDefinition {
        name: VFX_PLAYBACK_COMPLETED,
        domain: "vfx",
        category: SemanticEventCategory::Vfx,
        summary: "Engine reported VFX playback completed.",
        required_payload_keys: &["entity_id"],
        binding_targets: VFX_BINDING,
        persistent: false,
        replay_relevant: false,
    },
];

pub fn domain_event(name: &str) -> EventType {
    EventType::Domain(name.to_string())
}

pub fn get_semantic_event(name: &str) -> Option<&'static SemanticEventDefinition> {
    BUILTIN_SEMANTIC_EVENTS
        .iter()
        .find(|definition| definition.name == name)
}

pub fn semantic_events_for_domain(domain: &str) -> Vec<&'static SemanticEventDefinition> {
    BUILTIN_SEMANTIC_EVENTS
        .iter()
        .filter(|definition| definition.domain == domain)
        .collect()
}

pub fn semantic_events_for_binding_target(
    target: SemanticBindingTarget,
) -> Vec<&'static SemanticEventDefinition> {
    BUILTIN_SEMANTIC_EVENTS
        .iter()
        .filter(|definition| definition.supports_binding_target(target))
        .collect()
}

pub fn event_type_semantic_name(event_type: &EventType) -> Option<&str> {
    match event_type {
        EventType::Domain(name) => Some(name.as_str()),
        _ => None,
    }
}

pub fn is_registered_semantic_event(name: &str) -> bool {
    get_semantic_event(name).is_some()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeSet;

    #[test]
    fn registry_names_are_unique_and_match_domains() {
        let mut names = BTreeSet::new();
        for definition in BUILTIN_SEMANTIC_EVENTS {
            assert!(
                names.insert(definition.name),
                "duplicate {}",
                definition.name
            );
            assert!(
                definition
                    .name
                    .starts_with(&format!("{}.", definition.domain)),
                "{} must use its domain prefix",
                definition.name
            );
        }
    }

    #[test]
    fn movement_interaction_and_inventory_events_are_registered() {
        assert!(is_registered_semantic_event(MOVEMENT_JUMP_STARTED));
        assert!(is_registered_semantic_event(MOVEMENT_LANDED));
        assert!(is_registered_semantic_event(INTERACTION_ACCEPTED));
        assert!(is_registered_semantic_event(INVENTORY_PICKUP_ACCEPTED));
        assert!(is_registered_semantic_event(INVENTORY_EQUIPPED));
        assert!(is_registered_semantic_event(INVENTORY_DROPPED));
    }

    #[test]
    fn registry_exposes_binding_targets() {
        let animation_events = semantic_events_for_binding_target(SemanticBindingTarget::Animation);
        assert!(animation_events
            .iter()
            .any(|definition| definition.name == INTERACTION_ACCEPTED));
        assert!(animation_events
            .iter()
            .any(|definition| definition.name == ANIMATION_COMMAND_REQUESTED));
    }

    #[test]
    fn domain_event_helper_uses_event_type_domain() {
        let event_type = domain_event(INVENTORY_PICKUP_ACCEPTED);
        assert_eq!(
            event_type_semantic_name(&event_type),
            Some(INVENTORY_PICKUP_ACCEPTED)
        );
    }
}
