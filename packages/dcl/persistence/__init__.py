"""DCL Persistence Domain.

Provides save/load component schemas:
- COMP_SAVE_SLOT_V1
- COMP_CHECKPOINT_V1
- COMP_PLAYER_PROFILE_V1
- COMP_CLOUD_SYNC_V1
"""

from __future__ import annotations

from ..domain_package import DomainPackage
from . import (
    checkpoint_component,
    cloud_sync_component,
    player_profile_component,
    save_slot_component,
)

__all__ = [
    "get_domain_package",
    "save_slot_component",
    "checkpoint_component",
    "player_profile_component",
    "cloud_sync_component",
]


def get_domain_package() -> DomainPackage:
    return DomainPackage(
        domain_name="persistence",
        display_name="Persistence Domain",
        domain_version=1,
        description="Save slots, checkpoints, player profiles, and cloud sync schemas.",
        dependencies=[],
        components=[
            save_slot_component.build_definition(),
            checkpoint_component.build_definition(),
            player_profile_component.build_definition(),
            cloud_sync_component.build_definition(),
        ],
    )
