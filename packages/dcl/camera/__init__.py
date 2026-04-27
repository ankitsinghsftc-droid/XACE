"""
DCL Camera Domain — packages/dcl/camera/__init__.py

Provides camera control components:
- COMP_CAMERA_V1       (type_id=280)
- COMP_CAMERA_SHAKE_V1 (type_id=281)
- COMP_CINEMATIC_V1    (type_id=282)

Type ID block: 280-299 (camera reserved range)
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
        domain_name="camera",
        display_name="Camera Domain",
        domain_version=1,
        description="Camera control — follow cameras, shake effects, cinematic sequences.",
        dependencies=[],
        components=[
            ComponentDefinition(
                type_id=280,
                type_name="COMP_CAMERA_V1",
                layer=ComponentLayer.DCL,
                domain="camera",
                version=1,
                description="Camera configuration and follow target.",
                fields=[
                    ComponentFieldDefinition(
                        "mode", "enum", False, '"ThirdPerson"',
                        "CameraMode: FirstPerson|ThirdPerson|Fixed|Orbital|TopDown|Isometric"
                    ),
                    ComponentFieldDefinition(
                        "fov", "f32", False, "60.0",
                        "Field of view in degrees."
                    ),
                    ComponentFieldDefinition(
                        "near_clip", "f32", False, "0.1",
                        "Near clipping plane distance."
                    ),
                    ComponentFieldDefinition(
                        "far_clip", "f32", False, "1000.0",
                        "Far clipping plane distance."
                    ),
                    ComponentFieldDefinition(
                        "follow_target_entity", "u64", False, "0",
                        "Entity to follow. 0 = fixed position."
                    ),
                    ComponentFieldDefinition(
                        "offset", "struct", False, None,
                        "Vec3 offset from follow target."
                    ),
                    ComponentFieldDefinition(
                        "rotation_lock", "bool", False, "false",
                        "True if camera rotation is locked."
                    ),
                    ComponentFieldDefinition(
                        "smoothing", "f32", False, "0.1",
                        "Camera follow smoothing (0.0=instant, 1.0=very smooth)."
                    ),
                    ComponentFieldDefinition(
                        "is_active", "bool", False, "true",
                        "Whether this is the active camera."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=281,
                type_name="COMP_CAMERA_SHAKE_V1",
                layer=ComponentLayer.DCL,
                domain="camera",
                version=1,
                description="Camera shake effect — applied additively to active camera.",
                fields=[
                    ComponentFieldDefinition(
                        "intensity", "f32", False, "1.0",
                        "Shake intensity (0.0=none, 1.0=max)."
                    ),
                    ComponentFieldDefinition(
                        "duration_ticks", "u64", False, "30",
                        "How long the shake lasts."
                    ),
                    ComponentFieldDefinition(
                        "elapsed_ticks", "u64", False, "0",
                        "Ticks since shake started."
                    ),
                    ComponentFieldDefinition(
                        "frequency", "f32", False, "10.0",
                        "Shake oscillation frequency."
                    ),
                    ComponentFieldDefinition(
                        "decay_rate", "f32", False, "1.0",
                        "How quickly intensity fades over duration."
                    ),
                    ComponentFieldDefinition(
                        "is_active", "bool", False, "false",
                        "Whether shake is currently active."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=282,
                type_name="COMP_CINEMATIC_V1",
                layer=ComponentLayer.DCL,
                domain="camera",
                version=1,
                description="Cinematic sequence control — cutscene camera paths.",
                fields=[
                    ComponentFieldDefinition(
                        "sequence_id", "str", True, None,
                        "ID of the cinematic sequence asset."
                    ),
                    ComponentFieldDefinition(
                        "is_playing", "bool", False, "false",
                        "Whether the sequence is currently playing."
                    ),
                    ComponentFieldDefinition(
                        "current_tick", "u64", False, "0",
                        "Current playback position in ticks."
                    ),
                    ComponentFieldDefinition(
                        "playback_speed", "f32", False, "1.0",
                        "Sequence playback speed multiplier."
                    ),
                    ComponentFieldDefinition(
                        "loop", "bool", False, "false",
                        "Whether to loop the sequence."
                    ),
                    ComponentFieldDefinition(
                        "skippable", "bool", False, "true",
                        "Whether the player can skip this cinematic."
                    ),
                ],
            ),
        ],
    )