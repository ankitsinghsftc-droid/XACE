"""
DCL Persistence Domain — packages/dcl/persistence/__init__.py

Provides save/load persistence components (Audit 7):
- COMP_SAVE_SLOT_V1      (type_id=360)
- COMP_CHECKPOINT_V1     (type_id=361)
- COMP_PLAYER_PROFILE_V1 (type_id=362)
- COMP_CLOUD_SYNC_V1     (type_id=363)

Type ID block: 360-379 (persistence reserved range)
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
        domain_name="persistence",
        display_name="Persistence Domain",
        domain_version=1,
        description="Save/load persistence — save slots, checkpoints, player profiles, cloud sync (Audit 7).",
        dependencies=[],
        components=[
            ComponentDefinition(
                type_id=360,
                type_name="COMP_SAVE_SLOT_V1",
                layer=ComponentLayer.DCL,
                domain="persistence",
                version=1,
                description="Save slot metadata — tracks schema version for migration (Audit 7).",
                fields=[
                    ComponentFieldDefinition(
                        "slot_id", "str", True, None,
                        "Unique save slot identifier."
                    ),
                    ComponentFieldDefinition(
                        "display_name", "str", False, '"Save 1"',
                        "Human-readable slot name."
                    ),
                    ComponentFieldDefinition(
                        "schema_version", "str", True, None,
                        "CGS schema version this save was created on. "
                        "Used by SaveEngine for migration."
                    ),
                    ComponentFieldDefinition(
                        "last_saved_tick", "u64", False, "0",
                        "Simulation tick of last save."
                    ),
                    ComponentFieldDefinition(
                        "playtime_ticks", "u64", False, "0",
                        "Total playtime in ticks."
                    ),
                    ComponentFieldDefinition(
                        "is_autosave", "bool", False, "false",
                        "True if this was created by auto-save."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=361,
                type_name="COMP_CHECKPOINT_V1",
                layer=ComponentLayer.DCL,
                domain="persistence",
                version=1,
                description="Checkpoint — respawn point and save trigger.",
                fields=[
                    ComponentFieldDefinition(
                        "checkpoint_type", "enum", False, '"Manual"',
                        "CheckpointType: Manual|Auto|Story|Respawn"
                    ),
                    ComponentFieldDefinition(
                        "is_activated", "bool", False, "false",
                        "True once the player has activated this checkpoint."
                    ),
                    ComponentFieldDefinition(
                        "activation_tick", "u64", False, "0",
                        "Tick when checkpoint was activated."
                    ),
                    ComponentFieldDefinition(
                        "respawn_offset", "struct", False, None,
                        "Vec3 offset from checkpoint for respawn position."
                    ),
                    ComponentFieldDefinition(
                        "triggers_autosave", "bool", False, "true",
                        "Whether activating this checkpoint triggers auto-save."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=362,
                type_name="COMP_PLAYER_PROFILE_V1",
                layer=ComponentLayer.DCL,
                domain="persistence",
                version=1,
                description="Cross-session player profile — persists across game restarts.",
                fields=[
                    ComponentFieldDefinition(
                        "profile_id", "str", True, None,
                        "Unique player profile identifier."
                    ),
                    ComponentFieldDefinition(
                        "display_name", "str", False, '"Player"',
                        "Player display name."
                    ),
                    ComponentFieldDefinition(
                        "total_playtime_ticks", "u64", False, "0",
                        "Total lifetime playtime across all sessions."
                    ),
                    ComponentFieldDefinition(
                        "achievements", "list", False, "[]",
                        "List of earned achievement IDs."
                    ),
                    ComponentFieldDefinition(
                        "settings", "dict", False, "{}",
                        "Dict[str, str] player preference settings."
                    ),
                    ComponentFieldDefinition(
                        "last_played_slot_id", "str", False, '""',
                        "Save slot ID of the most recently played session."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=363,
                type_name="COMP_CLOUD_SYNC_V1",
                layer=ComponentLayer.DCL,
                domain="persistence",
                version=1,
                description="Cloud save sync state for cross-platform persistence (Audit 7).",
                fields=[
                    ComponentFieldDefinition(
                        "provider", "enum", False, '"None"',
                        "CloudProvider: Steam|Epic|PSN|Xbox|Custom|None"
                    ),
                    ComponentFieldDefinition(
                        "sync_state", "enum", False, '"Idle"',
                        "SyncState: Idle|Uploading|Downloading|Conflict|Error|Synced"
                    ),
                    ComponentFieldDefinition(
                        "last_sync_tick", "u64", False, "0",
                        "Tick of last successful cloud sync."
                    ),
                    ComponentFieldDefinition(
                        "conflict_resolution", "enum", False, '"Ask"',
                        "ConflictResolution: LocalWins|CloudWins|Ask"
                    ),
                    ComponentFieldDefinition(
                        "auto_sync", "bool", False, "true",
                        "Whether to automatically sync on save."
                    ),
                ],
            ),
        ],
    )