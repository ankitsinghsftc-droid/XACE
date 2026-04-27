"""
DCL Interaction Domain — packages/dcl/interaction/__init__.py

Provides player-world interaction components:
- COMP_INTERACTION_V1 (type_id=260)
- COMP_DIALOGUE_V1    (type_id=261)
- COMP_PUZZLE_V1      (type_id=262)
- COMP_USABLE_V1      (type_id=263)

Type ID block: 260-279 (interaction reserved range)
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
        domain_name="interaction",
        display_name="Interaction Domain",
        domain_version=1,
        description="Player-world interaction — interactables, dialogue, puzzles, usable objects.",
        dependencies=[],
        components=[
            ComponentDefinition(
                type_id=260,
                type_name="COMP_INTERACTION_V1",
                layer=ComponentLayer.DCL,
                domain="interaction",
                version=1,
                description="Makes an entity interactable — shows prompt and handles interaction events.",
                fields=[
                    ComponentFieldDefinition(
                        "interaction_type", "enum", True, None,
                        "InteractionType: Examine|PickUp|Talk|Use|Open|Activate|Custom"
                    ),
                    ComponentFieldDefinition(
                        "range", "f32", False, "2.0",
                        "Maximum interaction range in world units."
                    ),
                    ComponentFieldDefinition(
                        "is_interactable", "bool", False, "true",
                        "Whether interaction is currently possible."
                    ),
                    ComponentFieldDefinition(
                        "required_tag", "str", False, '""',
                        "Interacting entity must have this tag. Empty = any entity."
                    ),
                    ComponentFieldDefinition(
                        "prompt_text", "str", False, '""',
                        "UI prompt shown when in range. e.g. 'Press E to open'"
                    ),
                    ComponentFieldDefinition(
                        "interaction_count", "u32", False, "0",
                        "Number of times this entity has been interacted with."
                    ),
                    ComponentFieldDefinition(
                        "max_interactions", "u32", False, "0",
                        "Maximum interactions allowed. 0 = unlimited."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=261,
                type_name="COMP_DIALOGUE_V1",
                layer=ComponentLayer.DCL,
                domain="interaction",
                version=1,
                description="Dialogue tree state for NPCs and interactive objects.",
                fields=[
                    ComponentFieldDefinition(
                        "dialogue_tree_id", "str", True, None,
                        "ID of the dialogue tree asset to use."
                    ),
                    ComponentFieldDefinition(
                        "current_node_id", "str", False, '"root"',
                        "Current node in the dialogue tree."
                    ),
                    ComponentFieldDefinition(
                        "is_active", "bool", False, "false",
                        "True while dialogue is currently active."
                    ),
                    ComponentFieldDefinition(
                        "interacting_entity_id", "u64", False, "0",
                        "Entity currently in dialogue with this NPC."
                    ),
                    ComponentFieldDefinition(
                        "completed_node_ids", "list", False, "[]",
                        "List of node IDs the player has visited."
                    ),
                    ComponentFieldDefinition(
                        "variables", "dict", False, "{}",
                        "Dict[str, str] dialogue variables for conditional branches."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=262,
                type_name="COMP_PUZZLE_V1",
                layer=ComponentLayer.DCL,
                domain="interaction",
                version=1,
                description="Puzzle state tracker — tracks completion and element states.",
                fields=[
                    ComponentFieldDefinition(
                        "puzzle_id", "str", True, None,
                        "Unique puzzle identifier."
                    ),
                    ComponentFieldDefinition(
                        "is_solved", "bool", False, "false",
                        "True when the puzzle has been completed."
                    ),
                    ComponentFieldDefinition(
                        "element_states", "dict", False, "{}",
                        "Dict[element_id, state_value] — current state of each element."
                    ),
                    ComponentFieldDefinition(
                        "solution", "dict", False, "{}",
                        "Dict[element_id, required_value] — target state for solved."
                    ),
                    ComponentFieldDefinition(
                        "attempts", "u32", False, "0",
                        "Number of solve attempts."
                    ),
                    ComponentFieldDefinition(
                        "solved_tick", "u64", False, "0",
                        "Tick on which puzzle was solved."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=263,
                type_name="COMP_USABLE_V1",
                layer=ComponentLayer.DCL,
                domain="interaction",
                version=1,
                description="A usable item or object with charges and cooldown.",
                fields=[
                    ComponentFieldDefinition(
                        "use_action", "str", True, None,
                        "Action name emitted as event when used."
                    ),
                    ComponentFieldDefinition(
                        "charges", "i32", False, "-1",
                        "Remaining uses. -1 = unlimited."
                    ),
                    ComponentFieldDefinition(
                        "cooldown_ticks", "u64", False, "0",
                        "Ticks between uses."
                    ),
                    ComponentFieldDefinition(
                        "cooldown_remaining", "u64", False, "0",
                        "Ticks until next use is available."
                    ),
                    ComponentFieldDefinition(
                        "is_usable", "bool", False, "true",
                        "Whether this object can currently be used."
                    ),
                ],
            ),
        ],
    )