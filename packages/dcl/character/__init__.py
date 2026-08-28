"""
DCL Character Domain — packages/dcl/character/__init__.py

Provides character movement and animation components:
- COMP_MOVEMENT_INTENT_V1 (type_id=120) — directional movement input
- COMP_ANIMATION_V2       (type_id=121) — full animation state machine
- COMP_IK_V1              (type_id=122) — inverse kinematics
- COMP_CARRY_V1           (type_id=123) — object carrying state
- COMP_RAGDOLL_V1         (type_id=124) — ragdoll physics state

- COMP_KINEMATIC_CHARACTER_V1 (type_id=125) - deterministic jump/fall state

Type ID block: 120-139 (character reserved range)
Audit 3: COMP_ANIMATION_V2 full spec with layers, pending_events, feedback fields.
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
        domain_name="character",
        display_name="Character Domain",
        domain_version=1,
        description=(
            "Character movement, animation, IK, carrying, and ragdoll. "
            "Audit 3: COMP_ANIMATION_V2 with full layer and event support."
        ),
        dependencies=[],
        components=[
            ComponentDefinition(
                type_id=120,
                type_name="COMP_MOVEMENT_INTENT_V1",
                layer=ComponentLayer.DCL,
                domain="character",
                version=1,
                description=(
                    "Desired movement direction and action flags for this tick. "
                    "Written by InputSystem or AISystem. "
                    "Read by MovementSystem to update COMP_VELOCITY_V1."
                ),
                fields=[
                    ComponentFieldDefinition(
                        "direction", "struct", False, None,
                        "Normalized Vec3 movement direction. "
                        "Zero vector means no movement requested."
                    ),
                    ComponentFieldDefinition(
                        "direction_x", "i64", False, "0",
                        "Deterministic X direction in Fixed64 raw micro-units."
                    ),
                    ComponentFieldDefinition(
                        "direction_y", "i64", False, "0",
                        "Deterministic Y direction in Fixed64 raw micro-units."
                    ),
                    ComponentFieldDefinition(
                        "direction_z", "i64", False, "0",
                        "Deterministic Z direction in Fixed64 raw micro-units."
                    ),
                    ComponentFieldDefinition(
                        "sprint_requested", "bool", False, "false",
                        "True if the sprint action is held this tick."
                    ),
                    ComponentFieldDefinition(
                        "jump_requested", "bool", False, "false",
                        "True if the jump action was pressed this tick."
                    ),
                    ComponentFieldDefinition(
                        "jump_held", "bool", False, "false",
                        "Current jump hold state used for deterministic edge detection."
                    ),
                    ComponentFieldDefinition(
                        "crouch_requested", "bool", False, "false",
                        "True if the crouch action is held this tick."
                    ),
                    ComponentFieldDefinition(
                        "look_direction", "struct", False, None,
                        "Vec3 direction the character is looking toward. "
                        "Used for aiming and camera facing."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=121,
                type_name="COMP_ANIMATION_V2",
                layer=ComponentLayer.DCL,
                domain="character",
                version=2,
                description=(
                    "Full animation state machine component. Audit 3 full spec. "
                    "XACE writes intent fields. Engine writes back feedback fields "
                    "via EngineFeedbackProtocol (Audit 6)."
                ),
                fields=[
                    # Intent fields (written by XACE systems)
                    ComponentFieldDefinition(
                        "controller_ref", "asset_reference", True, None,
                        "AssetReference to the AnimationController asset."
                    ),
                    ComponentFieldDefinition(
                        "playback_speed", "f32", False, "1.0",
                        "Global playback speed multiplier. 1.0 = normal."
                    ),
                    ComponentFieldDefinition(
                        "layers", "dict", False, "{}",
                        "Dict[layer_name, LayerState]. Each layer has: "
                        "current_state, weight, mask, additive."
                    ),
                    ComponentFieldDefinition(
                        "parameters", "dict", False, "{}",
                        "Dict[param_name, ParamValue]. Each param has: "
                        "value, type (BOOL|FLOAT|INT|TRIGGER)."
                    ),
                    ComponentFieldDefinition(
                        "blend_parameters", "dict", False, "{}",
                        "Dict[tree_name, BlendTree]. Each tree has: "
                        "x_parameter, y_parameter, blend_type."
                    ),
                    ComponentFieldDefinition(
                        "pending_events", "list", False, "[]",
                        "List of AnimationEvents to fire at normalized time. "
                        "Each event: event_id, state_name, "
                        "trigger_at_normalized_time, game_event_type, "
                        "payload, is_consumed."
                    ),
                    ComponentFieldDefinition(
                        "ik_enabled", "bool", False, "false",
                        "Whether IK solving is active for this entity."
                    ),
                    # Feedback fields (written back by engine via FeedbackProtocol)
                    ComponentFieldDefinition(
                        "current_normalized_time", "f32", False, "0.0",
                        "Current playback position (0.0-1.0). "
                        "Written back by engine via ANIMATION_STATE_UPDATE feedback."
                    ),
                    ComponentFieldDefinition(
                        "is_transitioning", "bool", False, "false",
                        "True while transitioning between states. "
                        "Written back by engine via ANIMATION_STATE_UPDATE feedback."
                    ),
                    ComponentFieldDefinition(
                        "active_state_per_layer", "dict", False, "{}",
                        "Dict[layer_name, state_name]. Current active state per layer. "
                        "Written back by engine via ANIMATION_STATE_UPDATE feedback."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=122,
                type_name="COMP_IK_V1",
                layer=ComponentLayer.DCL,
                domain="character",
                version=1,
                description=(
                    "Inverse kinematics configuration. Audit 3 full spec. "
                    "Controls look-at, hand placement, foot placement, and carry IK."
                ),
                fields=[
                    ComponentFieldDefinition(
                        "ik_mode", "enum", False, '"DISABLED"',
                        "IKMode: DISABLED|LOOK_AT|HANDS|FEET|"
                        "HANDS_AND_FEET|FULL_BODY"
                    ),
                    ComponentFieldDefinition(
                        "look_at_target_entity", "u64", False, "0",
                        "Entity to look at. 0 = no look-at target."
                    ),
                    ComponentFieldDefinition(
                        "look_at_weight", "f32", False, "1.0",
                        "Blend weight for look-at IK (0.0-1.0)."
                    ),
                    ComponentFieldDefinition(
                        "look_at_clamp_degrees", "f32", False, "90.0",
                        "Maximum head rotation angle in degrees."
                    ),
                    ComponentFieldDefinition(
                        "left_hand_target_entity", "u64", False, "0",
                        "Entity for left hand IK target."
                    ),
                    ComponentFieldDefinition(
                        "left_hand_target_offset", "struct", False, None,
                        "Vec3 offset from left hand target entity."
                    ),
                    ComponentFieldDefinition(
                        "left_hand_weight", "f32", False, "1.0",
                        "Blend weight for left hand IK."
                    ),
                    ComponentFieldDefinition(
                        "right_hand_target_entity", "u64", False, "0",
                        "Entity for right hand IK target."
                    ),
                    ComponentFieldDefinition(
                        "right_hand_target_offset", "struct", False, None,
                        "Vec3 offset from right hand target entity."
                    ),
                    ComponentFieldDefinition(
                        "right_hand_weight", "f32", False, "1.0",
                        "Blend weight for right hand IK."
                    ),
                    ComponentFieldDefinition(
                        "foot_placement_enabled", "bool", False, "false",
                        "Whether foot IK places feet on uneven terrain."
                    ),
                    ComponentFieldDefinition(
                        "foot_placement_weight", "f32", False, "1.0",
                        "Blend weight for foot placement IK."
                    ),
                    ComponentFieldDefinition(
                        "carry_ik_preset", "enum", False, '"NONE"',
                        "CarryIKPreset: NONE|DRAG_BY_FEET|"
                        "CARRY_OVER_SHOULDER|FIREMAN_CARRY|TWO_HAND_CARRY"
                    ),
                    ComponentFieldDefinition(
                        "solve_order", "enum", False, '"FABRIK"',
                        "IK solver algorithm: FABRIK|CCD|TWO_BONE"
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=123,
                type_name="COMP_CARRY_V1",
                layer=ComponentLayer.DCL,
                domain="character",
                version=1,
                description=(
                    "Object carrying state. Tracks what entity this character "
                    "is currently carrying and how."
                ),
                fields=[
                    ComponentFieldDefinition(
                        "carried_entity_id", "u64", False, "0",
                        "Entity currently being carried. 0 = carrying nothing."
                    ),
                    ComponentFieldDefinition(
                        "carry_mode", "enum", False, '"NONE"',
                        "CarryMode: NONE|ONE_HAND|TWO_HAND|ON_BACK|DRAG"
                    ),
                    ComponentFieldDefinition(
                        "attach_offset", "struct", False, None,
                        "Vec3 offset from carrier's root for carried entity position."
                    ),
                    ComponentFieldDefinition(
                        "max_carry_distance", "f32", False, "2.0",
                        "Maximum distance at which carry interaction is possible."
                    ),
                    ComponentFieldDefinition(
                        "carry_weight_limit", "f32", False, "100.0",
                        "Maximum carry weight in arbitrary units."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=124,
                type_name="COMP_RAGDOLL_V1",
                layer=ComponentLayer.DCL,
                domain="character",
                version=1,
                description=(
                    "Ragdoll physics state. When active, the engine takes "
                    "over physical simulation. XACE receives final position "
                    "via PHYSICS_SETTLED feedback."
                ),
                fields=[
                    ComponentFieldDefinition(
                        "is_active", "bool", False, "false",
                        "True when ragdoll physics is active."
                    ),
                    ComponentFieldDefinition(
                        "blend_weight", "f32", False, "0.0",
                        "Blend from animation (0.0) to full ragdoll (1.0)."
                    ),
                    ComponentFieldDefinition(
                        "initial_velocity", "struct", False, None,
                        "Vec3 impulse applied when ragdoll activates."
                    ),
                    ComponentFieldDefinition(
                        "settled", "bool", False, "false",
                        "True when PHYSICS_SETTLED feedback received."
                    ),
                    ComponentFieldDefinition(
                        "settled_tick", "u64", False, "0",
                        "Tick on which ragdoll settled."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=125,
                type_name="COMP_KINEMATIC_CHARACTER_V1",
                layer=ComponentLayer.DCL,
                domain="character",
                version=1,
                description=(
                    "Deterministic kinematic character configuration and jump/fall state. "
                    "Grounded feedback may be supplied by an engine adapter."
                ),
                fields=[
                    ComponentFieldDefinition("grounded", "bool", False, "true", "Current grounded state."),
                    ComponentFieldDefinition("was_grounded", "bool", False, "true", "Grounded state observed on the prior tick."),
                    ComponentFieldDefinition("max_horizontal_speed", "i64", False, "6000000", "Fixed64 raw horizontal speed limit."),
                    ComponentFieldDefinition("jump_impulse", "i64", False, "12000000", "Fixed64 raw upward jump velocity."),
                    ComponentFieldDefinition("gravity_per_tick", "i64", False, "500000", "Fixed64 raw velocity subtracted per airborne tick."),
                    ComponentFieldDefinition("terminal_fall_speed", "i64", False, "30000000", "Fixed64 raw downward speed cap magnitude."),
                    ComponentFieldDefinition("coyote_ticks", "u32", False, "6", "Configured post-ground jump grace ticks."),
                    ComponentFieldDefinition("coyote_ticks_remaining", "u32", False, "6", "Remaining post-ground jump grace ticks."),
                    ComponentFieldDefinition("jump_buffer_ticks", "u32", False, "6", "Configured pre-ground jump buffer ticks."),
                    ComponentFieldDefinition("jump_buffer_ticks_remaining", "u32", False, "0", "Remaining buffered jump ticks."),
                    ComponentFieldDefinition("max_jumps", "u32", False, "1", "Maximum jumps before touching ground."),
                    ComponentFieldDefinition("jumps_used", "u32", False, "0", "Jumps consumed since touching ground."),
                ],
            ),
        ],
    )
