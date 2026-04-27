"""
DCL UI Domain — packages/dcl/ui/__init__.py

Provides UI binding components:
- COMP_UI_ELEMENT_V1  (type_id=340)
- COMP_HUD_BINDING_V1 (type_id=341)
- COMP_MINIMAP_V1     (type_id=342)

Type ID block: 340-359 (ui reserved range)
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
        domain_name="ui",
        display_name="UI Domain",
        domain_version=1,
        description="UI binding — world-space UI elements, HUD data bindings, minimap markers.",
        dependencies=[],
        components=[
            ComponentDefinition(
                type_id=340,
                type_name="COMP_UI_ELEMENT_V1",
                layer=ComponentLayer.DCL,
                domain="ui",
                version=1,
                description="A UI element anchored in world space to an entity.",
                fields=[
                    ComponentFieldDefinition(
                        "element_type", "enum", False, '"Label"',
                        "UIElementType: Label|HealthBar|ProgressBar|Icon|Custom"
                    ),
                    ComponentFieldDefinition(
                        "text", "str", False, '""',
                        "Display text for Label elements."
                    ),
                    ComponentFieldDefinition(
                        "value", "f32", False, "1.0",
                        "Current value for bar elements (0.0-1.0)."
                    ),
                    ComponentFieldDefinition(
                        "world_offset", "struct", False, None,
                        "Vec3 offset above the entity in world space."
                    ),
                    ComponentFieldDefinition(
                        "is_visible", "bool", False, "true",
                        "Whether this UI element is shown."
                    ),
                    ComponentFieldDefinition(
                        "fade_distance", "f32", False, "20.0",
                        "Distance at which element starts to fade out."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=341,
                type_name="COMP_HUD_BINDING_V1",
                layer=ComponentLayer.DCL,
                domain="ui",
                version=1,
                description=(
                    "Binds a component field value to a HUD display element. "
                    "The builder workspace UI reads these to auto-populate HUD."
                ),
                fields=[
                    ComponentFieldDefinition(
                        "hud_element_id", "str", True, None,
                        "ID of the HUD element to bind to."
                    ),
                    ComponentFieldDefinition(
                        "source_component_type_id", "u32", True, None,
                        "Component type ID containing the value to display."
                    ),
                    ComponentFieldDefinition(
                        "source_field_name", "str", True, None,
                        "Field name within the source component."
                    ),
                    ComponentFieldDefinition(
                        "display_format", "str", False, '"{value}"',
                        "Display format string. {value} is replaced with field value."
                    ),
                    ComponentFieldDefinition(
                        "is_active", "bool", False, "true",
                        "Whether this binding is active."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=342,
                type_name="COMP_MINIMAP_V1",
                layer=ComponentLayer.DCL,
                domain="ui",
                version=1,
                description="Minimap marker — shows this entity on the minimap.",
                fields=[
                    ComponentFieldDefinition(
                        "icon_id", "str", False, '"default"',
                        "Minimap icon identifier."
                    ),
                    ComponentFieldDefinition(
                        "color", "str", False, '"#FFFFFF"',
                        "Hex color for the minimap marker."
                    ),
                    ComponentFieldDefinition(
                        "is_visible_on_minimap", "bool", False, "true",
                        "Whether this entity appears on the minimap."
                    ),
                    ComponentFieldDefinition(
                        "show_direction", "bool", False, "false",
                        "Whether to show facing direction arrow on minimap."
                    ),
                    ComponentFieldDefinition(
                        "priority", "u32", False, "0",
                        "Display priority — higher draws on top."
                    ),
                ],
            ),
        ],
    )