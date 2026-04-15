//! # UCL Registry
//!
//! The Universal Component Library v1 registry. Maps every UCL Core
//! component type ID to its metadata. This registry is FROZEN FOREVER —
//! no components may be added, removed, or modified after v1 is shipped.
//!
//! ## Why Frozen
//! Every snapshot, replay, and wire message ever produced by XACE
//! references these component type IDs. Changing them would break
//! backward compatibility with every saved game, every replay file,
//! and every engine adapter ever built against this version.
//!
//! ## Three-Layer Architecture (Audit 1)
//! UCL Core (this file) — 10 components, frozen, owned by XACE
//! DCL (packages/dcl/) — domain packages, versioned, owned by XACE
//! GCL (game project) — per-game components, validated by XACE
//!
//! The CompositeComponentRegistry (Phase 11, Schema Factory) assembles
//! all three layers at game load. This registry covers UCL Core only.
//!
//! ## Determinism
//! Component type IDs are u32 constants — never dynamic, never generated
//! at runtime. The same ID always maps to the same component type across
//! all machines, all sessions, all engine adapters (D11).

use std::collections::BTreeMap;
use serde::{Deserialize, Serialize};

use crate::ucl::transform_component::COMP_TRANSFORM_V1_ID;
use crate::ucl::identity_component::COMP_IDENTITY_V1_ID;
use crate::ucl::render_component::COMP_RENDER_V1_ID;
use crate::ucl::collider_component::COMP_COLLIDER_V1_ID;
use crate::ucl::velocity_component::COMP_VELOCITY_V1_ID;
use crate::ucl::input_component::COMP_INPUT_V1_ID;
use crate::ucl::event_component::COMP_EVENT_V1_ID;
use crate::ucl::lifetime_component::COMP_LIFETIME_V1_ID;
use crate::ucl::game_state_component::COMP_GAMESTATE_V1_ID;
use crate::ucl::authority_component::COMP_AUTHORITY_V1_ID;

// ── Component Category ────────────────────────────────────────────────────────

/// Which layer of the three-layer component architecture this belongs to.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum ComponentLayer {
    /// Universal Component Library Core — frozen forever.
    UclCore,
    /// Domain Component Library — versioned, XACE-owned.
    Dcl,
    /// Game Component Library — per-game, developer-owned.
    Gcl,
}

// ── Component Metadata ────────────────────────────────────────────────────────

/// Metadata record for a single registered component type.
///
/// Stored in the registry for every known component type.
/// Used by the Schema Factory, Mutation Gate, and engine adapter
/// to validate component usage without importing concrete types.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ComponentMetadata {
    /// Unique numeric identifier. Frozen after assignment.
    /// Used as the key in ComponentTableStore.
    pub type_id: u32,

    /// Canonical name used in DSL paths and schema definitions.
    /// Example: "COMP_TRANSFORM_V1"
    pub type_name: &'static str,

    /// Human-readable description of what this component does.
    pub description: &'static str,

    /// Which layer this component belongs to.
    pub layer: ComponentLayer,

    /// Schema version of this component definition.
    /// Incremented when fields are added or changed.
    /// V1 = initial release. Frozen for UCL Core.
    pub version: u32,

    /// Whether this component is required on every entity.
    /// Currently no UCL Core component is strictly required —
    /// entities may have any subset of the 10 UCL components.
    pub is_universal: bool,
}

impl ComponentMetadata {
    /// Creates a UCL Core component metadata record.
    const fn ucl_core(
        type_id: u32,
        type_name: &'static str,
        description: &'static str,
    ) -> Self {
        Self {
            type_id,
            type_name,
            description,
            layer: ComponentLayer::UclCore,
            version: 1,
            is_universal: false,
        }
    }
}

// ── UCL Registry ──────────────────────────────────────────────────────────────

/// The frozen UCL Core component registry.
///
/// Contains exactly 10 component definitions — no more, no fewer.
/// Initialized once at startup. Never modified at runtime.
///
/// ## Usage
/// - Schema Factory uses this to validate actor component declarations
/// - Mutation Gate uses this to validate component type IDs before writes
/// - Engine Adapter uses this to map type IDs to engine-specific handlers
/// - SGC uses this to validate system read/write declarations
///
/// ## BTreeMap
/// Uses BTreeMap for deterministic iteration order (D11).
/// Keys are component type IDs (u32), values are ComponentMetadata.
pub struct UclRegistry {
    /// The frozen set of UCL Core component definitions.
    /// BTreeMap guarantees deterministic key ordering.
    components: BTreeMap<u32, ComponentMetadata>,
}

impl UclRegistry {
    /// Creates and initializes the UCL v1 registry.
    ///
    /// Called once during runtime initialization. The registry is
    /// immutable after creation — no components may be added or removed.
    ///
    /// ## The 10 UCL Core Components (Audit 1 — Frozen Forever)
    /// 1.  COMP_TRANSFORM_V1   — spatial position, rotation, scale
    /// 2.  COMP_IDENTITY_V1    — name, type, faction, tags
    /// 3.  COMP_RENDER_V1      — visual representation
    /// 4.  COMP_COLLIDER_V1    — physical collision boundary
    /// 5.  COMP_VELOCITY_V1    — linear and angular velocity
    /// 6.  COMP_INPUT_V1       — control source routing
    /// 7.  COMP_EVENT_V1       — in-world event carrier
    /// 8.  COMP_LIFETIME_V1    — automatic expiry timer
    /// 9.  COMP_GAMESTATE_V1   — global game session state
    /// 10. COMP_AUTHORITY_V1   — network authority and replication
    pub fn new() -> Self {
        let mut components = BTreeMap::new();

        let definitions = [
            ComponentMetadata::ucl_core(
                COMP_TRANSFORM_V1_ID,
                "COMP_TRANSFORM_V1",
                "Spatial position, rotation, and scale. Parent entity for hierarchy.",
            ),
            ComponentMetadata::ucl_core(
                COMP_IDENTITY_V1_ID,
                "COMP_IDENTITY_V1",
                "Entity name, type classification, faction, tags, and prefab origin.",
            ),
            ComponentMetadata::ucl_core(
                COMP_RENDER_V1_ID,
                "COMP_RENDER_V1",
                "Visual representation: mesh, sprite, or particle. Asset reference typed.",
            ),
            ComponentMetadata::ucl_core(
                COMP_COLLIDER_V1_ID,
                "COMP_COLLIDER_V1",
                "Physical collision boundary: shape, size, trigger vs solid, layer mask.",
            ),
            ComponentMetadata::ucl_core(
                COMP_VELOCITY_V1_ID,
                "COMP_VELOCITY_V1",
                "Linear and angular velocity with configurable speed limits.",
            ),
            ComponentMetadata::ucl_core(
                COMP_INPUT_V1_ID,
                "COMP_INPUT_V1",
                "Control source routing: Human, AI proxy, or network remote.",
            ),
            ComponentMetadata::ucl_core(
                COMP_EVENT_V1_ID,
                "COMP_EVENT_V1",
                "In-world event carrier. Events never modify state directly (I9).",
            ),
            ComponentMetadata::ucl_core(
                COMP_LIFETIME_V1_ID,
                "COMP_LIFETIME_V1",
                "Automatic expiry timer in ticks. Destroy, disable, loop, or emit on expire.",
            ),
            ComponentMetadata::ucl_core(
                COMP_GAMESTATE_V1_ID,
                "COMP_GAMESTATE_V1",
                "Global game session state: phase, score, elapsed ticks, match state.",
            ),
            ComponentMetadata::ucl_core(
                COMP_AUTHORITY_V1_ID,
                "COMP_AUTHORITY_V1",
                "Network authority type, replication mode, prediction, and sync rate.",
            ),
        ];

        for def in definitions {
            components.insert(def.type_id, def);
        }

        Self { components }
    }

    /// Returns the metadata for a component type ID.
    /// Returns None if the type ID is not a registered UCL Core component.
    pub fn get(&self, type_id: u32) -> Option<&ComponentMetadata> {
        self.components.get(&type_id)
    }

    /// Returns true if the given type ID is a registered UCL Core component.
    pub fn contains(&self, type_id: u32) -> bool {
        self.components.contains_key(&type_id)
    }

    /// Returns the canonical type name for a component type ID.
    /// Returns None if not found.
    pub fn type_name(&self, type_id: u32) -> Option<&'static str> {
        self.components.get(&type_id).map(|m| m.type_name)
    }

    /// Returns all registered component type IDs in ascending order.
    /// BTreeMap guarantees deterministic ascending order (D11).
    pub fn all_type_ids(&self) -> Vec<u32> {
        self.components.keys().copied().collect()
    }

    /// Returns all component metadata records in type ID ascending order.
    /// Used by Schema Factory to build the CompositeComponentRegistry.
    pub fn all_components(&self) -> Vec<&ComponentMetadata> {
        self.components.values().collect()
    }

    /// Returns the total number of registered UCL Core components.
    /// Must always be exactly 10 — validated in tests.
    pub fn component_count(&self) -> usize {
        self.components.len()
    }

    /// Returns true if a component type name is registered.
    /// Used by the DSL path parser to validate component references.
    pub fn contains_name(&self, type_name: &str) -> bool {
        self.components
            .values()
            .any(|m| m.type_name == type_name)
    }

    /// Returns the type ID for a given component name.
    /// Used by the GDE when resolving DSL paths to type IDs.
    /// Returns None if the name is not a UCL Core component.
    pub fn type_id_for_name(&self, type_name: &str) -> Option<u32> {
        self.components
            .values()
            .find(|m| m.type_name == type_name)
            .map(|m| m.type_id)
    }

    /// Validates that the registry is internally consistent.
    ///
    /// Checks:
    /// - Exactly 10 components registered
    /// - All type IDs are unique (guaranteed by BTreeMap)
    /// - All type names are unique
    /// - All type IDs match their stored metadata type_id
    /// - All components are UCL Core layer
    ///
    /// Returns Ok(()) if valid, Err with description if not.
    /// Called during runtime initialization to catch any
    /// accidental registry corruption early.
    pub fn validate(&self) -> Result<(), String> {
        // Must have exactly 10 UCL Core components
        if self.components.len() != 10 {
            return Err(format!(
                "UCL registry must contain exactly 10 components, found {}",
                self.components.len()
            ));
        }

        // All type names must be unique
        let mut names = std::collections::HashSet::new();
        for meta in self.components.values() {
            if !names.insert(meta.type_name) {
                return Err(format!(
                    "Duplicate component type name in UCL registry: {}",
                    meta.type_name
                ));
            }

            // Type ID in map key must match type ID in metadata
            if !self.components.contains_key(&meta.type_id) {
                return Err(format!(
                    "Component {} has mismatched type_id in registry",
                    meta.type_name
                ));
            }

            // All must be UCL Core layer
            if meta.layer != ComponentLayer::UclCore {
                return Err(format!(
                    "Non-UCL-Core component {} found in UCL registry",
                    meta.type_name
                ));
            }

            // Version must be 1 for all UCL Core components
            if meta.version != 1 {
                return Err(format!(
                    "UCL Core component {} has version {} — must be 1",
                    meta.type_name, meta.version
                ));
            }
        }

        Ok(())
    }
}

impl Default for UclRegistry {
    fn default() -> Self {
        Self::new()
    }
}

// ── Global Constants ──────────────────────────────────────────────────────────

/// All 10 UCL Core component type IDs as a sorted array.
/// Used for iteration when a registry instance is not available.
/// Order matches BTreeMap ascending key order.
pub const UCL_CORE_TYPE_IDS: [u32; 10] = [
    COMP_TRANSFORM_V1_ID,   // 1
    COMP_IDENTITY_V1_ID,    // 2
    COMP_RENDER_V1_ID,      // 3
    COMP_COLLIDER_V1_ID,    // 4
    COMP_VELOCITY_V1_ID,    // 5
    COMP_INPUT_V1_ID,       // 6
    COMP_EVENT_V1_ID,       // 7
    COMP_LIFETIME_V1_ID,    // 8
    COMP_GAMESTATE_V1_ID,   // 9
    COMP_AUTHORITY_V1_ID,   // 10
];

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn registry() -> UclRegistry {
        UclRegistry::new()
    }

    #[test]
    fn registry_has_exactly_ten_components() {
        assert_eq!(registry().component_count(), 10);
    }

    #[test]
    fn registry_validates_successfully() {
        assert!(registry().validate().is_ok());
    }

    #[test]
    fn all_ucl_type_ids_registered() {
        let reg = registry();
        for id in UCL_CORE_TYPE_IDS {
            assert!(reg.contains(id), "Missing type ID: {}", id);
        }
    }

    #[test]
    fn type_ids_are_in_ascending_order() {
        let ids = registry().all_type_ids();
        for window in ids.windows(2) {
            assert!(window[0] < window[1]);
        }
    }

    #[test]
    fn get_returns_correct_metadata() {
        let reg = registry();
        let meta = reg.get(COMP_TRANSFORM_V1_ID).unwrap();
        assert_eq!(meta.type_name, "COMP_TRANSFORM_V1");
        assert_eq!(meta.layer, ComponentLayer::UclCore);
        assert_eq!(meta.version, 1);
    }

    #[test]
    fn unknown_type_id_returns_none() {
        let reg = registry();
        assert!(reg.get(9999).is_none());
        assert!(!reg.contains(9999));
    }

    #[test]
    fn type_name_lookup_works() {
        let reg = registry();
        assert_eq!(
            reg.type_name(COMP_IDENTITY_V1_ID),
            Some("COMP_IDENTITY_V1")
        );
    }

    #[test]
    fn contains_name_works() {
        let reg = registry();
        assert!(reg.contains_name("COMP_VELOCITY_V1"));
        assert!(!reg.contains_name("COMP_NONEXISTENT"));
    }

    #[test]
    fn type_id_for_name_works() {
        let reg = registry();
        assert_eq!(
            reg.type_id_for_name("COMP_AUTHORITY_V1"),
            Some(COMP_AUTHORITY_V1_ID)
        );
        assert_eq!(reg.type_id_for_name("COMP_FAKE"), None);
    }

    #[test]
    fn all_components_returns_ten() {
        assert_eq!(registry().all_components().len(), 10);
    }

    #[test]
    fn all_components_are_ucl_core_layer() {
        for meta in registry().all_components() {
            assert_eq!(meta.layer, ComponentLayer::UclCore);
        }
    }

    #[test]
    fn all_components_are_version_one() {
        for meta in registry().all_components() {
            assert_eq!(meta.version, 1);
        }
    }

    #[test]
    fn ucl_core_type_ids_constant_sorted() {
        for window in UCL_CORE_TYPE_IDS.windows(2) {
            assert!(window[0] < window[1]);
        }
    }

    #[test]
    fn transform_is_registered() {
        let reg = registry();
        assert!(reg.contains(COMP_TRANSFORM_V1_ID));
        assert!(reg.contains_name("COMP_TRANSFORM_V1"));
    }

    #[test]
    fn gamestate_is_registered() {
        let reg = registry();
        assert!(reg.contains(COMP_GAMESTATE_V1_ID));
        assert!(reg.contains_name("COMP_GAMESTATE_V1"));
    }
}
