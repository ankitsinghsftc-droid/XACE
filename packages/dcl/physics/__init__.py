"""
DCL Physics Domain — packages/dcl/physics/__init__.py

Provides physics simulation components:
- COMP_RIGIDBODY_V1          (type_id=140)
- COMP_SURFACE_PROPERTIES_V1 (type_id=141)
- COMP_BUOYANCY_V1           (type_id=142)
- COMP_SOFT_BODY_V1          (type_id=143)

Type ID block: 140-159 (physics reserved range)
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
        domain_name="physics",
        display_name="Physics Domain",
        domain_version=1,
        description="Physics simulation — rigidbody, surface properties, buoyancy, soft body.",
        dependencies=[],
        components=[
            ComponentDefinition(
                type_id=140,
                type_name="COMP_RIGIDBODY_V1",
                layer=ComponentLayer.DCL,
                domain="physics",
                version=1,
                description=(
                    "Full rigidbody physics simulation properties. "
                    "The engine applies forces, drag, and gravity based on these values."
                ),
                fields=[
                    ComponentFieldDefinition(
                        "mass", "f32", True, None,
                        "Mass in kg. Must be > 0."
                    ),
                    ComponentFieldDefinition(
                        "drag", "f32", False, "0.0",
                        "Linear drag coefficient. 0 = no drag."
                    ),
                    ComponentFieldDefinition(
                        "angular_drag", "f32", False, "0.05",
                        "Angular drag coefficient."
                    ),
                    ComponentFieldDefinition(
                        "use_gravity", "bool", False, "true",
                        "Whether gravity affects this rigidbody."
                    ),
                    ComponentFieldDefinition(
                        "is_kinematic", "bool", False, "false",
                        "If true, physics forces don't move this body — "
                        "it's moved only by XACE system mutations."
                    ),
                    ComponentFieldDefinition(
                        "freeze_position_x", "bool", False, "false",
                        "Lock X-axis position."
                    ),
                    ComponentFieldDefinition(
                        "freeze_position_y", "bool", False, "false",
                        "Lock Y-axis position."
                    ),
                    ComponentFieldDefinition(
                        "freeze_position_z", "bool", False, "false",
                        "Lock Z-axis position."
                    ),
                    ComponentFieldDefinition(
                        "freeze_rotation_x", "bool", False, "false",
                        "Lock X-axis rotation."
                    ),
                    ComponentFieldDefinition(
                        "freeze_rotation_y", "bool", False, "false",
                        "Lock Y-axis rotation."
                    ),
                    ComponentFieldDefinition(
                        "freeze_rotation_z", "bool", False, "false",
                        "Lock Z-axis rotation."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=141,
                type_name="COMP_SURFACE_PROPERTIES_V1",
                layer=ComponentLayer.DCL,
                domain="physics",
                version=1,
                description="Physical surface material properties for collision response.",
                fields=[
                    ComponentFieldDefinition(
                        "friction", "f32", False, "0.6",
                        "Friction coefficient (0.0=ice, 1.0=rubber)."
                    ),
                    ComponentFieldDefinition(
                        "bounciness", "f32", False, "0.0",
                        "Restitution coefficient (0.0=no bounce, 1.0=full bounce)."
                    ),
                    ComponentFieldDefinition(
                        "surface_type", "enum", False, '"Default"',
                        "SurfaceType: Default|Grass|Metal|Wood|Stone|Sand|Ice|Water"
                    ),
                    ComponentFieldDefinition(
                        "audio_material", "str", False, '"default"',
                        "Audio material ID for footstep and impact sounds."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=142,
                type_name="COMP_BUOYANCY_V1",
                layer=ComponentLayer.DCL,
                domain="physics",
                version=1,
                description=(
                    "Buoyancy simulation for water environments. "
                    "Works with EnvironmentComponent water volumes."
                ),
                fields=[
                    ComponentFieldDefinition(
                        "density", "f32", False, "0.5",
                        "Object density relative to water (< 1.0 floats, > 1.0 sinks)."
                    ),
                    ComponentFieldDefinition(
                        "submerged_ratio", "f32", False, "0.0",
                        "Current ratio submerged (0.0=surface, 1.0=fully under). "
                        "Written back by engine feedback."
                    ),
                    ComponentFieldDefinition(
                        "buoyancy_force", "f32", False, "9.81",
                        "Upward force applied when submerged."
                    ),
                    ComponentFieldDefinition(
                        "water_drag", "f32", False, "0.8",
                        "Additional drag when in water."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=143,
                type_name="COMP_SOFT_BODY_V1",
                layer=ComponentLayer.DCL,
                domain="physics",
                version=1,
                description=(
                    "Soft body physics simulation — cloth, jelly, deformable objects. "
                    "Engine handles actual soft body computation."
                ),
                fields=[
                    ComponentFieldDefinition(
                        "stiffness", "f32", False, "0.5",
                        "Shape stiffness (0.0=very soft, 1.0=rigid)."
                    ),
                    ComponentFieldDefinition(
                        "damping", "f32", False, "0.1",
                        "Oscillation damping coefficient."
                    ),
                    ComponentFieldDefinition(
                        "mass_per_node", "f32", False, "0.1",
                        "Mass of each simulation node in kg."
                    ),
                    ComponentFieldDefinition(
                        "is_active", "bool", False, "true",
                        "Whether soft body simulation is enabled."
                    ),
                ],
            ),
        ],
    )