"""
scope_resolver.py — ScopeResolver
=====================================
Resolves the fuzzy scope hints in an IntentObject into concrete
CGS references.

IntentClassifier produces shallow hints ("actor_hint": "zombie").
ScopeResolver converts those hints into precise IDs and paths
("actor_id": "actor_zombie", "component_type_ids": [100, 101]).

## Resolution Chain
    intent.scope.actor_hint        → intent.scope.actor_id
    intent.scope.component_hints   → intent.scope.component_type_ids
    intent.scope.mode_hint         → intent.scope.mode_id
    intent.action.field            → path_hints (fully-qualified CGS paths)

## Ambiguity
When a hint matches more than one CGS node, the resolver records all
matches in `scope.candidate_actor_ids` (etc.) and sets a low confidence.
AmbiguityDetector picks this up and generates clarification questions.

## What the Resolver Does NOT Do
- It does not validate that the resolved path is writable — that is
  the ConsistencyValidator's job.
- It does not run PathParser validation — it trusts PathResolver.
- It does not produce DSL operations — that is TransactionBuilder's job.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from .intent_object import IntentObject, GDEIntentType
from ..domain_dsl.path_addressing.path_resolver import PathResolver


# ── Resolution Result ─────────────────────────────────────────────────────────

@dataclass
class ScopeResolutionResult:
    """
    Outcome of resolving an IntentObject's scope against the CGS.

    Attributes
    ----------
    resolved_actor_id : str | None
        The single definitively resolved actor ID, or None.
    resolved_mode_id : str | None
        The definitively resolved mode ID.
    resolved_component_ids : list[int]
        Component type IDs conclusively linked to this intent.
    resolved_path_hints : list[str]
        Fully-qualified CGS path hints for the mutation target.
    candidate_actor_ids : list[str]
        All actors that matched the hint (>1 means ambiguous).
    candidate_paths : list[str]
        All possible paths when ambiguous.
    confidence : float
        How confident the resolution is [0.0–1.0].
    is_ambiguous : bool
        True if more than one candidate matched.
    resolution_notes : list[str]
        Human-readable notes explaining how resolution went.
    """

    resolved_actor_id:       str | None   = None
    resolved_mode_id:        str | None   = None
    resolved_component_ids:  list[int]    = field(default_factory=list)
    resolved_path_hints:     list[str]    = field(default_factory=list)
    candidate_actor_ids:     list[str]    = field(default_factory=list)
    candidate_paths:         list[str]    = field(default_factory=list)
    confidence:              float        = 1.0
    is_ambiguous:            bool         = False
    resolution_notes:        list[str]    = field(default_factory=list)

    def __repr__(self) -> str:
        amb = " [AMBIGUOUS]" if self.is_ambiguous else ""
        return (
            f"ScopeResolutionResult("
            f"actor={self.resolved_actor_id!r}, "
            f"mode={self.resolved_mode_id!r}, "
            f"components={self.resolved_component_ids}, "
            f"conf={self.confidence:.2f}{amb})"
        )


# ── Component Name Vocabulary ─────────────────────────────────────────────────

# Maps common English names to DCL/UCL component type_ids
_COMPONENT_VOCAB: dict[str, list[int]] = {
    # UCL
    "transform":    [1],
    "position":     [1],
    "identity":     [2],
    "velocity":     [5],
    "speed":        [5],
    "movement":     [5],
    "input":        [6],
    "event":        [7],
    "lifetime":     [8],
    "gamestate":    [9],
    "game state":   [9],
    "authority":    [10],
    # DCL combat
    "health":       [100],
    "hp":           [100],
    "damage":       [101],
    "hitbox":       [102],
    "shield":       [103],
    "status":       [104],
    # DCL character
    "animation":    [121],
    "ik":           [122],
    # DCL ai
    "ai":           [160],
    "patrol":       [161],
    "perception":   [162],
    "detection":    [162],
    # DCL rpg
    "stats":        [200],
    "inventory":    [201],
    "ability":      [202],
    "progression":  [203],
    "economy":      [204],
    # DCL interaction
    "interaction":  [260],
    "dialogue":     [261],
    # DCL audio
    "audio":        [300],
    "sound":        [300],
}


# ── Scope Resolver ────────────────────────────────────────────────────────────

class ScopeResolver:
    """
    Resolves fuzzy IntentObject scope hints into concrete CGS references.

    Mutates the intent.scope dict in-place (adds resolved fields).
    Returns a ScopeResolutionResult for callers that need the detail.

    Usage
    -----
        resolver = ScopeResolver()
        result   = resolver.resolve(intent, cgs)
        # intent.scope now has actor_id, mode_id, component_type_ids set
    """

    def __init__(self) -> None:
        self._path_resolver = PathResolver()

    def resolve(
        self,
        intent: IntentObject,
        cgs:    dict[str, Any],
    ) -> ScopeResolutionResult:
        """
        Resolves the intent scope and updates intent.scope in-place.

        Returns the detailed ScopeResolutionResult. Callers only need
        to inspect the result if they want ambiguity details; the intent
        is updated regardless.
        """
        result = ScopeResolutionResult()

        # ── Step 1: Resolve mode ──────────────────────────────────────────────
        mode_id = self._resolve_mode(intent, cgs, result)
        result.resolved_mode_id = mode_id
        intent.scope["mode_id"] = mode_id

        # ── Step 2: Resolve actor ─────────────────────────────────────────────
        mode_dict = _find_mode(mode_id, cgs) if mode_id else {}
        actor_id  = self._resolve_actor(intent, mode_dict, result)
        result.resolved_actor_id = actor_id
        if actor_id:
            intent.scope["actor_id"] = actor_id

        # ── Step 3: Resolve component type IDs ───────────────────────────────
        comp_ids = self._resolve_components(intent, cgs, mode_dict, actor_id, result)
        result.resolved_component_ids = comp_ids
        intent.scope["component_type_ids"] = comp_ids

        # ── Step 4: Build path hints ──────────────────────────────────────────
        paths = self._build_path_hints(intent, mode_id, actor_id, comp_ids, cgs)
        result.resolved_path_hints = paths
        intent.scope["path_hints"] = paths

        # ── Step 5: Update confidence on intent ───────────────────────────────
        if result.confidence < intent.confidence:
            intent.confidence = result.confidence

        return result

    # ── Mode Resolution ───────────────────────────────────────────────────────

    @staticmethod
    def _resolve_mode(
        intent: IntentObject,
        cgs:    dict[str, Any],
        result: ScopeResolutionResult,
    ) -> str | None:
        """Resolves mode hint or explicit ID to a confirmed mode ID."""
        # Already set explicitly
        if intent.mode_id:
            if _find_mode(intent.mode_id, cgs):
                return intent.mode_id
            result.resolution_notes.append(
                f"Explicit mode_id '{intent.mode_id}' not found in CGS. "
                f"Falling back to default mode."
            )

        # Use mode_hint
        mode_hint = intent.scope.get("mode_hint", "")
        if mode_hint:
            candidates = [
                m.get("id") for m in cgs.get("modes", [])
                if mode_hint.lower() in m.get("id", "").lower()
                or mode_hint.lower() in m.get("display_name", "").lower()
            ]
            if len(candidates) == 1:
                return candidates[0]
            if len(candidates) > 1:
                result.is_ambiguous = True
                result.confidence   = min(result.confidence, 0.5)
                result.resolution_notes.append(
                    f"Mode hint '{mode_hint}' matched {len(candidates)} modes: "
                    f"{candidates}. Defaulting to first."
                )
                return candidates[0]

        # Default mode
        for mode in cgs.get("modes", []):
            if mode.get("is_default", False):
                return mode.get("id")

        modes = cgs.get("modes", [])
        return modes[0].get("id") if modes else None

    # ── Actor Resolution ──────────────────────────────────────────────────────

    @staticmethod
    def _resolve_actor(
        intent:    IntentObject,
        mode_dict: dict[str, Any],
        result:    ScopeResolutionResult,
    ) -> str | None:
        """Resolves actor hint or explicit ID to a confirmed actor ID."""
        actors = mode_dict.get("actors", [])

        if intent.actor_id:
            if any(a.get("id") == intent.actor_id for a in actors):
                return intent.actor_id
            result.resolution_notes.append(
                f"Explicit actor_id '{intent.actor_id}' not found in mode. "
                f"Will attempt fuzzy resolution."
            )

        hint = intent.scope.get("actor_hint", "")
        if not hint:
            return None

        hint_lower = hint.lower()
        # Exact ID match
        exact = [a for a in actors if a.get("id", "").lower() == hint_lower]
        if exact:
            return exact[0]["id"]

        # Fuzzy: hint is a substring of ID
        fuzzy_id = [a for a in actors if hint_lower in a.get("id", "").lower()]
        # Fuzzy: hint matches actor_type
        fuzzy_type = [
            a for a in actors
            if hint_lower in str(a.get("actor_type", "")).lower()
        ]

        candidates = fuzzy_id or fuzzy_type
        ids = [a.get("id") for a in candidates]
        result.candidate_actor_ids = ids

        if len(ids) == 1:
            result.resolution_notes.append(
                f"Actor hint '{hint}' resolved to '{ids[0]}'."
            )
            return ids[0]

        if len(ids) > 1:
            result.is_ambiguous = True
            result.confidence   = min(result.confidence, 0.55)
            result.resolution_notes.append(
                f"Actor hint '{hint}' matched {len(ids)} actors: {ids}."
            )
            return None   # AmbiguityDetector will ask

        result.resolution_notes.append(
            f"Actor hint '{hint}' matched no actors in mode."
        )
        return None

    # ── Component Resolution ──────────────────────────────────────────────────

    @staticmethod
    def _resolve_components(
        intent:    IntentObject,
        cgs:       dict[str, Any],
        mode_dict: dict[str, Any],
        actor_id:  str | None,
        result:    ScopeResolutionResult,
    ) -> list[int]:
        """Resolves component hints to type_ids."""
        # Start with any explicitly declared type IDs
        resolved: set[int] = set(intent.component_type_ids)

        # Map component name hints via vocabulary
        comp_hints = intent.scope.get("component_hints", [])
        for hint in comp_hints:
            ids = _COMPONENT_VOCAB.get(hint.lower(), [])
            resolved.update(ids)

        # If actor is known, intersect with what the actor actually has
        if actor_id:
            actor_comp_ids = _actor_component_ids(actor_id, mode_dict)
            if actor_comp_ids:
                intersected = resolved & actor_comp_ids
                if intersected:
                    resolved = intersected
                else:
                    result.resolution_notes.append(
                        f"Component hints {sorted(resolved)} do not overlap with "
                        f"actor '{actor_id}' components {sorted(actor_comp_ids)}. "
                        f"Keeping all hinted IDs."
                    )

        return sorted(resolved)

    # ── Path Hint Builder ─────────────────────────────────────────────────────

    def _build_path_hints(
        self,
        intent:   IntentObject,
        mode_id:  str | None,
        actor_id: str | None,
        comp_ids: list[int],
        cgs:      dict[str, Any],
    ) -> list[str]:
        """
        Builds fully-qualified path hints from resolved scope.
        These are candidate mutation paths, not confirmed resolvable paths.
        """
        if not mode_id or not actor_id:
            return []

        paths: list[str] = []
        field_name = intent.action.get("field", "")
        base = f"modes.{mode_id}.actors.{actor_id}"

        for comp_id in comp_ids:
            if field_name:
                path = f"{base}.components.{comp_id}.defaults.{field_name}"
                if self._path_resolver.exists(path, cgs):
                    paths.append(path)
                else:
                    # Field may not exist yet — include as candidate anyway
                    paths.append(path)
            else:
                paths.append(f"{base}.components.{comp_id}")

        return paths


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_mode(mode_id: str, cgs: dict[str, Any]) -> dict[str, Any]:
    for mode in cgs.get("modes", []):
        if mode.get("id") == mode_id:
            return mode
    return {}


def _actor_component_ids(actor_id: str, mode_dict: dict[str, Any]) -> set[int]:
    for actor in mode_dict.get("actors", []):
        if actor.get("id") == actor_id:
            return {
                c.get("type_id")
                for c in actor.get("components", [])
                if c.get("type_id") is not None
            }
    return set()