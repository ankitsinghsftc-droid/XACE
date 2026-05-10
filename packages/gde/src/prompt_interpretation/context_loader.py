"""
context_loader.py — ContextLoader
====================================
Loads a minimal CGS context slice relevant to an incoming IntentObject.

Full schema transmission is FORBIDDEN (CLAUDE.md). The ContextLoader
extracts only the CGS nodes the scope resolver, slot extractor, and
(when PIL runs) the LLM need to understand and act on the intent.

## What Goes into the Slice
For a "make the zombie faster" intent:
    - The zombie actor definition (COMP_TRANSFORM_V1, COMP_VELOCITY_V1 fields)
    - COMP_VELOCITY_V1 schema metadata (field names, ranges)
    - The mode the zombie lives in

For a "add a death rule when health reaches 0" intent:
    - The actor being targeted (to know which health component it has)
    - Existing rules in the mode (to check for duplicates)
    - COMP_HEALTH_V1 schema metadata

## What Is Always Excluded
    - Other modes not referenced by the intent
    - Actors not referenced by the intent
    - Full global_systems list (only relevant systems included)
    - Component defaults for unrelated components

## CGSContextSlice
The slice is a plain dataclass — not a dict — so callers know exactly
what fields are populated. Absent fields are None or empty collections,
never raised as errors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .intent_object import IntentObject, GDEIntentType


# ── CGS Context Slice ─────────────────────────────────────────────────────────

@dataclass
class CGSContextSlice:
    """
    Minimal relevant CGS context for one intent.

    Attributes
    ----------
    intent_type : str
        The intent type this slice was built for.
    mode_id : str | None
        The target mode ID, if resolved.
    mode_display_name : str | None
        Human-readable mode name for builder UI.
    target_actors : list[dict]
        Actor definition dicts for actors relevant to the intent.
        Each dict contains the actor's id, actor_type, and components.
    related_systems : list[dict]
        System definition dicts for systems that read/write the
        components this intent touches.
    existing_rules : list[dict]
        Rule definitions in the target mode. Included when the intent
        might create or modify rules (dedup check).
    component_hints : list[dict]
        Component metadata dicts (type_id, name, field_names) for
        components mentioned or implied by the intent.
    global_system_ids : list[str]
        IDs of global systems only (not full definitions). Enough for
        conflict detection without blowing up context size.
    all_actor_ids_in_mode : list[str]
        All actor IDs in the target mode. Needed for name resolution
        and duplicate detection.
    all_system_ids : list[str]
        All system IDs in the CGS (global + mode). For dep checking.
    cgs_version : str
        CGS version this slice was taken from. Used to detect staleness.
    """

    intent_type:          str
    mode_id:              str | None              = None
    mode_display_name:    str | None              = None
    target_actors:        list[dict[str, Any]]    = field(default_factory=list)
    related_systems:      list[dict[str, Any]]    = field(default_factory=list)
    existing_rules:       list[dict[str, Any]]    = field(default_factory=list)
    component_hints:      list[dict[str, Any]]    = field(default_factory=list)
    global_system_ids:    list[str]               = field(default_factory=list)
    all_actor_ids_in_mode: list[str]              = field(default_factory=list)
    all_system_ids:       list[str]               = field(default_factory=list)
    cgs_version:          str                     = ""

    def actor_ids(self) -> list[str]:
        return [a.get("id", "") for a in self.target_actors]

    def rule_ids(self) -> list[str]:
        return [r.get("id", "") for r in self.existing_rules]

    def component_type_ids(self) -> list[int]:
        return [c.get("type_id", 0) for c in self.component_hints]

    def is_empty(self) -> bool:
        return (
            not self.target_actors
            and not self.related_systems
            and not self.existing_rules
        )

    def __repr__(self) -> str:
        return (
            f"CGSContextSlice(intent={self.intent_type!r}, "
            f"mode={self.mode_id!r}, "
            f"actors={len(self.target_actors)}, "
            f"systems={len(self.related_systems)}, "
            f"rules={len(self.existing_rules)})"
        )


# ── Context Loader ────────────────────────────────────────────────────────────

class ContextLoader:
    """
    Extracts a minimal CGS context slice for a given IntentObject.

    Stateless — safe to call repeatedly with different intents and CGS states.

    Usage
    -----
        loader = ContextLoader()
        slice  = loader.load(intent, cgs)
    """

    # Maximum number of actors to include in one slice.
    # If more match, only the most relevant N are included.
    MAX_ACTORS      = 5
    MAX_SYSTEMS     = 8
    MAX_RULES       = 20

    def load(
        self,
        intent: IntentObject,
        cgs:    dict[str, Any],
    ) -> CGSContextSlice:
        """
        Builds a CGSContextSlice for the given intent.

        Parameters
        ----------
        intent : IntentObject
            Classified intent, optionally enriched with scope hints.
        cgs : dict[str, Any]
            Current CGS dict (deep copy — loader does not mutate it).

        Returns
        -------
        CGSContextSlice
            Populated with only the CGS nodes relevant to this intent.
        """
        version    = cgs.get("metadata", {}).get("version", "")
        mode_id    = self._resolve_mode_id(intent, cgs)
        mode_dict  = self._find_mode(mode_id, cgs) if mode_id else {}

        slice_ = CGSContextSlice(
            intent_type=intent.intent_type,
            mode_id=mode_id,
            mode_display_name=mode_dict.get("display_name"),
            cgs_version=version,
        )

        # All actor IDs in the target mode (for name resolution)
        if mode_dict:
            slice_.all_actor_ids_in_mode = [
                a.get("id", "") for a in mode_dict.get("actors", [])
                if a.get("id")
            ]

        # All system IDs across CGS (global + mode)
        slice_.all_system_ids = self._collect_all_system_ids(cgs)

        # Global system IDs only (not full defs)
        slice_.global_system_ids = [
            s.get("id", "") for s in cgs.get("global_systems", [])
            if s.get("id")
        ]

        # Load actors relevant to this intent
        slice_.target_actors = self._load_target_actors(intent, mode_dict)

        # Load related systems (those that read/write hinted components)
        slice_.related_systems = self._load_related_systems(intent, cgs, mode_dict)

        # Load existing rules (for rule intents)
        if GDEIntentType.is_query(intent.intent_type) or \
           intent.intent_type in (
               GDEIntentType.DEFINE_RULE,
               GDEIntentType.MODIFY_RULE,
               GDEIntentType.REMOVE_RULE,
           ):
            slice_.existing_rules = list(mode_dict.get("rules", []))[:self.MAX_RULES]

        # Component hints (type_id + field names, no defaults)
        slice_.component_hints = self._build_component_hints(intent)

        return slice_

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _resolve_mode_id(
        self, intent: IntentObject, cgs: dict[str, Any]
    ) -> str | None:
        """Returns the target mode ID from intent.scope or finds the default mode."""
        # Prefer explicit mode_id on scope
        if intent.mode_id:
            return intent.mode_id

        # Fall back to mode_hint (partial name from classifier)
        mode_hint = intent.scope.get("mode_hint", "")
        if mode_hint:
            for mode in cgs.get("modes", []):
                mid = mode.get("id", "")
                if mode_hint in mid.lower() or mid.lower() in mode_hint:
                    return mid

        # Fall back to default mode
        for mode in cgs.get("modes", []):
            if mode.get("is_default", False):
                return mode.get("id")

        # First mode if no default
        modes = cgs.get("modes", [])
        return modes[0].get("id") if modes else None

    @staticmethod
    def _find_mode(mode_id: str, cgs: dict[str, Any]) -> dict[str, Any]:
        for mode in cgs.get("modes", []):
            if mode.get("id") == mode_id:
                return mode
        return {}

    def _load_target_actors(
        self, intent: IntentObject, mode_dict: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Selects actors relevant to the intent from the target mode."""
        all_actors = mode_dict.get("actors", [])
        actor_hint = intent.scope.get("actor_hint", "")
        explicit   = intent.actor_id

        if explicit:
            # Exact match on actor_id
            matched = [a for a in all_actors if a.get("id") == explicit]
            return matched[:self.MAX_ACTORS]

        if actor_hint:
            # Fuzzy match on name/type
            matched = [
                a for a in all_actors
                if actor_hint in a.get("id", "").lower()
                or actor_hint in str(a.get("actor_type", "")).lower()
            ]
            if matched:
                return matched[:self.MAX_ACTORS]

        # For structural creates, return all actors (for ID dedup check)
        if intent.intent_type in (
            GDEIntentType.CREATE_ACTOR, GDEIntentType.DEFINE_RULE
        ):
            return all_actors[:self.MAX_ACTORS]

        return []

    def _load_related_systems(
        self,
        intent:    IntentObject,
        cgs:       dict[str, Any],
        mode_dict: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Selects systems that read/write the hinted component types."""
        comp_hints   = intent.scope.get("component_hints", [])
        hinted_ids   = set(intent.component_type_ids)

        # Map component name hints to type_ids (shallow — resolver does deep)
        _COMP_NAME_TO_ID = {
            "health": 100, "damage": 101, "hitbox": 102,
            "velocity": 5, "speed": 5, "transform": 1,
            "ai": 160, "patrol": 161, "perception": 162,
        }
        for hint in comp_hints:
            tid = _COMP_NAME_TO_ID.get(hint.lower())
            if tid:
                hinted_ids.add(tid)

        if not hinted_ids:
            return []

        result: list[dict[str, Any]] = []
        for sys in list(cgs.get("global_systems", [])) + list(mode_dict.get("systems", [])):
            reads  = set(sys.get("reads", []))
            writes = set(sys.get("writes", []))
            if reads & hinted_ids or writes & hinted_ids:
                result.append({
                    "id":    sys.get("id"),
                    "phase": sys.get("phase"),
                    "reads": sorted(reads),
                    "writes": sorted(writes),
                })
        return result[:self.MAX_SYSTEMS]

    @staticmethod
    def _build_component_hints(intent: IntentObject) -> list[dict[str, Any]]:
        """
        Builds lightweight component metadata dicts from intent scope.
        Only type_id and name — no defaults (too large for context window).
        """
        _ID_TO_META = {
            1:   {"type_id": 1,   "name": "COMP_TRANSFORM_V1",  "domain": "ucl"},
            2:   {"type_id": 2,   "name": "COMP_IDENTITY_V1",   "domain": "ucl"},
            5:   {"type_id": 5,   "name": "COMP_VELOCITY_V1",   "domain": "ucl",
                  "fields": ["linear.x", "linear.y", "linear.z", "max_linear_speed"]},
            100: {"type_id": 100, "name": "COMP_HEALTH_V1",     "domain": "dcl/combat",
                  "fields": ["current", "max", "regen_rate", "is_invincible"]},
            101: {"type_id": 101, "name": "COMP_DAMAGE_V1",     "domain": "dcl/combat",
                  "fields": ["amount", "damage_type", "is_consumed"]},
            160: {"type_id": 160, "name": "COMP_AI_V1",         "domain": "dcl/ai",
                  "fields": ["behavior_model", "detection_radius", "aggression_level"]},
        }
        hints = []
        for tid in intent.component_type_ids:
            meta = _ID_TO_META.get(tid)
            if meta:
                hints.append(meta)
        return hints

    @staticmethod
    def _collect_all_system_ids(cgs: dict[str, Any]) -> list[str]:
        ids: list[str] = []
        for s in cgs.get("global_systems", []):
            if s.get("id"):
                ids.append(s["id"])
        for mode in cgs.get("modes", []):
            for s in mode.get("systems", []):
                if s.get("id") and s["id"] not in ids:
                    ids.append(s["id"])
        return sorted(ids)