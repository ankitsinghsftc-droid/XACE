//! # Asset Type
//!
//! Defines the type of asset a reference points to.
//! Every AssetReference carries an AssetType so the engine adapter
//! knows exactly how to load and use the referenced file.
//!
//! ## Why Typed
//! Without explicit type information, the engine adapter would have to
//! guess from file extensions or naming conventions — both fragile.
//! Explicit typing means the adapter always knows whether to load a
//! mesh, a texture, an audio clip, or an animation controller.
//!
//! ## Engine Adapter Responsibility
//! The engine adapter maps each AssetType to its engine-specific
//! loading API. XACE never calls asset loading APIs directly.
//! Unity maps Mesh → GameObject with MeshRenderer.
//! Godot maps Mesh → MeshInstance3D. XACE is engine-agnostic.

use serde::{Deserialize, Serialize};

// ── Asset Type ────────────────────────────────────────────────────────────────

/// The category of asset a reference points to.
///
/// Used by the engine adapter to determine how to load and apply
/// the referenced asset. Also used by the Asset Registry to organize
/// and validate asset manifests.
///
/// ## Auto-Naming Convention
/// Each variant maps to a suffix in the auto-naming convention:
/// - Mesh           → _mesh_v[N]
/// - Texture        → _texture_v[N]
/// - Material       → _material_v[N]
/// - AnimationController → _anim_v[N]
/// - AudioClip      → _sfx_v[N]
/// - AudioMusic     → _music_v[N]
/// - Sprite         → _sprite_v[N]
/// - Particle       → _particle_v[N]
/// - Prefab         → _prefab_v[N]
/// - Font           → _font_v[N]
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum AssetType {
    /// A 3D mesh asset. Loaded by the engine as a renderable geometry.
    /// Used with RenderType::Mesh3D in COMP_RENDER_V1.
    /// Engine maps this to: Unity MeshFilter, Godot MeshInstance3D,
    /// Unreal StaticMeshComponent.
    Mesh,

    /// A 2D or 3D texture image. Applied to materials or UI elements.
    /// Formats: PNG, JPG, TGA, EXR — engine handles conversion.
    Texture,

    /// A material definition controlling surface appearance.
    /// References shaders, textures, and rendering properties.
    /// Engine-specific format: Unity Material, Godot ShaderMaterial.
    Material,

    /// An animation controller / state machine asset.
    /// Drives COMP_ANIMATION_V2 state transitions and blend trees.
    /// Engine maps this to: Unity AnimatorController, Godot AnimationTree.
    AnimationController,

    /// A short audio clip for sound effects.
    /// Played on demand by the audio system.
    /// Examples: footsteps, gunshots, UI clicks, impact sounds.
    AudioClip,

    /// A music track for background audio.
    /// Streamed rather than fully loaded into memory.
    /// Driven by COMP_MUSIC_STATE_V1 in dcl/audio/.
    AudioMusic,

    /// A 2D sprite image for 2D games or billboard elements.
    /// Used with RenderType::Sprite2D in COMP_RENDER_V1.
    Sprite,

    /// A particle system effect asset.
    /// Defines particle emission, movement, and appearance.
    /// Used with RenderType::ParticleEffect in COMP_RENDER_V1.
    Particle,

    /// A prefab — a pre-configured entity template.
    /// Referenced by COMP_IDENTITY_V1.prefab_id and spawner systems.
    /// The Schema Factory resolves prefabs into EntityBlueprints.
    Prefab,

    /// A font asset for UI text rendering.
    /// Used by COMP_UI_ELEMENT_V1 in dcl/ui/.
    Font,
}

impl AssetType {
    /// Returns the auto-naming suffix for this asset type.
    /// Used by the Asset Registry when generating asset IDs.
    ///
    /// Full ID format: [entity_type]_[entity_name]_[suffix]_v[N]
    /// Example: character_knight_mesh_v1
    pub fn naming_suffix(&self) -> &'static str {
        match self {
            AssetType::Mesh => "mesh",
            AssetType::Texture => "texture",
            AssetType::Material => "material",
            AssetType::AnimationController => "anim",
            AssetType::AudioClip => "sfx",
            AssetType::AudioMusic => "music",
            AssetType::Sprite => "sprite",
            AssetType::Particle => "particle",
            AssetType::Prefab => "prefab",
            AssetType::Font => "font",
        }
    }

    /// Returns a human-readable display name for this asset type.
    pub fn display_name(&self) -> &'static str {
        match self {
            AssetType::Mesh => "3D Mesh",
            AssetType::Texture => "Texture",
            AssetType::Material => "Material",
            AssetType::AnimationController => "Animation Controller",
            AssetType::AudioClip => "Audio Clip",
            AssetType::AudioMusic => "Music Track",
            AssetType::Sprite => "2D Sprite",
            AssetType::Particle => "Particle Effect",
            AssetType::Prefab => "Prefab",
            AssetType::Font => "Font",
        }
    }

    /// Returns true if this asset type is visual — affects rendering.
    /// Used by the builder UI to group assets in the asset panel.
    pub fn is_visual(&self) -> bool {
        matches!(
            self,
            AssetType::Mesh
                | AssetType::Texture
                | AssetType::Material
                | AssetType::Sprite
                | AssetType::Particle
        )
    }

    /// Returns true if this asset type is audio.
    pub fn is_audio(&self) -> bool {
        matches!(self, AssetType::AudioClip | AssetType::AudioMusic)
    }

    /// Returns true if this asset type is streamed rather than
    /// fully loaded into memory at once.
    /// Only music tracks are streamed — all other types are fully loaded.
    pub fn is_streamed(&self) -> bool {
        matches!(self, AssetType::AudioMusic)
    }
}

impl std::fmt::Display for AssetType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.display_name())
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mesh_naming_suffix() {
        assert_eq!(AssetType::Mesh.naming_suffix(), "mesh");
    }

    #[test]
    fn audio_clip_naming_suffix() {
        assert_eq!(AssetType::AudioClip.naming_suffix(), "sfx");
    }

    #[test]
    fn animation_controller_naming_suffix() {
        assert_eq!(AssetType::AnimationController.naming_suffix(), "anim");
    }

    #[test]
    fn visual_types_are_visual() {
        assert!(AssetType::Mesh.is_visual());
        assert!(AssetType::Texture.is_visual());
        assert!(AssetType::Material.is_visual());
        assert!(AssetType::Sprite.is_visual());
        assert!(AssetType::Particle.is_visual());
    }

    #[test]
    fn audio_types_are_not_visual() {
        assert!(!AssetType::AudioClip.is_visual());
        assert!(!AssetType::AudioMusic.is_visual());
    }

    #[test]
    fn audio_types_are_audio() {
        assert!(AssetType::AudioClip.is_audio());
        assert!(AssetType::AudioMusic.is_audio());
    }

    #[test]
    fn mesh_is_not_audio() {
        assert!(!AssetType::Mesh.is_audio());
    }

    #[test]
    fn only_music_is_streamed() {
        assert!(AssetType::AudioMusic.is_streamed());
        assert!(!AssetType::AudioClip.is_streamed());
        assert!(!AssetType::Mesh.is_streamed());
    }

    #[test]
    fn display_name_is_human_readable() {
        assert_eq!(AssetType::Mesh.to_string(), "3D Mesh");
        assert_eq!(AssetType::AnimationController.to_string(), "Animation Controller");
        assert_eq!(AssetType::AudioMusic.to_string(), "Music Track");
    }

    #[test]
    fn all_types_have_naming_suffix() {
        let types = [
            AssetType::Mesh,
            AssetType::Texture,
            AssetType::Material,
            AssetType::AnimationController,
            AssetType::AudioClip,
            AssetType::AudioMusic,
            AssetType::Sprite,
            AssetType::Particle,
            AssetType::Prefab,
            AssetType::Font,
        ];
        for t in types {
            assert!(!t.naming_suffix().is_empty());
        }
    }
}