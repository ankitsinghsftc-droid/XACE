"""
DCL Network Domain — packages/dcl/network/__init__.py

Provides multiplayer networking components (Phase 15):
- COMP_REPLICATION_V1       (type_id=320)
- COMP_NETWORK_TRANSFORM_V1 (type_id=321)
- COMP_PLAYER_SESSION_V1    (type_id=322)

Type ID block: 320-339 (network reserved range)
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
        domain_name="network",
        display_name="Network Domain",
        domain_version=1,
        description="Multiplayer networking — replication, network transform, player sessions (Phase 15).",
        dependencies=[],
        components=[
            ComponentDefinition(
                type_id=320,
                type_name="COMP_REPLICATION_V1",
                layer=ComponentLayer.DCL,
                domain="network",
                version=1,
                description=(
                    "Fine-grained replication control for a specific component "
                    "on an entity. Extends COMP_AUTHORITY_V1 with per-component control."
                ),
                fields=[
                    ComponentFieldDefinition(
                        "component_type_id", "u32", True, None,
                        "The component type this replication config applies to."
                    ),
                    ComponentFieldDefinition(
                        "replication_mode", "enum", False, '"Unreliable"',
                        "ReplicationMode: Unreliable|Reliable|ServerOnly|None"
                    ),
                    ComponentFieldDefinition(
                        "sync_rate_divisor", "u8", False, "1",
                        "Sync every Nth tick. 1=every tick, 2=every other tick."
                    ),
                    ComponentFieldDefinition(
                        "relevance_radius", "f32", False, "0.0",
                        "Only replicate to peers within this radius. 0.0=all peers."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=321,
                type_name="COMP_NETWORK_TRANSFORM_V1",
                layer=ComponentLayer.DCL,
                domain="network",
                version=1,
                description=(
                    "Network-optimized transform synchronization with "
                    "interpolation and extrapolation for smooth remote entity movement."
                ),
                fields=[
                    ComponentFieldDefinition(
                        "interpolation_mode", "enum", False, '"Linear"',
                        "InterpolationMode: None|Linear|Cubic|Hermite"
                    ),
                    ComponentFieldDefinition(
                        "position_threshold", "f32", False, "0.01",
                        "Minimum position delta to send an update."
                    ),
                    ComponentFieldDefinition(
                        "rotation_threshold", "f32", False, "0.5",
                        "Minimum rotation delta in degrees to send an update."
                    ),
                    ComponentFieldDefinition(
                        "extrapolate", "bool", False, "true",
                        "Whether to extrapolate movement between network updates."
                    ),
                    ComponentFieldDefinition(
                        "snap_threshold", "f32", False, "5.0",
                        "Distance beyond which interpolation snaps instead of blending."
                    ),
                ],
            ),
            ComponentDefinition(
                type_id=322,
                type_name="COMP_PLAYER_SESSION_V1",
                layer=ComponentLayer.DCL,
                domain="network",
                version=1,
                description="Player session data for a connected multiplayer peer.",
                fields=[
                    ComponentFieldDefinition(
                        "peer_id", "str", True, None,
                        "Unique peer identifier for this player."
                    ),
                    ComponentFieldDefinition(
                        "display_name", "str", False, '"Player"',
                        "Player display name shown in UI."
                    ),
                    ComponentFieldDefinition(
                        "connection_state", "enum", False, '"Connecting"',
                        "PeerConnectionState: Connecting|Syncing|Live|Desynced|Disconnected"
                    ),
                    ComponentFieldDefinition(
                        "latency_ms", "u32", False, "0",
                        "Current round-trip latency in milliseconds."
                    ),
                    ComponentFieldDefinition(
                        "ping_tick", "u64", False, "0",
                        "Tick of last ping."
                    ),
                    ComponentFieldDefinition(
                        "is_host", "bool", False, "false",
                        "True if this peer is the session host."
                    ),
                ],
            ),
        ],
    )