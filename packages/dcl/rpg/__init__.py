"""
DCL RPG Domain — packages/dcl/rpg/__init__.py

Provides RPG progression components:
- COMP_STATS_V1       (type_id=200)
- COMP_INVENTORY_V1   (type_id=201)
- COMP_ABILITY_V1     (type_id=202)
- COMP_PROGRESSION_V1 (type_id=203)
- COMP_ECONOMY_V1     (type_id=204)

Type ID block: 200-229 (rpg reserved range)
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
        domain_name="rpg",
        display_name="RPG Domain",
        domain_version=1,
        description="RPG systems — stats, inventory, abilities, progression, economy.",
        dependencies=[],
        components=[
            ComponentDefinition(
                type_id=200,
                type_name="COMP_STATS_V1",
                layer=ComponentLayer.DCL,
                domain="rpg",
                version=1,
                description="Numeric stats with base values, current values, and modifiers.",
                fields=[
                    ComponentFieldDefinition(
                        "base_values", "dict", True, None,
                        "Dict[stat_name, f32] base stat values before modifiers. "
                        "Examples: {speed: 5.0, strength: 10.0, defense: 3.0}"
                    ),
                    ComponentFieldDefinition(
                        "current_values", "dict", True, None,
                        "Dict[stat_name, f32] current values after modifiers applied."
                    ),
                    ComponentFieldDefinition(
                        "modifiers", "list", False, "[]",
                        "List of StatModifier: {stat_name, value, operation, source_id, duration_ticks}"
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=201,
                type_name="COMP_INVENTORY_V1",
                layer=ComponentLayer.DCL,
                domain="rpg",
                version=1,
                description="Item inventory with slots, capacity, and equipped item tracking.",
                fields=[
                    ComponentFieldDefinition(
                        "slots", "list", False, "[]",
                        "List of InventorySlot: {slot_id, item_id, quantity, is_equipped}"
                    ),
                    ComponentFieldDefinition(
                        "max_capacity", "u32", False, "20",
                        "Maximum number of item stacks this inventory can hold."
                    ),
                    ComponentFieldDefinition(
                        "current_count", "u32", False, "0",
                        "Current number of occupied slots."
                    ),
                    ComponentFieldDefinition(
                        "equipped_slot_id", "str", False, '""',
                        "ID of the currently equipped/active slot."
                    ),
                    ComponentFieldDefinition(
                        "weight_current", "f32", False, "0.0",
                        "Current total carry weight."
                    ),
                    ComponentFieldDefinition(
                        "weight_max", "f32", False, "100.0",
                        "Maximum carry weight. 0.0 = unlimited."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=202,
                type_name="COMP_ABILITY_V1",
                layer=ComponentLayer.DCL,
                domain="rpg",
                version=1,
                description="An active ability with cooldown, cost, and activation state.",
                fields=[
                    ComponentFieldDefinition(
                        "ability_id", "str", True, None,
                        "Unique ID matching the ability defined in the CGS."
                    ),
                    ComponentFieldDefinition(
                        "is_unlocked", "bool", False, "true",
                        "Whether this ability has been unlocked."
                    ),
                    ComponentFieldDefinition(
                        "cooldown_ticks", "u64", False, "0",
                        "Total cooldown duration in ticks."
                    ),
                    ComponentFieldDefinition(
                        "cooldown_remaining", "u64", False, "0",
                        "Ticks remaining before ability can be used again."
                    ),
                    ComponentFieldDefinition(
                        "resource_cost", "f32", False, "0.0",
                        "Resource cost to activate (mana, stamina, etc.)."
                    ),
                    ComponentFieldDefinition(
                        "is_active", "bool", False, "false",
                        "True while the ability effect is ongoing."
                    ),
                    ComponentFieldDefinition(
                        "activation_tick", "u64", False, "0",
                        "Tick on which ability was last activated."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=203,
                type_name="COMP_PROGRESSION_V1",
                layer=ComponentLayer.DCL,
                domain="rpg",
                version=1,
                description="Experience, leveling, and skill point progression.",
                fields=[
                    ComponentFieldDefinition(
                        "level", "u32", False, "1",
                        "Current character level."
                    ),
                    ComponentFieldDefinition(
                        "experience", "f64", False, "0.0",
                        "Current experience points."
                    ),
                    ComponentFieldDefinition(
                        "experience_to_next", "f64", False, "100.0",
                        "Experience required for next level."
                    ),
                    ComponentFieldDefinition(
                        "skill_points", "u32", False, "0",
                        "Unspent skill points available for allocation."
                    ),
                    ComponentFieldDefinition(
                        "max_level", "u32", False, "100",
                        "Maximum achievable level. 0 = no cap."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=204,
                type_name="COMP_ECONOMY_V1",
                layer=ComponentLayer.DCL,
                domain="rpg",
                version=1,
                description="Currency and economic state for trading and purchasing.",
                fields=[
                    ComponentFieldDefinition(
                        "currencies", "dict", False, "{}",
                        "Dict[currency_id, f64] current amounts. "
                        "Examples: {gold: 150.0, gems: 5.0}"
                    ),
                    ComponentFieldDefinition(
                        "transaction_history", "list", False, "[]",
                        "Recent transactions for audit trail. "
                        "Each: {currency_id, delta, reason, tick}"
                    ),
                ],
            ),
        ],
    )