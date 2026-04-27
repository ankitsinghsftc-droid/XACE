"""
DCL Stealth Domain — packages/dcl/stealth/__init__.py

Provides stealth gameplay components:
- COMP_STEALTH_V1    (type_id=180)
- COMP_DISGUISE_V1   (type_id=181)
- COMP_DETECTION_V1  (type_id=182)

Type ID block: 180-199 (stealth reserved range)
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
        domain_name="stealth",
        display_name="Stealth Domain",
        domain_version=1,
        description="Stealth gameplay — visibility levels, disguises, detection meters.",
        dependencies=["ai"],
        components=[
            ComponentDefinition(
                type_id=180,
                type_name="COMP_STEALTH_V1",
                layer=ComponentLayer.DCL,
                domain="stealth",
                version=1,
                description="Stealth state for player or NPC — visibility and noise level.",
                fields=[
                    ComponentFieldDefinition(
                        "visibility_level", "f32", False, "1.0",
                        "How visible this entity is (0.0=invisible, 1.0=fully visible). "
                        "Affected by light, cover, movement speed."
                    ),
                    ComponentFieldDefinition(
                        "noise_level", "f32", False, "0.0",
                        "Current noise emission level (0.0=silent, 1.0=max noise)."
                    ),
                    ComponentFieldDefinition(
                        "is_crouching", "bool", False, "false",
                        "True when in crouch stance — reduces visibility and noise."
                    ),
                    ComponentFieldDefinition(
                        "in_shadow", "bool", False, "false",
                        "True when entity is in a shadow zone. "
                        "Written by LightingSystem or engine feedback."
                    ),
                    ComponentFieldDefinition(
                        "last_seen_tick", "u64", False, "0",
                        "Tick when this entity was last spotted by an AI."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=181,
                type_name="COMP_DISGUISE_V1",
                layer=ComponentLayer.DCL,
                domain="stealth",
                version=1,
                description="Disguise state — allows player to pass as another faction.",
                fields=[
                    ComponentFieldDefinition(
                        "active_disguise_id", "str", False, '""',
                        "ID of the currently worn disguise. Empty = no disguise."
                    ),
                    ComponentFieldDefinition(
                        "disguise_faction", "str", False, '""',
                        "Faction the disguise represents."
                    ),
                    ComponentFieldDefinition(
                        "suspicion_level", "f32", False, "0.0",
                        "Current suspicion (0.0=trusted, 1.0=blown cover)."
                    ),
                    ComponentFieldDefinition(
                        "suspicion_decay_rate", "f32", False, "0.01",
                        "Suspicion reduction per tick when not acting suspiciously."
                    ),
                    ComponentFieldDefinition(
                        "is_blown", "bool", False, "false",
                        "True when disguise has been completely exposed."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=182,
                type_name="COMP_DETECTION_V1",
                layer=ComponentLayer.DCL,
                domain="stealth",
                version=1,
                description=(
                    "Detection meter for AI entities — tracks how close they are "
                    "to fully detecting a stealthy target."
                ),
                fields=[
                    ComponentFieldDefinition(
                        "detection_progress", "f32", False, "0.0",
                        "Detection meter (0.0=unaware, 1.0=fully alerted)."
                    ),
                    ComponentFieldDefinition(
                        "detection_rate", "f32", False, "0.1",
                        "How fast detection increases per tick when target visible."
                    ),
                    ComponentFieldDefinition(
                        "decay_rate", "f32", False, "0.05",
                        "How fast detection decreases per tick when target not visible."
                    ),
                    ComponentFieldDefinition(
                        "alert_threshold", "f32", False, "0.8",
                        "Detection level that triggers alert state."
                    ),
                    ComponentFieldDefinition(
                        "suspected_entity_id", "u64", False, "0",
                        "Entity currently being detected."
                    ),
                    ComponentFieldDefinition(
                        "alert_state", "enum", False, '"Unaware"',
                        "AlertState: Unaware|Suspicious|Alert|Combat"
                    ),
                ],
            ),
        ],
    )