"""DCL Network Domain.

Provides multiplayer component schemas:
- COMP_REPLICATION_V1
- COMP_NETWORK_TRANSFORM_V1
- COMP_PLAYER_SESSION_V1
"""

from __future__ import annotations

from ..domain_package import DomainPackage
from . import network_transform_component, player_session_component, replication_component

__all__ = [
    "get_domain_package",
    "replication_component",
    "network_transform_component",
    "player_session_component",
]


def get_domain_package() -> DomainPackage:
    return DomainPackage(
        domain_name="network",
        display_name="Network Domain",
        domain_version=1,
        description="Multiplayer replication, network interpolation, and player session schemas.",
        dependencies=[],
        components=[
            replication_component.build_definition(),
            network_transform_component.build_definition(),
            player_session_component.build_definition(),
        ],
    )
