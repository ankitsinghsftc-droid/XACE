"""
asset_type_enum.py — AssetType enumeration for the XACE Asset Registry.

Mirrors packages/core/src/assets/asset_type_enum.rs exactly.
Every asset reference in XACE carries one of these types — never a raw string.

## Type Coverage
Eleven asset types covering all engine-rendered and engine-played content.
The type determines which engine component accepts the reference, and which
validation rules apply when transitioning from PLACEHOLDER → LINKED.

## Audit 2 Contract
Asset references are typed AssetReference objects — NEVER raw strings.
The AssetType is embedded in every AssetReference and checked at validation time.
"""

from enum import Enum


class AssetType(str, Enum):
    """
    All supported asset types in the XACE asset pipeline.

    Discriminants match the Rust asset_type_enum.rs — do not reorder.
    String values are the canonical serialization used in CGS JSON and
    game_config.yaml.
    """

    # ── Visual Assets ──────────────────────────────────────────────────────

    MESH = "MESH"
    """
    3D geometry asset. Used by COMP_RENDER_V1.asset_reference.
    Engine references: .fbx, .obj, .gltf, .glb (Unity), StaticMesh (Unreal).
    Placeholder behaviour: entity renders as grey box at origin.
    """

    TEXTURE = "TEXTURE"
    """
    2D image asset. Used by material definitions and sprite references.
    Engine references: .png, .jpg, .tga, .exr.
    Placeholder behaviour: magenta/checkerboard fill.
    """

    MATERIAL = "MATERIAL"
    """
    Shader/surface definition. Used by COMP_RENDER_V1.material_ref.
    Engine references: .mat (Unity), Material Instance (Unreal).
    Placeholder behaviour: engine default material (grey unlit).
    """

    ANIMATION_CONTROLLER = "ANIMATION_CONTROLLER"
    """
    State machine / blend tree definition.
    Used by COMP_ANIMATION_V2.controller_ref.
    Engine references: Animator Controller (Unity), Anim Blueprint (Unreal).
    Placeholder behaviour: entity frozen in T-pose / default pose.
    """

    ANIMATION_CLIP = "ANIMATION_CLIP"
    """
    Single animation clip/sequence.
    Used by semantic event bindings and animation command playback.
    Engine references: AnimationClip (Unity), Animation resource (Godot),
    Animation Sequence (Unreal).
    Placeholder behaviour: requested animation is skipped.
    """

    # ── Audio Assets ───────────────────────────────────────────────────────

    AUDIO_CLIP = "AUDIO_CLIP"
    """
    Short audio event — SFX, voice line, foley.
    Used by COMP_AUDIO_EMITTER_V1.asset_reference.
    Engine references: .wav, .ogg, .mp3.
    Placeholder behaviour: silent (no audio plays).
    """

    AUDIO_MUSIC = "AUDIO_MUSIC"
    """
    Long-form music track. Used by COMP_MUSIC_STATE_V1.
    Distinct from AUDIO_CLIP — music uses streaming playback.
    Placeholder behaviour: silent.
    """

    # ── 2D / UI Assets ─────────────────────────────────────────────────────

    SPRITE = "SPRITE"
    """
    2D sprite image. Used by COMP_RENDER_V1 in 2D game modes.
    Engine references: sprite atlas slices, individual .png.
    Placeholder behaviour: magenta square.
    """

    # ── VFX Assets ─────────────────────────────────────────────────────────

    PARTICLE = "PARTICLE"
    """
    Particle system / VFX definition.
    Engine references: Particle System (Unity), Niagara (Unreal).
    Placeholder behaviour: no particle effect plays.
    """

    # ── Composite Assets ───────────────────────────────────────────────────

    PREFAB = "PREFAB"
    """
    Pre-configured entity template.
    Engine references: .prefab (Unity), Blueprint (Unreal).
    Placeholder behaviour: empty GameObject / Actor at spawn point.
    """

    # ── Typography ─────────────────────────────────────────────────────────

    FONT = "FONT"
    """
    Font asset for UI text rendering.
    Used by COMP_UI_ELEMENT_V1.
    Engine references: .ttf, .otf, SDF font atlas.
    Placeholder behaviour: engine default system font.
    """

    # ── Utility Methods ────────────────────────────────────────────────────

    @property
    def is_audio(self) -> bool:
        """Returns True if this is an audio asset type."""
        return self in (AssetType.AUDIO_CLIP, AssetType.AUDIO_MUSIC)

    @property
    def is_visual(self) -> bool:
        """Returns True if this is a visual rendering asset."""
        return self in (
            AssetType.MESH,
            AssetType.TEXTURE,
            AssetType.MATERIAL,
            AssetType.SPRITE,
            AssetType.PARTICLE,
        )

    @property
    def is_animation_related(self) -> bool:
        """Returns True if this type is required by the animation system."""
        return self in (AssetType.ANIMATION_CONTROLLER, AssetType.ANIMATION_CLIP)

    @property
    def placeholder_description(self) -> str:
        """Human-readable description of placeholder behaviour for the builder UI."""
        descriptions = {
            AssetType.MESH: "Renders as grey box",
            AssetType.TEXTURE: "Shows magenta/checkerboard",
            AssetType.MATERIAL: "Uses engine default grey material",
            AssetType.ANIMATION_CONTROLLER: "Entity frozen in default pose",
            AssetType.ANIMATION_CLIP: "Animation request is skipped",
            AssetType.AUDIO_CLIP: "Silent — no audio plays",
            AssetType.AUDIO_MUSIC: "Silent — no music plays",
            AssetType.SPRITE: "Shows magenta square",
            AssetType.PARTICLE: "No particle effect",
            AssetType.PREFAB: "Empty object at spawn point",
            AssetType.FONT: "Uses system default font",
        }
        return descriptions[self]

    @classmethod
    def all_types(cls) -> list["AssetType"]:
        """Returns all asset types in declaration order."""
        return list(cls)

    @classmethod
    def from_string(cls, value: str) -> "AssetType":
        """
        Parses an AssetType from its string value.
        Raises ValueError for unknown strings.
        """
        try:
            return cls(value.upper())
        except ValueError:
            raise ValueError(
                f"Unknown AssetType: '{value}'. "
                f"Valid types: {[t.value for t in cls]}"
            )
