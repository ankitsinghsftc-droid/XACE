//! # Game Mode
//!
//! A self-contained game mode definition. Each mode has its own world,
//! actors, systems, rules, and UI configuration. Multiple modes can
//! exist in one game — arena, survival, main menu, tutorial, etc.
//!
//! ## What a Mode Is
//! A mode is a complete playable configuration of a game. Switching
//! modes recompiles the ExecutionPlan via the SGC. The active mode
//! is tracked in COMP_GAMESTATE_V1.active_mode_id.
//!
//! ## Mode Isolation
//! Systems declared in one mode do not run in another mode.
//! Global systems (declared in CanonicalGameSchema) run in all modes.
//! This isolation is enforced by the SGC during ExecutionPlan compilation.
//!
//! ## Global Invariant I3
//! Mode definitions live in the CGS only.
//! The runtime never defines or modifies modes directly.

use serde::{Deserialize, Serialize};
use crate::schema::world_definition::WorldDefinition;
use crate::schema::actor_definition::ActorDefinition;
use crate::schema::system_definition::SystemDefinition;
use crate::schema::rule_definition::RuleDefinition;

// ── UI Configuration ──────────────────────────────────────────────────────────

/// UI layout configuration for a game mode.
///
/// Declares which UI elements are active during this mode.
/// UI element details live in DCL ui/ components on UI entities.
/// This struct is a lightweight reference layer — it names the
/// UI configurations without duplicating their full definitions.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ModeUiConfig {
    /// IDs of HUD elements active during this mode.
    /// Each ID maps to a UI entity defined in actors[].
    /// Example: ["hud_health_bar", "hud_score_display", "hud_minimap"]
    pub active_hud_elements: Vec<String>,

    /// ID of the pause menu UI configuration for this mode.
    /// Empty string means no pause menu (main menu mode, etc.)
    pub pause_menu_id: String,

    /// Whether the in-game XACE console overlay is enabled in this mode.
    /// The console allows prompt input during live gameplay (Phase 14).
    pub console_enabled: bool,
}

impl ModeUiConfig {
    /// Creates a minimal UI config with no HUD elements.
    pub fn empty() -> Self {
        Self {
            active_hud_elements: Vec::new(),
            pause_menu_id: String::new(),
            console_enabled: false,
        }
    }

    /// Creates a standard gameplay UI config with console enabled.
    pub fn gameplay(pause_menu_id: impl Into<String>) -> Self {
        Self {
            active_hud_elements: Vec::new(),
            pause_menu_id: pause_menu_id.into(),
            console_enabled: true,
        }
    }
}

impl Default for ModeUiConfig {
    fn default() -> Self {
        Self::empty()
    }
}

// ── Game Mode ─────────────────────────────────────────────────────────────────

/// A complete, self-contained game mode definition.
///
/// Every playable configuration of a game is a GameMode. A simple game
/// might have one mode. A complex game might have many:
/// - mode_main_menu: lobby, character select
/// - mode_arena: active combat gameplay
/// - mode_survival: wave-based gameplay
/// - mode_tutorial: guided first session
///
/// ## Compilation
/// When the active mode changes, the Schema Factory recompiles the
/// CompiledSchemaPackage and the SGC produces a new ExecutionPlan.
/// The runtime applies the new plan on the next tick boundary.
///
/// ## Actor Definitions
/// Actors are entity templates — they define what components an entity
/// starts with. At runtime, the Spawner system or Genesis Engine
/// instantiates actors into live entities using these definitions.
///
/// ## Systems and Rules
/// Systems declared here run only when this mode is active.
/// Rules declared here are evaluated only in this mode's context.
/// Global systems (in CanonicalGameSchema) always run regardless.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct GameMode {
    /// Unique identifier for this mode within the CGS.
    /// Used by COMP_GAMESTATE_V1.active_mode_id to track active mode.
    /// Example: "mode_arena", "mode_survival", "mode_main_menu"
    pub id: String,

    /// Human-readable name for this mode.
    /// Shown in the builder UI and Design Mentor suggestions.
    pub description: String,

    /// Whether this is the default mode loaded at game start.
    /// Exactly one mode in the CGS must have is_default = true.
    /// Validated by CanonicalGameSchema::is_structurally_valid().
    pub is_default: bool,

    /// The world configuration for this mode.
    /// Defines map type, environment, physics profile, gravity, etc.
    pub world: WorldDefinition,

    /// Entity templates available in this mode.
    /// Each ActorDefinition is a blueprint for spawning entities.
    /// Sorted by ID for deterministic processing (D11).
    pub actors: Vec<ActorDefinition>,

    /// Systems that run only when this mode is active.
    /// Combined with global_systems from CGS by the SGC.
    /// Sorted by ID for deterministic graph construction (D11).
    pub systems: Vec<SystemDefinition>,

    /// Game rules evaluated in this mode.
    /// Rules define condition→effect logic compiled by the GDE.
    /// Sorted by priority descending, then ID ascending (D11).
    pub rules: Vec<RuleDefinition>,

    /// UI configuration for this mode.
    pub ui: ModeUiConfig,
}

impl GameMode {
    /// Creates a new empty game mode with no actors, systems, or rules.
    ///
    /// Used by the Game Genesis Engine and GDE when creating new modes.
    /// World defaults to a standard environment. UI defaults to empty.
    pub fn new(
        id: impl Into<String>,
        description: impl Into<String>,
        is_default: bool,
    ) -> Self {
        Self {
            id: id.into(),
            description: description.into(),
            is_default,
            world: WorldDefinition::default(),
            actors: Vec::new(),
            systems: Vec::new(),
            rules: Vec::new(),
            ui: ModeUiConfig::empty(),
        }
    }

    /// Returns the actor definition with the given ID, if it exists.
    pub fn get_actor(&self, actor_id: &str) -> Option<&ActorDefinition> {
        self.actors.iter().find(|a| a.id == actor_id)
    }

    /// Returns true if an actor with the given ID exists in this mode.
    pub fn has_actor(&self, actor_id: &str) -> bool {
        self.actors.iter().any(|a| a.id == actor_id)
    }

    /// Returns the system definition with the given ID, if it exists.
    pub fn get_system(&self, system_id: &str) -> Option<&SystemDefinition> {
        self.systems.iter().find(|s| s.id == system_id)
    }

    /// Returns true if a system with the given ID exists in this mode.
    pub fn has_system(&self, system_id: &str) -> bool {
        self.systems.iter().any(|s| s.id == system_id)
    }

    /// Returns the rule definition with the given ID, if it exists.
    pub fn get_rule(&self, rule_id: &str) -> Option<&RuleDefinition> {
        self.rules.iter().find(|r| r.id == rule_id)
    }

    /// Returns true if a rule with the given ID exists in this mode.
    pub fn has_rule(&self, rule_id: &str) -> bool {
        self.rules.iter().any(|r| r.id == rule_id)
    }

    /// Returns true if this mode has no actors, systems, or rules defined.
    /// An empty mode is valid structurally but not playable.
    pub fn is_empty(&self) -> bool {
        self.actors.is_empty()
            && self.systems.is_empty()
            && self.rules.is_empty()
    }

    /// Returns all active rule IDs sorted by priority descending.
    /// Used by the GDE when evaluating rule conflicts.
    pub fn active_rule_ids(&self) -> Vec<&str> {
        let mut rules: Vec<&RuleDefinition> = self.rules
            .iter()
            .filter(|r| r.is_active)
            .collect();
        rules.sort_by(|a, b| {
            b.priority.cmp(&a.priority)
                .then(a.id.cmp(&b.id))
        });
        rules.iter().map(|r| r.id.as_str()).collect()
    }

    /// Validates this mode for internal consistency.
    ///
    /// Checks:
    /// - ID is not empty
    /// - No duplicate actor IDs
    /// - No duplicate system IDs
    /// - No duplicate rule IDs
    ///
    /// Full validation is performed by Schema Factory (Phase 11).
    pub fn validate(&self) -> Result<(), String> {
        if self.id.is_empty() {
            return Err("GameMode ID must not be empty".into());
        }

        // Check duplicate actor IDs
        let mut seen = std::collections::HashSet::new();
        for actor in &self.actors {
            if !seen.insert(&actor.id) {
                return Err(format!(
                    "Duplicate actor ID in mode {}: {}",
                    self.id, actor.id
                ));
            }
        }

        // Check duplicate system IDs
        seen.clear();
        for system in &self.systems {
            if !seen.insert(&system.id) {
                return Err(format!(
                    "Duplicate system ID in mode {}: {}",
                    self.id, system.id
                ));
            }
        }

        // Check duplicate rule IDs
        seen.clear();
        for rule in &self.rules {
            if !seen.insert(&rule.id) {
                return Err(format!(
                    "Duplicate rule ID in mode {}: {}",
                    self.id, rule.id
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

    fn test_mode() -> GameMode {
        GameMode::new("mode_arena", "Arena Mode", true)
    }

    #[test]
    fn new_mode_is_empty() {
        let mode = test_mode();
        assert!(mode.is_empty());
        assert!(mode.actors.is_empty());
        assert!(mode.systems.is_empty());
        assert!(mode.rules.is_empty());
    }

    #[test]
    fn mode_id_and_default_set_correctly() {
        let mode = test_mode();
        assert_eq!(mode.id, "mode_arena");
        assert!(mode.is_default);
    }

    #[test]
    fn non_default_mode() {
        let mode = GameMode::new("mode_survival", "Survival", false);
        assert!(!mode.is_default);
    }

    #[test]
    fn get_actor_returns_none_when_empty() {
        let mode = test_mode();
        assert!(mode.get_actor("actor_player").is_none());
    }

    #[test]
    fn get_system_returns_none_when_empty() {
        let mode = test_mode();
        assert!(mode.get_system("sys_input").is_none());
    }

    #[test]
    fn validate_passes_for_empty_mode() {
        let mode = test_mode();
        assert!(mode.validate().is_ok());
    }

    #[test]
    fn validate_fails_for_empty_id() {
        let mode = GameMode::new("", "No ID", true);
        assert!(mode.validate().is_err());
    }

    #[test]
    fn active_rule_ids_empty_when_no_rules() {
        let mode = test_mode();
        assert!(mode.active_rule_ids().is_empty());
    }

    #[test]
    fn ui_config_empty_by_default() {
        let mode = test_mode();
        assert!(mode.ui.active_hud_elements.is_empty());
        assert!(mode.ui.pause_menu_id.is_empty());
    }

    #[test]
    fn gameplay_ui_has_console_enabled() {
        let ui = ModeUiConfig::gameplay("pause_menu_main");
        assert!(ui.console_enabled);
        assert_eq!(ui.pause_menu_id, "pause_menu_main");
    }
}