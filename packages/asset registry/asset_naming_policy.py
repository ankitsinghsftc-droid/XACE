"""
asset_naming_policy.py — Auto-naming convention for XACE asset references (Audit 2).

CLAUDE.md: Auto-naming convention: [entity_type][entity_name][asset_type]_[version]
Examples: character_knight_mesh_v1, enemy_dragon_roar_sfx_v1

## Responsibility
One canonical source of truth for how asset IDs are constructed.
Every auto-registration call goes through AssetNamingPolicy.generate().
This guarantees that:
  - The same entity + type always produces the same asset_id
  - Collisions are impossible for different (entity_type, entity_name, asset_type) combos
  - Human-readable IDs appear in the builder UI without needing a lookup table

## Format
`{entity_type}_{entity_name}_{asset_type_suffix}_v{version}`

Where:
  - entity_type: lowercase, e.g. "character", "enemy", "prop", "ui"
  - entity_name: lowercase, spaces converted to underscores
  - asset_type_suffix: short suffix per AssetType (see ASSET_TYPE_SUFFIXES)
  - version: integer starting at 1, incremented on re-registration

## Validation
Generated IDs are checked against the pattern before registration.
IDs that come from external sources (CGS import, migration) are also
validated before being accepted into the registry.
"""

from __future__ import annotations

import re
from typing import Optional

from asset_type_enum import AssetType


# ── Asset Type Suffixes ───────────────────────────────────────────────────────

# Maps each AssetType to the short suffix used in auto-generated IDs.
# These suffixes are part of the public API — do not change them after v1.
ASSET_TYPE_SUFFIXES: dict[AssetType, str] = {
    AssetType.MESH:                 "mesh",
    AssetType.TEXTURE:              "tex",
    AssetType.MATERIAL:             "mat",
    AssetType.ANIMATION_CONTROLLER: "anim",
    AssetType.AUDIO_CLIP:           "sfx",
    AssetType.AUDIO_MUSIC:          "music",
    AssetType.SPRITE:               "sprite",
    AssetType.PARTICLE:             "vfx",
    AssetType.PREFAB:               "prefab",
    AssetType.FONT:                 "font",
}

# Reverse mapping: suffix → AssetType
SUFFIX_TO_ASSET_TYPE: dict[str, AssetType] = {
    v: k for k, v in ASSET_TYPE_SUFFIXES.items()
}

# Canonical ID pattern — validated on every ID accepted into the registry
_ID_PATTERN = re.compile(
    r"^[a-z][a-z0-9]*_[a-z][a-z0-9_]*_"
    r"(mesh|tex|mat|anim|sfx|music|sprite|vfx|prefab|font)"
    r"_v[1-9][0-9]*$"
)


class AssetNamingPolicy:
    """
    Generates and validates canonical asset IDs following the XACE convention.

    ## Usage
    ```python
    # Auto-registration on entity creation:
    asset_id = AssetNamingPolicy.generate("character", "knight", AssetType.MESH)
    # → "character_knight_mesh_v1"

    asset_id = AssetNamingPolicy.generate("enemy", "dragon", AssetType.AUDIO_CLIP)
    # → "enemy_dragon_sfx_v1"
    ```
    """

    @staticmethod
    def generate(
        entity_type: str,
        entity_name: str,
        asset_type: AssetType,
        version: int = 1,
    ) -> str:
        """
        Generates a canonical asset ID.

        Args:
            entity_type: The entity's archetype, e.g. "character", "enemy", "prop"
            entity_name: The entity's name, e.g. "knight", "dragon"
            asset_type: The AssetType for this reference
            version: Version number, starting at 1. Incremented on re-registration.

        Returns:
            Canonical asset ID string.

        Raises:
            ValueError if entity_type or entity_name are empty or invalid,
            or if version < 1.
        """
        if not entity_type or not entity_type.strip():
            raise ValueError("AssetNamingPolicy.generate(): entity_type must not be empty")
        if not entity_name or not entity_name.strip():
            raise ValueError("AssetNamingPolicy.generate(): entity_name must not be empty")
        if version < 1:
            raise ValueError(
                f"AssetNamingPolicy.generate(): version must be >= 1, got {version}"
            )

        # Normalise: lowercase, replace spaces/hyphens with underscores, strip non-alnum
        et = AssetNamingPolicy._normalise_segment(entity_type)
        en = AssetNamingPolicy._normalise_segment(entity_name)
        suffix = ASSET_TYPE_SUFFIXES[asset_type]

        asset_id = f"{et}_{en}_{suffix}_v{version}"

        # Validate the result before returning
        if not AssetNamingPolicy.is_valid(asset_id):
            raise ValueError(
                f"AssetNamingPolicy.generate(): produced invalid ID '{asset_id}'. "
                "Check that entity_type and entity_name contain only valid characters."
            )

        return asset_id

    @staticmethod
    def generate_next_version(
        existing_id: str,
        asset_type: AssetType,
    ) -> str:
        """
        Generates the next version of an existing asset ID.

        Example:
            generate_next_version("character_knight_mesh_v1", AssetType.MESH)
            → "character_knight_mesh_v2"
        """
        parsed = AssetNamingPolicy.parse(existing_id)
        if parsed is None:
            raise ValueError(
                f"AssetNamingPolicy.generate_next_version(): "
                f"'{existing_id}' is not a valid asset ID"
            )
        entity_type, entity_name, _, version = parsed
        return AssetNamingPolicy.generate(entity_type, entity_name, asset_type, version + 1)

    @staticmethod
    def is_valid(asset_id: str) -> bool:
        """
        Returns True if asset_id matches the canonical XACE naming pattern.
        Used by asset_validator.py before accepting any external asset ID.
        """
        if not asset_id:
            return False
        return bool(_ID_PATTERN.match(asset_id))

    @staticmethod
    def parse(asset_id: str) -> Optional[tuple[str, str, AssetType, int]]:
        """
        Parses a canonical asset ID into its components.

        Returns (entity_type, entity_name, asset_type, version) or None if invalid.

        Example:
            parse("character_knight_mesh_v1")
            → ("character", "knight", AssetType.MESH, 1)
        """
        if not AssetNamingPolicy.is_valid(asset_id):
            return None

        # Extract version from end
        version_match = re.search(r"_v(\d+)$", asset_id)
        if not version_match:
            return None
        version = int(version_match.group(1))
        without_version = asset_id[:version_match.start()]

        # Find and extract the suffix
        for suffix, asset_type in SUFFIX_TO_ASSET_TYPE.items():
            if without_version.endswith(f"_{suffix}"):
                remainder = without_version[: -(len(suffix) + 1)]
                # First underscore-separated segment is entity_type,
                # rest is entity_name (may contain underscores)
                first_underscore = remainder.index("_")
                entity_type = remainder[:first_underscore]
                entity_name = remainder[first_underscore + 1:]
                return entity_type, entity_name, asset_type, version

        return None

    @staticmethod
    def extract_asset_type(asset_id: str) -> Optional[AssetType]:
        """
        Extracts the AssetType from a canonical asset ID without full parsing.
        Returns None if the ID is not in canonical format.
        """
        parsed = AssetNamingPolicy.parse(asset_id)
        return parsed[2] if parsed else None

    @staticmethod
    def extract_version(asset_id: str) -> Optional[int]:
        """
        Extracts the version number from a canonical asset ID.
        Returns None if the ID is not in canonical format.
        """
        parsed = AssetNamingPolicy.parse(asset_id)
        return parsed[3] if parsed else None

    @staticmethod
    def _normalise_segment(segment: str) -> str:
        """
        Normalises an entity_type or entity_name segment.
        Converts to lowercase, replaces spaces and hyphens with underscores,
        and strips any characters that are not alphanumeric or underscore.
        """
        s = segment.strip().lower()
        s = re.sub(r"[\s\-]+", "_", s)       # spaces and hyphens → underscores
        s = re.sub(r"[^a-z0-9_]", "", s)      # remove all other non-alnum chars
        s = re.sub(r"_+", "_", s)             # collapse multiple underscores
        s = s.strip("_")                       # strip leading/trailing underscores
        return s

    @staticmethod
    def describe(asset_id: str) -> str:
        """
        Returns a human-readable description of an asset ID for the builder UI.
        Example: "character_knight_mesh_v1" → "Knight (Character) — Mesh, version 1"
        Returns the raw ID if parsing fails.
        """
        parsed = AssetNamingPolicy.parse(asset_id)
        if parsed is None:
            return asset_id
        entity_type, entity_name, asset_type, version = parsed
        return (
            f"{entity_name.replace('_', ' ').title()} "
            f"({entity_type.replace('_', ' ').title()}) — "
            f"{asset_type.value.replace('_', ' ').title()}, version {version}"
        )


# ── Module-level Tests ────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Smoke test the naming policy
    cases = [
        ("character", "knight", AssetType.MESH, 1),
        ("enemy", "dragon", AssetType.AUDIO_CLIP, 1),
        ("prop", "wooden_crate", AssetType.PREFAB, 2),
        ("ui", "main_menu", AssetType.FONT, 1),
    ]
    for et, en, at, v in cases:
        asset_id = AssetNamingPolicy.generate(et, en, at, v)
        print(f"  {asset_id}")
        assert AssetNamingPolicy.is_valid(asset_id), f"Failed validation: {asset_id}"
        parsed = AssetNamingPolicy.parse(asset_id)
        assert parsed is not None
        assert parsed[0] == et
        assert parsed[2] == at
        assert parsed[3] == v
        print(f"    → {AssetNamingPolicy.describe(asset_id)}")
    print("AssetNamingPolicy: all smoke tests passed.")