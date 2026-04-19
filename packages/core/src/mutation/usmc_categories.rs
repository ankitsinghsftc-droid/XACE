//! # USMC Categories
//!
//! The Universal Schema Mutation Categories. Every mutation submitted
//! to the CGS through the PIL → GDE pipeline is classified into one
//! of these categories before processing.
//!
//! ## What USMC Is
//! USMC is the classification system for design intent. When a user
//! says "add a health system to my player", the GDE classifies that
//! as a Modify intent. When they say "create a new enemy type", that
//! is a Create intent. The category drives which validation rules,
//! which risk guards, and which Design Mentor suggestions apply.
//!
//! ## Why Classification Matters
//! Different mutation categories carry different risk profiles:
//! - Create: low risk, adds new schema nodes
//! - Remove: high risk, may break dependencies
//! - Constrain: medium risk, affects existing system behavior
//! - ProgressionDefine: complex, touches multiple systems
//!
//! The Safety Scope Guard (Phase 13) uses USMC categories to apply
//! the correct risk threshold before allowing any mutation to commit.
//!
//! ## Determinism
//! USMC classification is deterministic — the same prompt always
//! produces the same category given the same CGS context (D6).
//! The classifier uses heuristics + component vocabulary, not randomness.

use serde::{Deserialize, Serialize};

// ── USMC Category ─────────────────────────────────────────────────────────────

/// The Universal Schema Mutation Category.
///
/// Classifies every design intent into one of eight categories.
/// Assigned by the GDE's usmc_classifier before any mutation processing.
/// Used by the Safety Scope Guard, Design Mentor, and NLTL translation layer.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum UsmcCategory {
    /// Adding something new to the schema that did not exist before.
    ///
    /// Examples:
    /// - "Add a health system to my game"
    /// - "Create a new enemy type called Zombie"
    /// - "Add a dash ability to the player"
    ///
    /// Risk profile: LOW. Creates new schema nodes with no existing dependencies.
    /// Validation: check no ID collision, validate component types exist.
    Create,

    /// Changing properties of something that already exists.
    ///
    /// Examples:
    /// - "Make the player faster"
    /// - "Change the zombie health to 150"
    /// - "Update the win condition score to 500"
    ///
    /// Risk profile: MEDIUM. Modifies existing schema nodes.
    /// Validation: check target exists, validate value types, check invariants.
    Modify,

    /// Deleting something from the schema entirely.
    ///
    /// Examples:
    /// - "Remove the shield system"
    /// - "Delete the tutorial mode"
    /// - "Remove the inventory from the player"
    ///
    /// Risk profile: HIGH. May cascade to break dependent systems or rules.
    /// Validation: full dependency analysis required before commit.
    /// Requires confirmation in COLLABORATIVE and ADVANCED modes.
    Remove,

    /// Adding rules or limits that restrict existing behavior.
    ///
    /// Examples:
    /// - "Players can only jump twice before landing"
    /// - "Enemies cannot enter the safe zone"
    /// - "Score cannot exceed 9999"
    ///
    /// Risk profile: MEDIUM. Adds constraints to existing systems.
    /// Validation: check constraint targets exist, verify no contradiction.
    Constrain,

    /// Combining multiple existing elements into a composite behavior.
    ///
    /// Examples:
    /// - "Make the player character also function as a vehicle"
    /// - "Combine the stealth and combat systems for this enemy"
    /// - "Link the health system to the animation system"
    ///
    /// Risk profile: MEDIUM-HIGH. Creates cross-system dependencies.
    /// Validation: dependency graph analysis, parallel execution safety check.
    Compose,

    /// Defining progression, leveling, or advancement systems.
    ///
    /// Examples:
    /// - "Add experience points and leveling to the player"
    /// - "Create a skill tree with 5 abilities"
    /// - "Define wave progression for the survival mode"
    ///
    /// Risk profile: MEDIUM. Touches stats, abilities, and game state.
    /// Validation: check stats and ability components exist in DCL.
    ProgressionDefine,

    /// Defining the physical world, environment, or level structure.
    ///
    /// Examples:
    /// - "Make the world a foggy indoor dungeon"
    /// - "Add a day/night cycle to the outdoor environment"
    /// - "Change the gravity to low for the moon level"
    ///
    /// Risk profile: LOW-MEDIUM. Modifies WorldDefinition and environment.
    /// Validation: check physics profile compatibility with map type.
    EnvironmentDefine,

    /// Defining how entities interact with each other or the world.
    ///
    /// Examples:
    /// - "Make doors open when the player gets close"
    /// - "Add dialogue when the player talks to the NPC"
    /// - "Create a pickup system for health items"
    ///
    /// Risk profile: MEDIUM. Creates entity-to-entity interaction rules.
    /// Validation: check interaction components exist, validate trigger zones.
    Interaction,
}

impl UsmcCategory {
    /// Returns the risk level for this category (0=low, 3=high).
    /// Used by the Safety Scope Guard to select risk thresholds.
    pub fn risk_level(&self) -> u8 {
        match self {
            UsmcCategory::Create => 1,
            UsmcCategory::Modify => 2,
            UsmcCategory::Remove => 3,
            UsmcCategory::Constrain => 2,
            UsmcCategory::Compose => 2,
            UsmcCategory::ProgressionDefine => 2,
            UsmcCategory::EnvironmentDefine => 1,
            UsmcCategory::Interaction => 2,
        }
    }

    /// Returns true if this category requires dependency analysis
    /// before the mutation can be committed.
    pub fn requires_dependency_analysis(&self) -> bool {
        matches!(
            self,
            UsmcCategory::Remove | UsmcCategory::Compose
        )
    }

    /// Returns true if this category may require user confirmation
    /// before committing in non-FULLY_ASSISTED mode.
    pub fn may_require_confirmation(&self) -> bool {
        matches!(
            self,
            UsmcCategory::Remove | UsmcCategory::Compose
        )
    }

    /// Returns a plain-English label for this category.
    /// Used by the NLTL translation layer — zero technical vocabulary.
    pub fn plain_english_label(&self) -> &'static str {
        match self {
            UsmcCategory::Create => "Adding something new",
            UsmcCategory::Modify => "Changing something existing",
            UsmcCategory::Remove => "Removing something",
            UsmcCategory::Constrain => "Adding a rule or limit",
            UsmcCategory::Compose => "Combining behaviors",
            UsmcCategory::ProgressionDefine => "Defining progression",
            UsmcCategory::EnvironmentDefine => "Defining the world",
            UsmcCategory::Interaction => "Defining interactions",
        }
    }

    /// Returns all USMC categories as a static slice.
    /// Used by the GDE classifier to iterate all possible categories.
    pub fn all() -> &'static [UsmcCategory] {
        &[
            UsmcCategory::Create,
            UsmcCategory::Modify,
            UsmcCategory::Remove,
            UsmcCategory::Constrain,
            UsmcCategory::Compose,
            UsmcCategory::ProgressionDefine,
            UsmcCategory::EnvironmentDefine,
            UsmcCategory::Interaction,
        ]
    }
}

impl std::fmt::Display for UsmcCategory {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            UsmcCategory::Create => write!(f, "Create"),
            UsmcCategory::Modify => write!(f, "Modify"),
            UsmcCategory::Remove => write!(f, "Remove"),
            UsmcCategory::Constrain => write!(f, "Constrain"),
            UsmcCategory::Compose => write!(f, "Compose"),
            UsmcCategory::ProgressionDefine => write!(f, "ProgressionDefine"),
            UsmcCategory::EnvironmentDefine => write!(f, "EnvironmentDefine"),
            UsmcCategory::Interaction => write!(f, "Interaction"),
        }
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn remove_is_highest_risk() {
        assert_eq!(UsmcCategory::Remove.risk_level(), 3);
    }

    #[test]
    fn create_is_low_risk() {
        assert_eq!(UsmcCategory::Create.risk_level(), 1);
    }

    #[test]
    fn remove_requires_dependency_analysis() {
        assert!(UsmcCategory::Remove.requires_dependency_analysis());
    }

    #[test]
    fn create_does_not_require_dependency_analysis() {
        assert!(!UsmcCategory::Create.requires_dependency_analysis());
    }

    #[test]
    fn remove_may_require_confirmation() {
        assert!(UsmcCategory::Remove.may_require_confirmation());
    }

    #[test]
    fn modify_does_not_require_confirmation() {
        assert!(!UsmcCategory::Modify.may_require_confirmation());
    }

    #[test]
    fn all_returns_eight_categories() {
        assert_eq!(UsmcCategory::all().len(), 8);
    }

    #[test]
    fn plain_english_labels_not_empty() {
        for category in UsmcCategory::all() {
            assert!(!category.plain_english_label().is_empty());
        }
    }

    #[test]
    fn display_is_readable() {
        assert_eq!(UsmcCategory::Create.to_string(), "Create");
        assert_eq!(UsmcCategory::ProgressionDefine.to_string(), "ProgressionDefine");
        assert_eq!(UsmcCategory::EnvironmentDefine.to_string(), "EnvironmentDefine");
    }

    #[test]
    fn all_categories_have_risk_levels() {
        for category in UsmcCategory::all() {
            assert!(category.risk_level() > 0);
            assert!(category.risk_level() <= 3);
        }
    }
}
