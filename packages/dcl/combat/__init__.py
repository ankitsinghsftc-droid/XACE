"""
DCL Combat Domain — packages/dcl/combat/__init__.py

Provides combat-related components:
- COMP_HEALTH_V1    (type_id=100) — entity health tracking
- COMP_DAMAGE_V1    (type_id=101) — damage event carrier
- COMP_HITBOX_V1    (type_id=102) — hit detection volume
- COMP_SHIELD_V1    (type_id=103) — damage absorption layer
- COMP_STATUS_EFFECT_V1 (type_id=104) — timed status conditions

Type ID block: 100-119 (combat reserved range)
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
        domain_name="combat",
        display_name="Combat Domain",
        domain_version=1,
        description=(
            "Combat system components — health, damage, hitboxes, "
            "shields, and status effects."
        ),
        dependencies=[],
        components=[
            ComponentDefinition(
                type_id=100,
                type_name="COMP_HEALTH_V1",
                layer=ComponentLayer.DCL,
                domain="combat",
                version=1,
                description=(
                    "Entity health tracking. Written by DamageSystem, "
                    "read by DeathSystem and UI systems."
                ),
                fields=[
                    ComponentFieldDefinition(
                        "current", "f32", True, None,
                        "Current health points. Never goes below 0."
                    ),
                    ComponentFieldDefinition(
                        "max", "f32", True, None,
                        "Maximum health points. Must be > 0."
                    ),
                    ComponentFieldDefinition(
                        "regen_rate", "f32", False, "0.0",
                        "Health regenerated per tick. 0.0 = no regeneration."
                    ),
                    ComponentFieldDefinition(
                        "is_invincible", "bool", False, "false",
                        "If true, damage is received but health never changes."
                    ),
                    ComponentFieldDefinition(
                        "death_behavior", "enum", False, '"DestroyEntity"',
                        "What happens on death: DestroyEntity|Disable|EmitEvent"
                    ),
                    ComponentFieldDefinition(
                        "last_damage_tick", "u64", False, "0",
                        "Tick on which last damage was received."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=101,
                type_name="COMP_DAMAGE_V1",
                layer=ComponentLayer.DCL,
                domain="combat",
                version=1,
                description=(
                    "Damage event carrier. Attached to projectiles or "
                    "damage zones. Consumed by DamageSystem each tick."
                ),
                fields=[
                    ComponentFieldDefinition(
                        "damage_type", "enum", True, None,
                        "DamageType: Physical|Fire|Ice|Lightning|Poison|True"
                    ),
                    ComponentFieldDefinition(
                        "amount", "f32", True, None,
                        "Damage amount before mitigation. Must be >= 0."
                    ),
                    ComponentFieldDefinition(
                        "source_entity_id", "u64", False, "0",
                        "Entity that caused the damage. 0 = environmental."
                    ),
                    ComponentFieldDefinition(
                        "applied_tick", "u64", False, "0",
                        "Tick on which damage was applied."
                    ),
                    ComponentFieldDefinition(
                        "is_consumed", "bool", False, "false",
                        "True after DamageSystem has processed this damage."
                    ),
                    ComponentFieldDefinition(
                        "can_crit", "bool", False, "true",
                        "Whether this damage instance can critically strike."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=102,
                type_name="COMP_HITBOX_V1",
                layer=ComponentLayer.DCL,
                domain="combat",
                version=1,
                description=(
                    "Hit detection volume separate from physics collider. "
                    "Defines the region that registers damage hits."
                ),
                fields=[
                    ComponentFieldDefinition(
                        "shape", "enum", True, None,
                        "HitboxShape: Box|Sphere|Capsule"
                    ),
                    ComponentFieldDefinition(
                        "size", "struct", True, None,
                        "Hitbox dimensions — same format as ColliderSize"
                    ),
                    ComponentFieldDefinition(
                        "offset", "struct", False, None,
                        "Offset from entity transform origin"
                    ),
                    ComponentFieldDefinition(
                        "damage_multiplier", "f32", False, "1.0",
                        "Damage multiplier for hits on this hitbox. "
                        "Use 2.0 for headshot zones."
                    ),
                    ComponentFieldDefinition(
                        "hitbox_type", "enum", False, '"Body"',
                        "HitboxType: Head|Body|Limb|Weak|Armor"
                    ),
                    ComponentFieldDefinition(
                        "is_active", "bool", False, "true",
                        "Whether this hitbox is currently registering hits."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=103,
                type_name="COMP_SHIELD_V1",
                layer=ComponentLayer.DCL,
                domain="combat",
                version=1,
                description=(
                    "Damage absorption layer that depletes before health. "
                    "Regenerates at a defined rate when not taking damage."
                ),
                fields=[
                    ComponentFieldDefinition(
                        "current", "f32", True, None,
                        "Current shield points."
                    ),
                    ComponentFieldDefinition(
                        "max", "f32", True, None,
                        "Maximum shield points. Must be > 0."
                    ),
                    ComponentFieldDefinition(
                        "regen_rate", "f32", False, "0.0",
                        "Shield points regenerated per tick."
                    ),
                    ComponentFieldDefinition(
                        "regen_delay_ticks", "u64", False, "120",
                        "Ticks after last hit before regeneration starts."
                    ),
                    ComponentFieldDefinition(
                        "absorption_ratio", "f32", False, "1.0",
                        "Fraction of incoming damage absorbed by shield. "
                        "1.0 = full absorption. 0.5 = half to shield, half to health."
                    ),
                    ComponentFieldDefinition(
                        "last_hit_tick", "u64", False, "0",
                        "Tick of last damage hit — used for regen delay."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=104,
                type_name="COMP_STATUS_EFFECT_V1",
                layer=ComponentLayer.DCL,
                domain="combat",
                version=1,
                description=(
                    "A timed status condition applied to an entity. "
                    "Examples: burning, frozen, stunned, poisoned."
                ),
                fields=[
                    ComponentFieldDefinition(
                        "effect_type", "enum", True, None,
                        "StatusEffectType: Burning|Frozen|Stunned|Poisoned|"
                        "Slowed|Buffed|Debuffed|Custom"
                    ),
                    ComponentFieldDefinition(
                        "intensity", "f32", False, "1.0",
                        "Effect intensity multiplier. 1.0 = base effect."
                    ),
                    ComponentFieldDefinition(
                        "duration_ticks", "u64", True, None,
                        "How long the effect lasts in ticks."
                    ),
                    ComponentFieldDefinition(
                        "elapsed_ticks", "u64", False, "0",
                        "Ticks since effect was applied."
                    ),
                    ComponentFieldDefinition(
                        "source_entity_id", "u64", False, "0",
                        "Entity that applied this effect."
                    ),
                    ComponentFieldDefinition(
                        "tick_damage", "f32", False, "0.0",
                        "Damage applied per tick while effect is active. "
                        "0.0 = no tick damage (stun, slow, etc.)"
                    ),
                    ComponentFieldDefinition(
                        "is_consumed", "bool", False, "false",
                        "True when duration has expired."
                    ),
                ],
            ),
        ],
    )