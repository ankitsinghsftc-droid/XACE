"""
mode_profile_loader.py — ModeProfileLoader
============================================
Loads game mode profile definitions from configuration data and validates
them before they are used by the GDE's profile_expander.

## What Is a Game Mode Profile?
A game mode profile is a design archetype — a starting CGS skeleton for
a particular style of game mode (e.g. "arena shooter", "survival", "RPG").
It is NOT the same as a ModeProfile (assistance level). These are two
distinct concepts:

    ModeProfile     — controls how the GDE assists the designer (Phase 12)
    GameModeProfile — a CGS skeleton for a type of gameplay (this file)

## Built-In Templates
Four built-in templates are registered at startup:

    "arena_shooter"  — fast combat, respawning, score-based win condition
    "survival"       — resource scarcity, health attrition, no respawn
    "rpg"            — progression, dialogue, open exploration
    "sandbox"        — creative building, no win condition, free exploration

These match (a subset of) the 30 genre templates in Phase 16 GGE.
The loader here is the GDE's lighter-weight version — it provides
structural blueprints for the CGS, not full genre templates.

## Validation Rules
    L1 — archetype field is non-empty and unique
    L2 — base_cgs_snapshot contains metadata, modes (non-empty), global_systems
    L3 — structural_invariants is a list of strings
    L4 — allowed_systems is a list of system ID strings
    L5 — default_components is a list of non-negative integers (type_ids)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Load Error ────────────────────────────────────────────────────────────────

class ProfileLoadError(Exception):
    """Raised when a game mode profile fails validation."""


# ── Game Mode Profile ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GameModeProfile:
    """
    CGS skeleton for one type of gameplay mode.

    Attributes
    ----------
    archetype : str
        Unique identifier for this profile. Example: "arena_shooter"
    display_name : str
        Human-readable name shown in builder UI and GGE.
    description : str
        One-sentence description for the designer.
    base_cgs_snapshot : dict[str, Any]
        Minimal valid CGS dict that the profile_expander uses as a starting
        point. Contains metadata, one default mode, and global systems.
    structural_invariants : tuple[str, ...]
        Plain-English constraints that must remain true for this archetype.
        Example: "There must always be exactly one player actor."
    allowed_systems : tuple[str, ...]
        System IDs that make sense for this archetype (guidance, not enforcement).
    default_components : tuple[int, ...]
        Component type_ids included by default on new actors in this mode.
    genre_tags : tuple[str, ...]
        Genre keywords for this profile (used by GGE genre detector).
    """

    archetype:             str
    display_name:          str
    description:           str
    base_cgs_snapshot:     dict[str, Any]
    structural_invariants: tuple[str, ...]   = ()
    allowed_systems:       tuple[str, ...]   = ()
    default_components:    tuple[int, ...]   = ()
    genre_tags:            tuple[str, ...]   = ()

    def __repr__(self) -> str:
        return f"GameModeProfile({self.archetype!r})"


# ── Validation ────────────────────────────────────────────────────────────────

def _validate_profile_dict(d: dict[str, Any]) -> list[str]:
    """Returns error strings for a raw profile dict (empty = valid)."""
    errors: list[str] = []

    # L1
    if not d.get("archetype"):
        errors.append("L1: 'archetype' field is missing or empty.")

    # L2
    snap = d.get("base_cgs_snapshot", {})
    if not isinstance(snap, dict):
        errors.append("L2: 'base_cgs_snapshot' must be a dict.")
    else:
        if not snap.get("metadata"):
            errors.append("L2: 'base_cgs_snapshot.metadata' is missing.")
        if not snap.get("modes"):
            errors.append("L2: 'base_cgs_snapshot.modes' must be a non-empty list.")
        if "global_systems" not in snap:
            errors.append("L2: 'base_cgs_snapshot.global_systems' is missing.")

    # L3
    if not isinstance(d.get("structural_invariants", []), list):
        errors.append("L3: 'structural_invariants' must be a list of strings.")

    # L4
    if not isinstance(d.get("allowed_systems", []), list):
        errors.append("L4: 'allowed_systems' must be a list of system ID strings.")

    # L5
    for tid in d.get("default_components", []):
        if not isinstance(tid, int) or tid < 0:
            errors.append(f"L5: default_components entry {tid!r} must be a non-negative int.")

    return errors


# ── Built-In Templates ────────────────────────────────────────────────────────

def _make_base_snapshot(mode_id: str, display_name: str) -> dict[str, Any]:
    return {
        "metadata": {
            "name":     display_name,
            "version":  "0.1.0",
            "cgs_hash": "",
        },
        "global_systems": [
            {
                "id":            "sys_input",
                "phase":         "Input",
                "reads":         [6],
                "writes":        [5],
                "depends_on":    [],
                "deterministic": True,
                "display_name":  "Input System",
            },
            {
                "id":            "sys_movement",
                "phase":         "Simulation",
                "reads":         [5],
                "writes":        [1],
                "depends_on":    ["sys_input"],
                "deterministic": True,
                "display_name":  "Movement System",
            },
        ],
        "modes": [
            {
                "id":             mode_id,
                "display_name":   display_name,
                "is_default":     True,
                "schema_version": "0.1.0",
                "actors":         [],
                "systems":        [],
                "rules":          [],
            }
        ],
    }


_BUILTIN_PROFILES_RAW: list[dict[str, Any]] = [
    {
        "archetype":    "arena_shooter",
        "display_name": "Arena Shooter",
        "description":  "Fast combat with respawning, score tracking, and a time limit.",
        "genre_tags":   ["shooter", "action", "pvp", "arena"],
        "structural_invariants": [
            "There must always be at least one player actor.",
            "There must be a score tracking system or rule.",
            "The mode must have a win condition rule.",
        ],
        "allowed_systems":    [
            "sys_input", "sys_movement", "sys_ai", "sys_damage",
            "sys_death", "sys_respawn", "sys_score",
        ],
        "default_components": [1, 2, 5, 6, 100, 101],
        "base_cgs_snapshot":  _make_base_snapshot("mode_arena", "Arena"),
    },
    {
        "archetype":    "survival",
        "display_name": "Survival",
        "description":  "Resource scarcity, health attrition, no respawn.",
        "genre_tags":   ["survival", "horror", "crafting", "open_world"],
        "structural_invariants": [
            "There must always be exactly one player actor.",
            "The player actor must have a health component.",
            "There must be no respawn rule.",
        ],
        "allowed_systems":    [
            "sys_input", "sys_movement", "sys_ai", "sys_damage",
            "sys_death", "sys_hunger", "sys_inventory",
        ],
        "default_components": [1, 2, 5, 6, 100, 101, 201],
        "base_cgs_snapshot":  _make_base_snapshot("mode_survival", "Survival"),
    },
    {
        "archetype":    "rpg",
        "display_name": "RPG",
        "description":  "Progression, dialogue, exploration, and character growth.",
        "genre_tags":   ["rpg", "exploration", "narrative", "open_world"],
        "structural_invariants": [
            "There must always be exactly one player actor.",
            "The player actor must have a stats or progression component.",
        ],
        "allowed_systems":    [
            "sys_input", "sys_movement", "sys_ai", "sys_dialogue",
            "sys_progression", "sys_inventory", "sys_quests",
        ],
        "default_components": [1, 2, 5, 6, 100, 200, 201, 202, 203, 261],
        "base_cgs_snapshot":  _make_base_snapshot("mode_rpg", "RPG"),
    },
    {
        "archetype":    "sandbox",
        "display_name": "Sandbox",
        "description":  "Creative building and free exploration with no fixed win condition.",
        "genre_tags":   ["sandbox", "building", "creative", "exploration"],
        "structural_invariants": [
            "There must always be exactly one player actor.",
        ],
        "allowed_systems":    [
            "sys_input", "sys_movement", "sys_build", "sys_interact",
            "sys_physics", "sys_worldstream",
        ],
        "default_components": [1, 2, 5, 6, 260],
        "base_cgs_snapshot":  _make_base_snapshot("mode_sandbox", "Sandbox"),
    },
]


# ── Mode Profile Loader ───────────────────────────────────────────────────────

class ModeProfileLoader:
    """
    Loads and indexes GameModeProfile definitions.

    Starts with four built-in templates. Additional profiles can be
    registered from game_config.yaml or custom template files.

    Usage
    -----
        loader = ModeProfileLoader()
        profile = loader.get("survival")
        all_p   = loader.all_profiles()
    """

    def __init__(self) -> None:
        self._profiles: dict[str, GameModeProfile] = {}
        self._load_builtins()

    # ── Public API ────────────────────────────────────────────────────────────

    def get(self, archetype: str) -> GameModeProfile:
        """
        Returns the profile for the given archetype.

        Raises
        ------
        ProfileLoadError
            If no profile with this archetype exists.
        """
        p = self._profiles.get(archetype)
        if p is None:
            raise ProfileLoadError(
                f"No game mode profile found for archetype '{archetype}'. "
                f"Available: {sorted(self._profiles.keys())}"
            )
        return p

    def get_or_none(self, archetype: str) -> GameModeProfile | None:
        return self._profiles.get(archetype)

    def all_profiles(self) -> list[GameModeProfile]:
        """Returns all registered profiles sorted by archetype (D11)."""
        return sorted(self._profiles.values(), key=lambda p: p.archetype)

    def all_archetypes(self) -> list[str]:
        return sorted(self._profiles.keys())

    def by_genre_tag(self, tag: str) -> list[GameModeProfile]:
        """Returns profiles whose genre_tags contain the given tag."""
        tag_lower = tag.lower()
        return [
            p for p in self.all_profiles()
            if any(tag_lower in gt.lower() for gt in p.genre_tags)
        ]

    def register(self, profile_dict: dict[str, Any]) -> GameModeProfile:
        """
        Validates and registers a custom profile from a dict.

        Raises
        ------
        ProfileLoadError
            If the profile dict fails validation or the archetype is duplicate.
        """
        errors = _validate_profile_dict(profile_dict)
        if errors:
            raise ProfileLoadError(
                f"Profile validation failed:\n"
                + "\n".join(f"  {e}" for e in errors)
            )
        archetype = profile_dict["archetype"]
        if archetype in self._profiles:
            raise ProfileLoadError(
                f"Profile archetype '{archetype}' is already registered. "
                f"Use a unique archetype name."
            )
        profile = _dict_to_profile(profile_dict)
        self._profiles[archetype] = profile
        return profile

    def contains(self, archetype: str) -> bool:
        return archetype in self._profiles

    # ── Internal ──────────────────────────────────────────────────────────────

    def _load_builtins(self) -> None:
        for raw in _BUILTIN_PROFILES_RAW:
            profile = _dict_to_profile(raw)
            self._profiles[profile.archetype] = profile


# ── Dict → Profile ────────────────────────────────────────────────────────────

def _dict_to_profile(d: dict[str, Any]) -> GameModeProfile:
    return GameModeProfile(
        archetype=d["archetype"],
        display_name=d.get("display_name", d["archetype"]),
        description=d.get("description", ""),
        base_cgs_snapshot=d.get("base_cgs_snapshot", {}),
        structural_invariants=tuple(d.get("structural_invariants", [])),
        allowed_systems=tuple(d.get("allowed_systems", [])),
        default_components=tuple(d.get("default_components", [])),
        genre_tags=tuple(d.get("genre_tags", [])),
    )