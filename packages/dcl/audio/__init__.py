"""
DCL Audio Domain — packages/dcl/audio/__init__.py

Provides spatial audio components:
- COMP_AUDIO_EMITTER_V1  (type_id=300)
- COMP_AUDIO_LISTENER_V1 (type_id=301)
- COMP_MUSIC_STATE_V1    (type_id=302)
- COMP_AUDIO_ZONE_V1     (type_id=303)

Type ID block: 300-319 (audio reserved range)
"""

from __future__ import annotations
from ..dcl_registry import (
    ComponentDefinition,
    ComponentFieldDefinition,
    ComponentLayer,
)
from ..domain_package import DomainPackage


def get_domain_package() -> DomainPackage:
    return DomainPackage(
        domain_name="audio",
        display_name="Audio Domain",
        domain_version=1,
        description="Spatial audio — emitters, listeners, music state, audio zones.",
        dependencies=[],
        components=[
            ComponentDefinition(
                type_id=300,
                type_name="COMP_AUDIO_EMITTER_V1",
                layer=ComponentLayer.DCL,
                domain="audio",
                version=1,
                description="3D audio emitter — plays sound effects in world space.",
                fields=[
                    ComponentFieldDefinition(
                        "clip_ref", "asset_reference", True, None,
                        "AssetReference to the audio clip."
                    ),
                    ComponentFieldDefinition(
                        "volume", "f32", False, "1.0",
                        "Playback volume (0.0=silent, 1.0=full)."
                    ),
                    ComponentFieldDefinition(
                        "pitch", "f32", False, "1.0",
                        "Playback pitch multiplier."
                    ),
                    ComponentFieldDefinition(
                        "is_playing", "bool", False, "false",
                        "Whether audio is currently playing."
                    ),
                    ComponentFieldDefinition(
                        "loop", "bool", False, "false",
                        "Whether to loop the clip."
                    ),
                    ComponentFieldDefinition(
                        "min_distance", "f32", False, "1.0",
                        "Distance at which volume starts attenuating."
                    ),
                    ComponentFieldDefinition(
                        "max_distance", "f32", False, "20.0",
                        "Distance at which audio is inaudible."
                    ),
                    ComponentFieldDefinition(
                        "spatial_blend", "f32", False, "1.0",
                        "0.0 = 2D audio, 1.0 = fully 3D spatial."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=301,
                type_name="COMP_AUDIO_LISTENER_V1",
                layer=ComponentLayer.DCL,
                domain="audio",
                version=1,
                description="Audio listener — the ear position for 3D audio. Usually on the camera or player.",
                fields=[
                    ComponentFieldDefinition(
                        "is_active", "bool", False, "true",
                        "Whether this is the active audio listener. "
                        "Only one listener should be active at a time."
                    ),
                    ComponentFieldDefinition(
                        "volume_scale", "f32", False, "1.0",
                        "Master volume scale for all audio heard by this listener."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=302,
                type_name="COMP_MUSIC_STATE_V1",
                layer=ComponentLayer.DCL,
                domain="audio",
                version=1,
                description=(
                    "Music playback state. Intensity driven by game events "
                    "and distance from threats."
                ),
                fields=[
                    ComponentFieldDefinition(
                        "track_ref", "asset_reference", False, None,
                        "AssetReference to current music track."
                    ),
                    ComponentFieldDefinition(
                        "intensity_value", "f32", False, "0.0",
                        "Music intensity (0.0=calm, 1.0=combat). "
                        "Drives adaptive music layer blending."
                    ),
                    ComponentFieldDefinition(
                        "volume", "f32", False, "1.0",
                        "Music volume."
                    ),
                    ComponentFieldDefinition(
                        "is_playing", "bool", False, "false",
                        "Whether music is currently playing."
                    ),
                    ComponentFieldDefinition(
                        "crossfade_ticks", "u64", False, "60",
                        "Ticks for crossfade when switching tracks."
                    ),
                    ComponentFieldDefinition(
                        "loop", "bool", False, "true",
                        "Whether to loop the music track."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=303,
                type_name="COMP_AUDIO_ZONE_V1",
                layer=ComponentLayer.DCL,
                domain="audio",
                version=1,
                description="Audio zone — applies reverb, filters, or ambient sounds in a volume.",
                fields=[
                    ComponentFieldDefinition(
                        "zone_type", "enum", False, '"Reverb"',
                        "AudioZoneType: Reverb|LowPass|HighPass|Ambient"
                    ),
                    ComponentFieldDefinition(
                        "reverb_preset", "str", False, '"default"',
                        "Named reverb preset ID (cave, room, hall, etc.)."
                    ),
                    ComponentFieldDefinition(
                        "ambient_clip_ref", "asset_reference", False, None,
                        "Ambient sound AssetReference played inside this zone."
                    ),
                    ComponentFieldDefinition(
                        "blend_distance", "f32", False, "2.0",
                        "Distance over which zone effect blends in/out."
                    ),
                    ComponentFieldDefinition(
                        "is_active", "bool", False, "true",
                        "Whether this zone is active."
                    ),
                ],
            ),
        ],
    )