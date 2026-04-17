//! # Canonical Game Schema (CGS)
//!
//! The single source of truth for every game definition in XACE.
//! Every entity, system, rule, and mode that exists in a game is
//! defined here. Nothing exists in the runtime that is not first
//! defined in the CGS.
//!
//! ## What the CGS Is
//! The CGS is the complete, versioned, validated definition of a game.
//! It is the output of the GDE (Game Definition Engine) and the input
//! to the Schema Factory. It is never modified directly — all changes
//! go through the mutation pipeline:
//! PIL → GDE → CGS mutation → Schema Factory → Runtime
//!
//! ## What the CGS Is Not
//! - Not a runtime state container (that is WorldSnapshot)
//! - Not an execution plan (that is ExecutionPlan from SGC)
//! - Not a save file (that is the Save System, Phase 15)
//!
//! ## Versioning
//! Every mutation increments the version and recomputes cgs_hash.
//! The hash is deterministic — identical schemas always produce
//! identical hashes (D11). The runtime halts if schema version
//! does not match execution plan version (I7, D10).
//!
//! ## Global Invariant I3
//! The CGS is the single source of truth.
//! No runtime system may modify the CGS directly.
//! All modifications go through the mutation pipeline only.

use serde::{Deserialize, Serialize};
use crate::schema::game_mode::GameMode;
use crate::schema::system_definition::SystemDefinition;

// ── CGS Version ───────────────────────────────────────────────────────────────

/// Semantic version for the CGS.
///
/// MAJOR.MINOR.PATCH — incremented by the GDE on every mutation:
/// - PATCH: small value changes (stat tweaks, parameter adjustments)
/// - MINOR: new entities, systems, or rules added
/// - MAJOR: structural changes (mode added/removed, system removed)
///
/// Version is immutable once assigned to a snapshot.
/// The Schema Factory uses version to validate compatibility.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub struct CgsVersion {
    pub major: u32,
    pub minor: u32,
    pub patch: u32,
}

impl CgsVersion {
    /// The initial version for a newly created CGS.
    pub const INITIAL: CgsVersion = CgsVersion {
        major: 0,
        minor: 1,
        patch: 0,
    };

    pub fn new(major: u32, minor: u32, patch: u32) -> Self {
        Self { major, minor, patch }
    }

    /// Increments the patch version. Used for small value changes.
    pub fn increment_patch(&self) -> Self {
        Self {
            major: self.major,
            minor: self.minor,
            patch: self.patch + 1,
        }
    }

    /// Increments the minor version. Used for additive changes.
    pub fn increment_minor(&self) -> Self {
        Self {
            major: self.major,
            minor: self.minor + 1,
            patch: 0,
        }
    }

    /// Increments the major version. Used for structural changes.
    pub fn increment_major(&self) -> Self {
        Self {
            major: self.major + 1,
            minor: 0,
            patch: 0,
        }
    }

    /// Returns true if this version is compatible with another.
    /// Compatible means same major version — minor and patch differences
    /// are handled by the Schema Factory's migration rules.
    pub fn is_compatible_with(&self, other: &CgsVersion) -> bool {
        self.major == other.major
    }
}

impl std::fmt::Display for CgsVersion {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}.{}.{}", self.major, self.minor, self.patch)
    }
}

// ── CGS Metadata ──────────────────────────────────────────────────────────────

/// Metadata about the CGS itself — who created it, when, and what it is.
///
/// Stored at the top level of every CGS. Immutable fields (created_at,
/// game_id) are set once at genesis. Mutable fields (version, cgs_hash,
/// last_modified_at) are updated on every mutation.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct CgsMetadata {
    /// Unique identifier for this game project.
    /// Assigned at genesis. Never changes.
    /// Format: UUID string.
    pub game_id: String,

    /// Human-readable name of this game.
    /// Set at genesis, can be changed via mutation.
    pub game_name: String,

    /// Current version of this CGS.
    /// Incremented by GDE on every successful mutation.
    pub version: CgsVersion,

    /// Deterministic hash of the entire CGS content.
    /// Recomputed after every mutation using stable key ordering (D11).
    /// Used to verify schema integrity and detect corruption.
    /// Also used by the runtime to verify schema/execution plan match (D10).
    pub cgs_hash: String,

    /// ISO 8601 timestamp when this game was first created.
    /// Immutable after genesis.
    pub created_at: String,

    /// ISO 8601 timestamp of the most recent mutation.
    /// Updated by GDE on every successful mutation.
    pub last_modified_at: String,

    /// The XACE platform version this CGS was created with.
    /// Used for forward/backward compatibility checks.
    pub xace_version: String,
}

impl CgsMetadata {
    /// Creates metadata for a brand new game project.
    pub fn new(
        game_id: impl Into<String>,
        game_name: impl Into<String>,
        created_at: impl Into<String>,
        xace_version: impl Into<String>,
    ) -> Self {
        Self {
            game_id: game_id.into(),
            game_name: game_name.into(),
            version: CgsVersion::INITIAL,
            cgs_hash: String::new(), // computed after full CGS is assembled
            created_at: created_at.into(),
            last_modified_at: String::new(),
            xace_version: xace_version.into(),
        }
    }
}

// ── Canonical Game Schema ─────────────────────────────────────────────────────

/// The complete definition of a game in XACE.
///
/// Contains everything needed to compile, simulate, and render a game:
/// - Metadata: version, hash, timestamps
/// - Global systems: systems that run regardless of active mode
/// - Modes: game modes (arena, survival, etc.) each with their own
///   world, actors, systems, rules, and UI
///
/// ## Single Source of Truth (I3)
/// The CGS is authoritative. The runtime derives everything from it.
/// No component, system, or rule exists unless it is defined here first.
///
/// ## Mutation Flow
/// CGS is never edited directly. All changes flow through:
/// PIL → GDE → MutationTransaction → GDE validates → CGS updated →
/// Schema Factory recompiles → SGC produces new ExecutionPlan →
/// Runtime applies new plan on next tick.
///
/// ## Schema Hash
/// cgs_hash in metadata is a deterministic hash of the entire CGS.
/// Same content = same hash, always, on any machine (D11).
/// The SGC embeds this hash in the ExecutionPlan it produces.
/// The runtime verifies hash match before executing (D10, I7).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct CanonicalGameSchema {
    /// Version, identity, and integrity metadata.
    pub metadata: CgsMetadata,

    /// Systems that run every tick regardless of which game mode is active.
    ///
    /// Examples: InputSystem, PhysicsSystem, LifetimeSystem, NetworkSystem.
    /// These are declared here once and included in every ExecutionPlan.
    /// Mode-specific systems are declared inside each GameMode.
    pub global_systems: Vec<SystemDefinition>,

    /// All game modes defined for this game.
    ///
    /// At least one mode must exist. One mode must be marked as default.
    /// The active mode is tracked in COMP_GAMESTATE_V1.active_mode_id.
    /// Mode switching is a schema mutation — it recompiles the ExecutionPlan.
    ///
    /// Examples: "mode_main_menu", "mode_arena", "mode_survival"
    pub modes: Vec<GameMode>,
}

impl CanonicalGameSchema {
    /// Creates a new empty CGS for a game at genesis.
    ///
    /// Starts with no global systems and no modes.
    /// The Game Genesis Engine (Phase 16) populates these from templates.
    /// The GDE populates them from user mutations.
    pub fn new(metadata: CgsMetadata) -> Self {
        Self {
            metadata,
            global_systems: Vec::new(),
            modes: Vec::new(),
        }
    }

    /// Returns the game mode with the given ID, if it exists.
    pub fn get_mode(&self, mode_id: &str) -> Option<&GameMode> {
        self.modes.iter().find(|m| m.id == mode_id)
    }

    /// Returns true if a mode with the given ID exists in this schema.
    pub fn has_mode(&self, mode_id: &str) -> bool {
        self.modes.iter().any(|m| m.id == mode_id)
    }

    /// Returns the default game mode, if one is marked as default.
    /// A valid CGS must have exactly one default mode.
    pub fn default_mode(&self) -> Option<&GameMode> {
        self.modes.iter().find(|m| m.is_default)
    }

    /// Returns a global system by ID, if it exists.
    pub fn get_global_system(&self, system_id: &str) -> Option<&SystemDefinition> {
        self.global_systems.iter().find(|s| s.id == system_id)
    }

    /// Returns true if a global system with the given ID exists.
    pub fn has_global_system(&self, system_id: &str) -> bool {
        self.global_systems.iter().any(|s| s.id == system_id)
    }

    /// Returns the total number of systems across all modes and global.
    /// Used for complexity estimation and performance risk assessment.
    pub fn total_system_count(&self) -> usize {
        let mode_systems: usize = self.modes
            .iter()
            .map(|m| m.systems.len())
            .sum();
        self.global_systems.len() + mode_systems
    }

    /// Returns the total number of actor definitions across all modes.
    pub fn total_actor_count(&self) -> usize {
        self.modes.iter().map(|m| m.actors.len()).sum()
    }

    /// Returns true if this CGS passes basic structural validation.
    ///
    /// Full validation is performed by the Schema Factory (Phase 11).
    /// This is a lightweight check for obvious problems:
    /// - At least one mode exists
    /// - Exactly one default mode exists
    /// - No duplicate mode IDs
    /// - game_id is not empty
    pub fn is_structurally_valid(&self) -> Result<(), String> {
        if self.metadata.game_id.is_empty() {
            return Err("CGS game_id must not be empty".into());
        }

        if self.modes.is_empty() {
            return Err("CGS must contain at least one game mode".into());
        }

        // Check for duplicate mode IDs
        let mut seen_ids = std::collections::HashSet::new();
        for mode in &self.modes {
            if !seen_ids.insert(&mode.id) {
                return Err(format!(
                    "Duplicate mode ID in CGS: {}",
                    mode.id
                ));
            }
        }

        // Exactly one default mode
        let default_count = self.modes.iter().filter(|m| m.is_default).count();
        if default_count == 0 {
            return Err("CGS must have exactly one default mode — none found".into());
        }
        if default_count > 1 {
            return Err(format!(
                "CGS must have exactly one default mode — found {}",
                default_count
            ));
        }

        // Check for duplicate global system IDs
        let mut seen_systems = std::collections::HashSet::new();
        for system in &self.global_systems {
            if !seen_systems.insert(&system.id) {
                return Err(format!(
                    "Duplicate global system ID in CGS: {}",
                    system.id
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
    use crate::schema::game_mode::GameMode;

    fn test_metadata() -> CgsMetadata {
        CgsMetadata::new(
            "game-uuid-001",
            "Test Game",
            "2026-01-01T00:00:00Z",
            "0.1.0",
        )
    }

    fn minimal_valid_cgs() -> CanonicalGameSchema {
        let mut cgs = CanonicalGameSchema::new(test_metadata());
        cgs.modes.push(GameMode::new("mode_main", "Main Mode", true));
        cgs
    }

    #[test]
    fn new_cgs_starts_empty() {
        let cgs = CanonicalGameSchema::new(test_metadata());
        assert!(cgs.modes.is_empty());
        assert!(cgs.global_systems.is_empty());
    }

    #[test]
    fn valid_cgs_passes_structural_check() {
        let cgs = minimal_valid_cgs();
        assert!(cgs.is_structurally_valid().is_ok());
    }

    #[test]
    fn empty_game_id_fails_validation() {
        let mut meta = test_metadata();
        meta.game_id = String::new();
        let cgs = CanonicalGameSchema::new(meta);
        assert!(cgs.is_structurally_valid().is_err());
    }

    #[test]
    fn no_modes_fails_validation() {
        let cgs = CanonicalGameSchema::new(test_metadata());
        assert!(cgs.is_structurally_valid().is_err());
    }

    #[test]
    fn no_default_mode_fails_validation() {
        let mut cgs = CanonicalGameSchema::new(test_metadata());
        cgs.modes.push(GameMode::new("mode_arena", "Arena", false));
        assert!(cgs.is_structurally_valid().is_err());
    }

    #[test]
    fn duplicate_mode_ids_fail_validation() {
        let mut cgs = CanonicalGameSchema::new(test_metadata());
        cgs.modes.push(GameMode::new("mode_arena", "Arena", true));
        cgs.modes.push(GameMode::new("mode_arena", "Arena2", false));
        assert!(cgs.is_structurally_valid().is_err());
    }

    #[test]
    fn two_default_modes_fail_validation() {
        let mut cgs = CanonicalGameSchema::new(test_metadata());
        cgs.modes.push(GameMode::new("mode_arena", "Arena", true));
        cgs.modes.push(GameMode::new("mode_survival", "Survival", true));
        assert!(cgs.is_structurally_valid().is_err());
    }

    #[test]
    fn get_mode_returns_correct_mode() {
        let cgs = minimal_valid_cgs();
        let mode = cgs.get_mode("mode_main");
        assert!(mode.is_some());
        assert_eq!(mode.unwrap().id, "mode_main");
    }

    #[test]
    fn get_mode_returns_none_for_unknown() {
        let cgs = minimal_valid_cgs();
        assert!(cgs.get_mode("mode_nonexistent").is_none());
    }

    #[test]
    fn default_mode_found() {
        let cgs = minimal_valid_cgs();
        let default = cgs.default_mode();
        assert!(default.is_some());
        assert!(default.unwrap().is_default);
    }

    #[test]
    fn version_increments_correctly() {
        let v = CgsVersion::new(1, 2, 3);
        assert_eq!(v.increment_patch(), CgsVersion::new(1, 2, 4));
        assert_eq!(v.increment_minor(), CgsVersion::new(1, 3, 0));
        assert_eq!(v.increment_major(), CgsVersion::new(2, 0, 0));
    }

    #[test]
    fn version_compatibility_same_major() {
        let v1 = CgsVersion::new(1, 0, 0);
        let v2 = CgsVersion::new(1, 5, 3);
        assert!(v1.is_compatible_with(&v2));
    }

    #[test]
    fn version_incompatibility_different_major() {
        let v1 = CgsVersion::new(1, 0, 0);
        let v2 = CgsVersion::new(2, 0, 0);
        assert!(!v1.is_compatible_with(&v2));
    }

    #[test]
    fn version_display() {
        let v = CgsVersion::new(1, 2, 3);
        assert_eq!(v.to_string(), "1.2.3");
    }

    #[test]
    fn total_system_count_includes_global_and_mode() {
        let mut cgs = minimal_valid_cgs();
        assert_eq!(cgs.total_system_count(), 0);
        cgs.global_systems.push(
            SystemDefinition::new("sys_input", "InputSystem")
        );
        assert_eq!(cgs.total_system_count(), 1);
    }
}
