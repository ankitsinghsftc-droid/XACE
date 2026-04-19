//! # Actor Definition
//!
//! Defines an entity template in the CGS. An ActorDefinition is the
//! blueprint from which live entities are instantiated at runtime.
//! Every entity that can exist in a game mode is defined here first.
//!
//! ## Actor vs Entity
//! ActorDefinition = the schema blueprint (lives in CGS, immutable at runtime)
//! Entity = the live instance (lives in EntityStore, mutable via Mutation Gate)
//!
//! When the Spawner system or Game Genesis Engine creates an entity,
//! it reads the ActorDefinition and instantiates it into the EntityStore
//! with the declared component defaults. The entity then lives independently
//! of its blueprint — mutations to the entity do not affect the blueprint.
//!
//! ## Control Type
//! Every actor declares its control type — Human, AiProxy, or NetworkRemote.
//! This drives how COMP_INPUT_V1 is configured on instantiation and
//! which systems process this entity's input each tick.
//!
//! ## Global Invariant I3
//! Actor definitions live in the CGS only.
//! The runtime never creates actor definitions — only entity instances.

use serde::{Deserialize, Serialize};
use crate::ucl::input_component::ControlType;

// ── Actor Type ────────────────────────────────────────────────────────────────

/// The high-level role of this actor in the game.
///
/// Used by the Schema Factory to apply sensible component defaults
/// and by the Design Mentor to give contextually appropriate suggestions.
/// Does not constrain which components can be attached — it is a hint,
/// not a hard rule.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum ActorType {
    /// A player-controlled character. Gets COMP_INPUT_V1 with Human control.
    PlayerCharacter,
    /// An AI-controlled friendly or neutral character.
    NpcCharacter,
    /// An AI-controlled hostile character.
    Enemy,
    /// A static or dynamic interactable object in the world.
    Prop,
    /// A trigger zone or logical boundary with no visual.
    Zone,
    /// A short-lived gameplay object — projectile, effect, pickup.
    Projectile,
    /// A camera entity driven by the camera system.
    Camera,
    /// An entity that spawns other entities at runtime.
    Spawner,
    /// A global game controller entity — one per mode, manages game state.
    Controller,
    /// A UI element anchored in world space.
    WorldUi,
    /// Developer-defined actor type not covered above.
    Custom(String),
}

impl Default for ActorType {
    fn default() -> Self {
        ActorType::Prop
    }
}

impl std::fmt::Display for ActorType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ActorType::PlayerCharacter => write!(f, "PlayerCharacter"),
            ActorType::NpcCharacter => write!(f, "NpcCharacter"),
            ActorType::Enemy => write!(f, "Enemy"),
            ActorType::Prop => write!(f, "Prop"),
            ActorType::Zone => write!(f, "Zone"),
            ActorType::Projectile => write!(f, "Projectile"),
            ActorType::Camera => write!(f, "Camera"),
            ActorType::Spawner => write!(f, "Spawner"),
            ActorType::Controller => write!(f, "Controller"),
            ActorType::WorldUi => write!(f, "WorldUi"),
            ActorType::Custom(name) => write!(f, "Custom({})", name),
        }
    }
}

// ── Component Default ─────────────────────────────────────────────────────────

/// A default component value declared for an actor in the CGS.
///
/// When the Spawner system instantiates an actor into a live entity,
/// it reads these defaults and writes them to the ComponentTableStore
/// via the Mutation Gate. The entity starts with exactly these values.
///
/// ## Serialization
/// Component data is stored as a JSON string. The Schema Factory
/// validates the JSON against the component's UCL/DCL definition
/// before allowing the CGS commit. Invalid component data blocks commit.
///
/// ## Type ID
/// component_type_id maps to a registered component in the
/// CompositeComponentRegistry (UCL + DCL + GCL). Unknown type IDs
/// block commit — validated by Schema Factory (Phase 11).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ComponentDefault {
    /// The component type ID from the CompositeComponentRegistry.
    /// Must be a registered UCL, DCL, or GCL component type ID.
    pub component_type_id: u32,

    /// The canonical component type name for human readability.
    /// Examples: "COMP_TRANSFORM_V1", "COMP_HEALTH_V1"
    pub component_type_name: String,

    /// Default field values serialized as JSON.
    /// Validated against the component schema by Schema Factory.
    /// Empty string means "use component struct defaults entirely."
    pub default_values_json: String,
}

impl ComponentDefault {
    /// Creates a component default using the component's built-in defaults.
    /// No field overrides — entity starts with the component's zero state.
    pub fn from_defaults(
        component_type_id: u32,
        component_type_name: impl Into<String>,
    ) -> Self {
        Self {
            component_type_id,
            component_type_name: component_type_name.into(),
            default_values_json: String::new(),
        }
    }

    /// Creates a component default with specific field overrides.
    /// `json` must be valid JSON matching the component's field schema.
    pub fn with_values(
        component_type_id: u32,
        component_type_name: impl Into<String>,
        json: impl Into<String>,
    ) -> Self {
        Self {
            component_type_id,
            component_type_name: component_type_name.into(),
            default_values_json: json.into(),
        }
    }

    /// Returns true if this default has explicit field overrides.
    pub fn has_overrides(&self) -> bool {
        !self.default_values_json.is_empty()
    }
}

// ── Ability Reference ─────────────────────────────────────────────────────────

/// A reference to an ability available to this actor.
///
/// Abilities are high-level game actions — jump, attack, dash, cast spell.
/// Each ability maps to a system that implements its logic.
/// The ability system reads these references to know which actors
/// can perform which actions.
///
/// Full ability definitions live in dcl/rpg/ability_component.py.
/// This is a lightweight reference in the schema layer.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AbilityReference {
    /// Unique ID of this ability within the CGS.
    pub ability_id: String,

    /// Human-readable name shown in builder UI and Design Mentor.
    pub display_name: String,

    /// Whether this ability is enabled by default on instantiation.
    pub enabled_by_default: bool,
}

impl AbilityReference {
    pub fn new(
        ability_id: impl Into<String>,
        display_name: impl Into<String>,
    ) -> Self {
        Self {
            ability_id: ability_id.into(),
            display_name: display_name.into(),
            enabled_by_default: true,
        }
    }
}

// ── Actor Definition ──────────────────────────────────────────────────────────

/// A complete entity blueprint defined in the CGS.
///
/// ActorDefinitions are the templates from which all live entities
/// are created. They live in the CGS (immutable at runtime) and are
/// compiled into EntityBlueprints by the Schema Factory (Phase 11).
///
/// ## Instantiation Flow
/// CGS ActorDefinition
///   → Schema Factory compiles to EntityBlueprint
///   → Spawner system reads blueprint at runtime
///   → EntityStore.create_entity() called
///   → ComponentTableStore populated with component defaults
///   → Entity is live and visible to all systems
///
/// ## Stats
/// `stats` is a free-form key-value store for game-specific numeric values
/// that don't belong to a specific component. Examples: base_damage,
/// move_speed_modifier, experience_reward. Systems can read these via
/// the actor definition lookup without querying multiple components.
///
/// ## Prefab ID
/// `prefab_id` links this actor to an engine-side prefab for visual setup.
/// The engine adapter uses this to spawn the correct visual representation.
/// Empty string means no prefab — entity is built entirely from components.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ActorDefinition {
    /// Unique identifier for this actor within its GameMode.
    /// Used by spawner systems and DSL paths to reference this actor.
    /// Examples: "actor_player", "actor_zombie", "actor_health_pickup"
    pub id: String,

    /// The high-level role of this actor.
    pub actor_type: ActorType,

    /// Component defaults applied when this actor is instantiated.
    /// Sorted by component_type_id for deterministic processing (D11).
    pub components: Vec<ComponentDefault>,

    /// Game-specific numeric stats for this actor.
    /// Free-form key-value — validated by GDE, not by runtime.
    /// Examples: {"max_health": 100.0, "move_speed": 5.0}
    pub stats: std::collections::BTreeMap<String, f64>,

    /// Abilities available to entities of this actor type.
    pub abilities: Vec<AbilityReference>,

    /// Who controls entities instantiated from this actor.
    /// Drives COMP_INPUT_V1 configuration on instantiation.
    pub control_type: ControlType,

    /// Optional engine prefab ID for visual setup.
    /// Empty string = no prefab, entity is component-driven only.
    pub prefab_id: String,

    /// Human-readable description of this actor.
    /// Shown in builder UI and used by Design Mentor suggestions.
    pub description: String,
}

impl ActorDefinition {
    /// Creates a minimal actor definition with no components or abilities.
    pub fn new(
        id: impl Into<String>,
        actor_type: ActorType,
        control_type: ControlType,
    ) -> Self {
        Self {
            id: id.into(),
            actor_type,
            components: Vec::new(),
            stats: std::collections::BTreeMap::new(),
            abilities: Vec::new(),
            control_type,
            prefab_id: String::new(),
            description: String::new(),
        }
    }

    /// Creates a player character actor definition.
    /// Human-controlled, PlayerCharacter type, no components yet.
    pub fn player(id: impl Into<String>) -> Self {
        Self::new(id, ActorType::PlayerCharacter, ControlType::Human)
    }

    /// Creates an AI enemy actor definition.
    pub fn enemy(id: impl Into<String>) -> Self {
        Self::new(id, ActorType::Enemy, ControlType::AiProxy)
    }

    /// Creates a prop actor definition (static object, no control).
    pub fn prop(id: impl Into<String>) -> Self {
        Self::new(id, ActorType::Prop, ControlType::AiProxy)
    }

    /// Returns true if this actor has a component with the given type ID.
    pub fn has_component(&self, type_id: u32) -> bool {
        self.components.iter().any(|c| c.component_type_id == type_id)
    }

    /// Returns the component default for the given type ID, if present.
    pub fn get_component(&self, type_id: u32) -> Option<&ComponentDefault> {
        self.components.iter().find(|c| c.component_type_id == type_id)
    }

    /// Adds a component default, maintaining sorted order by type_id (D11).
    /// No-op if a component with the same type_id already exists.
    pub fn add_component(&mut self, component: ComponentDefault) {
        if self.has_component(component.component_type_id) {
            return;
        }
        let pos = self.components
            .partition_point(|c| c.component_type_id < component.component_type_id);
        self.components.insert(pos, component);
    }

    /// Returns a stat value by key, if it exists.
    pub fn get_stat(&self, key: &str) -> Option<f64> {
        self.stats.get(key).copied()
    }

    /// Sets a stat value. Overwrites if key already exists.
    pub fn set_stat(&mut self, key: impl Into<String>, value: f64) {
        self.stats.insert(key.into(), value);
    }

    /// Returns true if this actor has an ability with the given ID.
    pub fn has_ability(&self, ability_id: &str) -> bool {
        self.abilities.iter().any(|a| a.ability_id == ability_id)
    }

    /// Returns true if this actor is player-controlled.
    pub fn is_player_controlled(&self) -> bool {
        matches!(self.control_type, ControlType::Human)
    }

    /// Returns true if this actor is AI-controlled.
    pub fn is_ai_controlled(&self) -> bool {
        matches!(self.control_type, ControlType::AiProxy)
    }

    /// Validates this actor for internal consistency.
    ///
    /// Checks:
    /// - ID is not empty
    /// - No duplicate component type IDs
    /// - No duplicate ability IDs
    ///
    /// Full validation including component schema checks is
    /// performed by the Schema Factory (Phase 11).
    pub fn validate(&self) -> Result<(), String> {
        if self.id.is_empty() {
            return Err("ActorDefinition ID must not be empty".into());
        }

        // Check duplicate component type IDs
        let mut seen = std::collections::HashSet::new();
        for comp in &self.components {
            if !seen.insert(comp.component_type_id) {
                return Err(format!(
                    "Duplicate component type ID {} in actor {}",
                    comp.component_type_id, self.id
                ));
            }
        }

        // Check duplicate ability IDs
        let mut seen_abilities = std::collections::HashSet::new();
        for ability in &self.abilities {
            if !seen_abilities.insert(&ability.ability_id) {
                return Err(format!(
                    "Duplicate ability ID {} in actor {}",
                    ability.ability_id, self.id
                ));
            }
        }

        Ok(())
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn player_actor_is_human_controlled() {
        let actor = ActorDefinition::player("actor_player");
        assert!(actor.is_player_controlled());
        assert!(!actor.is_ai_controlled());
        assert_eq!(actor.actor_type, ActorType::PlayerCharacter);
    }

    #[test]
    fn enemy_actor_is_ai_controlled() {
        let actor = ActorDefinition::enemy("actor_zombie");
        assert!(actor.is_ai_controlled());
        assert_eq!(actor.actor_type, ActorType::Enemy);
    }

    #[test]
    fn new_actor_has_no_components() {
        let actor = ActorDefinition::player("actor_player");
        assert!(actor.components.is_empty());
    }

    #[test]
    fn add_component_maintains_sorted_order() {
        let mut actor = ActorDefinition::player("actor_player");
        actor.add_component(ComponentDefault::from_defaults(5, "COMP_VELOCITY_V1"));
        actor.add_component(ComponentDefault::from_defaults(1, "COMP_TRANSFORM_V1"));
        actor.add_component(ComponentDefault::from_defaults(3, "COMP_RENDER_V1"));
        assert_eq!(actor.components[0].component_type_id, 1);
        assert_eq!(actor.components[1].component_type_id, 3);
        assert_eq!(actor.components[2].component_type_id, 5);
    }

    #[test]
    fn add_component_no_duplicates() {
        let mut actor = ActorDefinition::player("actor_player");
        actor.add_component(ComponentDefault::from_defaults(1, "COMP_TRANSFORM_V1"));
        actor.add_component(ComponentDefault::from_defaults(1, "COMP_TRANSFORM_V1"));
        assert_eq!(actor.components.len(), 1);
    }

    #[test]
    fn has_component_works() {
        let mut actor = ActorDefinition::player("actor_player");
        actor.add_component(ComponentDefault::from_defaults(1, "COMP_TRANSFORM_V1"));
        assert!(actor.has_component(1));
        assert!(!actor.has_component(99));
    }

    #[test]
    fn get_component_returns_correct() {
        let mut actor = ActorDefinition::player("actor_player");
        actor.add_component(ComponentDefault::from_defaults(2, "COMP_IDENTITY_V1"));
        let comp = actor.get_component(2);
        assert!(comp.is_some());
        assert_eq!(comp.unwrap().component_type_name, "COMP_IDENTITY_V1");
    }

    #[test]
    fn stats_stored_and_retrieved() {
        let mut actor = ActorDefinition::enemy("actor_zombie");
        actor.set_stat("max_health", 100.0);
        actor.set_stat("move_speed", 3.5);
        assert_eq!(actor.get_stat("max_health"), Some(100.0));
        assert_eq!(actor.get_stat("move_speed"), Some(3.5));
        assert_eq!(actor.get_stat("missing"), None);
    }

    #[test]
    fn validate_passes_for_valid_actor() {
        let actor = ActorDefinition::player("actor_player");
        assert!(actor.validate().is_ok());
    }

    #[test]
    fn validate_fails_for_empty_id() {
        let actor = ActorDefinition::new("", ActorType::Prop, ControlType::AiProxy);
        assert!(actor.validate().is_err());
    }

    #[test]
    fn validate_detects_duplicate_components() {
        let mut actor = ActorDefinition::player("actor_player");
        actor.components.push(
            ComponentDefault::from_defaults(1, "COMP_TRANSFORM_V1")
        );
        actor.components.push(
            ComponentDefault::from_defaults(1, "COMP_TRANSFORM_V1")
        );
        assert!(actor.validate().is_err());
    }

    #[test]
    fn component_default_with_overrides() {
        let comp = ComponentDefault::with_values(
            1,
            "COMP_TRANSFORM_V1",
            r#"{"position": {"x": 0, "y": 5, "z": 0}}"#,
        );
        assert!(comp.has_overrides());
    }

    #[test]
    fn component_default_without_overrides() {
        let comp = ComponentDefault::from_defaults(1, "COMP_TRANSFORM_V1");
        assert!(!comp.has_overrides());
    }

    #[test]
    fn actor_type_display() {
        assert_eq!(ActorType::PlayerCharacter.to_string(), "PlayerCharacter");
        assert_eq!(ActorType::Enemy.to_string(), "Enemy");
        assert_eq!(
            ActorType::Custom("BossMinion".into()).to_string(),
            "Custom(BossMinion)"
        );
    }

    #[test]
    fn ability_reference_enabled_by_default() {
        let ability = AbilityReference::new("ability_jump", "Jump");
        assert!(ability.enabled_by_default);
    }

    #[test]
    fn has_ability_works() {
        let mut actor = ActorDefinition::player("actor_player");
        actor.abilities.push(AbilityReference::new("ability_jump", "Jump"));
        assert!(actor.has_ability("ability_jump"));
        assert!(!actor.has_ability("ability_dash"));
    }
}
