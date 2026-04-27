"""
DCL AI Domain — packages/dcl/ai/__init__.py

Provides AI behavior components:
- COMP_AI_V1           (type_id=160) — core AI behavior state
- COMP_PATROL_V1       (type_id=161) — patrol waypoint following
- COMP_PERCEPTION_V1   (type_id=162) — detection and visibility queries
- COMP_CROWD_AGENT_V1  (type_id=163) — crowd simulation LOD

Type ID block: 160-179 (ai reserved range)
Audit 6: COMP_PERCEPTION_V1 includes visibility_query_pending flag.
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
        domain_name="ai",
        display_name="AI Domain",
        domain_version=1,
        description="AI behavior — core AI, patrol, perception, crowd simulation.",
        dependencies=[],
        components=[
            ComponentDefinition(
                type_id=160,
                type_name="COMP_AI_V1",
                layer=ComponentLayer.DCL,
                domain="ai",
                version=1,
                description="Core AI behavior state machine.",
                fields=[
                    ComponentFieldDefinition(
                        "behavior_model", "enum", True, None,
                        "AIBehaviorModel: Idle|Patrol|Chase|Attack|Flee|Custom"
                    ),
                    ComponentFieldDefinition(
                        "current_state", "str", False, '"Idle"',
                        "Current named AI state within the behavior model."
                    ),
                    ComponentFieldDefinition(
                        "target_entity_id", "u64", False, "0",
                        "Current target entity. 0 = no target."
                    ),
                    ComponentFieldDefinition(
                        "detection_radius", "f32", False, "10.0",
                        "Radius within which this AI detects other entities."
                    ),
                    ComponentFieldDefinition(
                        "aggression_level", "f32", False, "0.5",
                        "Aggression (0.0=passive, 1.0=always attacks)."
                    ),
                    ComponentFieldDefinition(
                        "memory", "dict", False, "{}",
                        "Dict[str, str] AI working memory — "
                        "stores last known positions, timestamps, etc."
                    ),
                    ComponentFieldDefinition(
                        "home_position", "struct", False, None,
                        "Vec3 position this AI considers its home/spawn point."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=161,
                type_name="COMP_PATROL_V1",
                layer=ComponentLayer.DCL,
                domain="ai",
                version=1,
                description="Waypoint patrol behavior for AI entities.",
                fields=[
                    ComponentFieldDefinition(
                        "waypoints", "list", True, None,
                        "List of Vec3 waypoint positions to patrol between."
                    ),
                    ComponentFieldDefinition(
                        "current_waypoint_index", "u32", False, "0",
                        "Index into waypoints of current destination."
                    ),
                    ComponentFieldDefinition(
                        "patrol_mode", "enum", False, '"Loop"',
                        "PatrolMode: Loop|PingPong|OneShot"
                    ),
                    ComponentFieldDefinition(
                        "wait_ticks_at_waypoint", "u64", False, "60",
                        "Ticks to wait at each waypoint before moving."
                    ),
                    ComponentFieldDefinition(
                        "wait_ticks_remaining", "u64", False, "0",
                        "Countdown ticks remaining at current waypoint."
                    ),
                    ComponentFieldDefinition(
                        "move_speed", "f32", False, "3.0",
                        "Movement speed during patrol in units per second."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=162,
                type_name="COMP_PERCEPTION_V1",
                layer=ComponentLayer.DCL,
                domain="ai",
                version=1,
                description=(
                    "Sensory perception for AI entities. "
                    "Audit 6: includes visibility_query_pending flag for "
                    "engine raycast queries via FeedbackProtocol."
                ),
                fields=[
                    ComponentFieldDefinition(
                        "sight_range", "f32", False, "15.0",
                        "Maximum sight range in world units."
                    ),
                    ComponentFieldDefinition(
                        "sight_angle_degrees", "f32", False, "120.0",
                        "Field of view cone angle in degrees."
                    ),
                    ComponentFieldDefinition(
                        "hearing_range", "f32", False, "8.0",
                        "Range at which sounds are detected."
                    ),
                    ComponentFieldDefinition(
                        "can_see_target", "bool", False, "false",
                        "True if last visibility query confirmed line of sight. "
                        "Written by visibility_feedback_handler."
                    ),
                    ComponentFieldDefinition(
                        "last_known_target_position", "struct", False, None,
                        "Vec3 last confirmed position of target entity."
                    ),
                    ComponentFieldDefinition(
                        "visibility_query_pending", "bool", False, "false",
                        "Audit 6: Set true by AISystem to request a raycast. "
                        "VisibilityQueryBatcher reads this each tick and sends "
                        "batch to engine. Result returns next tick as feedback."
                    ),
                    ComponentFieldDefinition(
                        "visibility_query_target_entity", "u64", False, "0",
                        "Target entity for the pending visibility query."
                    ),
                    ComponentFieldDefinition(
                        "last_visibility_result_tick", "u64", False, "0",
                        "Tick of the most recent visibility query result."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=163,
                type_name="COMP_CROWD_AGENT_V1",
                layer=ComponentLayer.DCL,
                domain="ai",
                version=1,
                description=(
                    "Lightweight crowd simulation agent. "
                    "Uses Logic LOD — full AI only within active radius, "
                    "simplified crowd behavior beyond it."
                ),
                fields=[
                    ComponentFieldDefinition(
                        "crowd_group_id", "str", False, '"default"',
                        "Which crowd group this agent belongs to."
                    ),
                    ComponentFieldDefinition(
                        "lod_level", "enum", False, '"Full"',
                        "LODLevel: Full|Reduced|Minimal|Inactive. "
                        "Set by LOD system based on distance from player."
                    ),
                    ComponentFieldDefinition(
                        "separation_radius", "f32", False, "1.0",
                        "Personal space radius for crowd avoidance."
                    ),
                    ComponentFieldDefinition(
                        "max_speed", "f32", False, "4.0",
                        "Maximum crowd movement speed."
                    ),
                    ComponentFieldDefinition(
                        "destination", "struct", False, None,
                        "Vec3 crowd destination position."
                    ),
                ],
            ),
        ],
    )