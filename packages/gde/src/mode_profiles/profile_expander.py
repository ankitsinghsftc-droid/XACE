"""
profile_expander.py — ProfileExpander
=======================================
Expands a GameModeProfile into a full, validated CGS skeleton ready for
the first SchemaFactory.compile() call.

## What Expansion Does
A GameModeProfile.base_cgs_snapshot is intentionally minimal — no actors,
no rules, sparse system list. The ProfileExpander enriches it:

    1. Stamps a fresh cgs_hash and version "0.1.0"
    2. Adds a default player actor with the profile's default_components
    3. Adds placeholder actors for common archetype patterns
       (arena → enemy placeholder; survival → resource node placeholder)
    4. Ensures all referenced component type_ids have table entries
    5. Sets mode.schema_version to match metadata.version
    6. Returns the expanded CGS dict ready for CGSManager.initialise()

## What Expansion Does NOT Do
- It does not validate the CGS against SchemaValidationContract
  (that happens in SchemaFactory.compile())
- It does not populate real assets (all are PLACEHOLDER)
- It does not configure mode-specific rules (GGE does that in Phase 16)
- It does not install gameplay systems beyond the base global_systems

## Determinism
Two calls to expand() with the same profile and game_name always produce
structurally identical CGS dicts (same keys, same structure). The only
non-deterministic part is cgs_hash, which depends on content, but since
content is deterministic the hash is too (D9, D11).
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .mode_profile_loader import GameModeProfile


# ── Expansion Error ───────────────────────────────────────────────────────────

class ProfileExpansionError(Exception):
    """Raised when a profile cannot be expanded into a valid CGS skeleton."""


# ── Default Actor Templates ───────────────────────────────────────────────────

def _player_actor(component_type_ids: list[int]) -> dict[str, Any]:
    return {
        "id":           "actor_player",
        "actor_type":   "PLAYER",
        "control_type": "HUMAN",
        "tags":         ["player"],
        "mode_scope":   [],
        "components": [
            {"type_id": tid, "defaults": {}}
            for tid in sorted(component_type_ids)
        ],
    }


_ARCHETYPE_EXTRA_ACTORS: dict[str, list[dict[str, Any]]] = {
    "arena_shooter": [
        {
            "id":           "actor_enemy_placeholder",
            "actor_type":   "ENEMY",
            "control_type": "AI_PROXY",
            "tags":         ["enemy", "placeholder"],
            "mode_scope":   [],
            "components":   [
                {"type_id": 1,   "defaults": {}},
                {"type_id": 2,   "defaults": {}},
                {"type_id": 5,   "defaults": {}},
                {"type_id": 100, "defaults": {}},
                {"type_id": 160, "defaults": {}},
            ],
        }
    ],
    "survival": [
        {
            "id":           "actor_resource_node",
            "actor_type":   "WORLD_OBJECT",
            "control_type": "NONE",
            "tags":         ["resource", "placeholder"],
            "mode_scope":   [],
            "components":   [
                {"type_id": 1,   "defaults": {}},
                {"type_id": 2,   "defaults": {}},
                {"type_id": 260, "defaults": {}},
            ],
        }
    ],
    "rpg": [
        {
            "id":           "actor_npc_placeholder",
            "actor_type":   "NPC",
            "control_type": "AI_PROXY",
            "tags":         ["npc", "placeholder"],
            "mode_scope":   [],
            "components":   [
                {"type_id": 1,   "defaults": {}},
                {"type_id": 2,   "defaults": {}},
                {"type_id": 5,   "defaults": {}},
                {"type_id": 261, "defaults": {}},
            ],
        }
    ],
    "sandbox": [],
}


# ── Profile Expander ──────────────────────────────────────────────────────────

class ProfileExpander:
    """
    Expands a GameModeProfile into a full CGS skeleton.

    Stateless — one call to expand() per new game creation.

    Usage
    -----
        expander = ProfileExpander()
        cgs      = expander.expand(profile, game_name="My Survival Game")
        manager  = CGSManager.initialise(cgs)
    """

    def expand(
        self,
        profile:   GameModeProfile,
        game_name: str = "",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Expands a GameModeProfile into a full CGS skeleton.

        Parameters
        ----------
        profile : GameModeProfile
            The archetype profile to expand from.
        game_name : str
            The name the designer gave to the game. Used in metadata.
        session_id : str | None
            Builder session ID for provenance.

        Returns
        -------
        dict[str, Any]
            Fully expanded CGS dict ready for CGSManager.initialise().

        Raises
        ------
        ProfileExpansionError
            If the profile snapshot is malformed.
        """
        # Deep copy to avoid mutating the profile
        cgs = copy.deepcopy(profile.base_cgs_snapshot)

        if not isinstance(cgs, dict):
            raise ProfileExpansionError(
                f"Profile '{profile.archetype}' base_cgs_snapshot is not a dict."
            )
        if not cgs.get("modes"):
            raise ProfileExpansionError(
                f"Profile '{profile.archetype}' base_cgs_snapshot has no modes."
            )

        # ── Step 1: Stamp metadata ────────────────────────────────────────────
        cgs.setdefault("metadata", {})
        cgs["metadata"]["name"]    = game_name or profile.display_name
        cgs["metadata"]["version"] = "0.1.0"

        # ── Step 2: Populate default mode ────────────────────────────────────
        mode = cgs["modes"][0]
        mode["schema_version"] = "0.1.0"

        # ── Step 3: Add player actor ──────────────────────────────────────────
        comp_ids = list(profile.default_components) or [1, 2, 5, 6, 100]
        player   = _player_actor(comp_ids)
        if not any(a.get("id") == "actor_player" for a in mode.get("actors", [])):
            mode.setdefault("actors", []).append(player)

        # ── Step 4: Add archetype-specific placeholder actors ─────────────────
        extra_actors = _ARCHETYPE_EXTRA_ACTORS.get(profile.archetype, [])
        existing_ids = {a.get("id") for a in mode.get("actors", [])}
        for actor in extra_actors:
            if actor.get("id") not in existing_ids:
                mode["actors"].append(copy.deepcopy(actor))

        # ── Step 5: Sort actors by ID (D11) ───────────────────────────────────
        mode["actors"].sort(key=lambda a: a.get("id", ""))

        # ── Step 6: Sort global_systems by ID (D11) ───────────────────────────
        cgs["global_systems"].sort(key=lambda s: s.get("id", ""))

        # ── Step 7: Compute and stamp cgs_hash ───────────────────────────────
        cgs["metadata"]["cgs_hash"] = _compute_hash(cgs)

        return cgs

    def expand_many(
        self,
        profile:    GameModeProfile,
        game_name:  str,
        mode_count: int = 1,
    ) -> dict[str, Any]:
        """
        Expands a profile into a multi-mode CGS.
        The first mode is the default; additional modes are copies with unique IDs.
        """
        if mode_count < 1:
            raise ProfileExpansionError("mode_count must be at least 1.")
        cgs = self.expand(profile, game_name)
        base_mode = cgs["modes"][0]

        for i in range(1, mode_count):
            extra = copy.deepcopy(base_mode)
            extra["id"]         = f"{base_mode['id']}_{i+1}"
            extra["is_default"] = False
            extra["display_name"] = f"{base_mode.get('display_name', '')} {i+1}"
            # Suffix all actor IDs to avoid cross-mode collision
            for actor in extra.get("actors", []):
                actor["id"] = f"{actor['id']}_m{i+1}"
            cgs["modes"].append(extra)

        # Recompute hash after adding modes
        cgs["metadata"]["cgs_hash"] = _compute_hash(cgs)
        return cgs

    def validate_expanded(self, cgs: dict[str, Any]) -> list[str]:
        """
        Lightweight validation of an expanded CGS before passing to
        CGSManager. Returns error strings (empty = passes basic checks).
        Full validation happens in SchemaValidationContract.
        """
        errors: list[str] = []

        if not cgs.get("metadata", {}).get("version"):
            errors.append("Expanded CGS missing metadata.version.")
        if not cgs.get("metadata", {}).get("cgs_hash"):
            errors.append("Expanded CGS missing metadata.cgs_hash.")
        if not cgs.get("modes"):
            errors.append("Expanded CGS has no modes.")
        else:
            if not any(m.get("is_default") for m in cgs["modes"]):
                errors.append("Expanded CGS has no default mode.")
            for mode in cgs["modes"]:
                if not mode.get("schema_version"):
                    errors.append(f"Mode '{mode.get('id')}' missing schema_version.")

        return errors


# ── Hash Helper ───────────────────────────────────────────────────────────────

def _compute_hash(cgs: dict[str, Any]) -> str:
    """Computes a deterministic SHA-256 hash of the CGS dict (D9, D11)."""
    stripped = copy.deepcopy(cgs)
    stripped.get("metadata", {}).pop("cgs_hash", None)
    canonical = json.dumps(stripped, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()