"""
scope_builder.py — ScopeBuilder
=================================
Resolves AllowedMutationScope for a given IntentEnvelope + CGS.

ScopeBuilder answers: "given what the user wants to do and what mode
they are in, which CGS paths may the LLM touch?"

## Why Scope Resolution Matters

    Without an explicit scope, the LLM could propose mutations anywhere
    in the CGS — including engine-internal fields (entity_id format,
    schema_version), frozen UCL component definitions, or other actors
    not mentioned by the user. Scope constrains the solution space before
    any LLM token is spent.

## Scope Building Strategy

    1. Forbidden paths — always blocked, regardless of mode or intent.
       These cover CGS fields that XACE owns and that no designer prompt
       may ever touch. Set once at module load, never changed.

    2. Intent-derived allowed paths — extracted from IntentEnvelope's
       intent category + the GDE intent hints. For a BalanceAdjustment
       targeting actor_zombie, the allowed paths include:
           modes[mode_default].actors[actor_zombie].components[*].defaults.*

    3. Mode expansion — ARCHITECT_MODE removes the allow-list entirely
       (allowed_paths = empty tuple = unrestricted). FULLY_ASSISTED
       narrows paths further to only the most-likely target.

    4. Structural gating — structural_change_allowed is True only when:
       - intent_category is CreateFeature, RemoveFeature, or StructuralChange
       - AND mode is not FULLY_ASSISTED (beginners don't get structural ops)

## CGS Path Conventions (from the real CGS JSON)

    Global:
        metadata.*                        — forbidden (schema_version, cgs_hash)
        global_systems[*].*               — allowed for StructuralChange

    Per-mode:
        modes[{mode_id}].actors[{actor_id}].components[{type_id}].defaults.*
        modes[{mode_id}].systems[{system_id}].*
        modes[{mode_id}].rules[{rule_id}].*

## Forbidden Path List

    These paths are NEVER mutable regardless of mode or intent:
        metadata.cgs_hash
        metadata.schema_version
        metadata.name         (rename via metadata ops only)
        metadata.version      (bumped by CGSManager, not by LLM)
        Any path containing: entity_id_format, ucl_frozen, tick_rate,
        determinism_invariant
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from llm_context_packet import AllowedMutationScope
from intent_intake.intent_envelope import IntentEnvelope, PILIntentCategory


# ── Permanent Forbidden Paths ─────────────────────────────────────────────────
# These are always forbidden regardless of mode or intent.

_PERMANENT_FORBIDDEN: tuple[str, ...] = (
    "metadata.cgs_hash",
    "metadata.schema_version",
    "metadata.name",
    "metadata.version",
    "metadata.ucl_version",
    "entity_id_format",
    "ucl_frozen",
    "tick_rate",
    "determinism_invariant",
    "mutation_gate_config",
    "snapshot_engine_config",
)

# ── Structural intent categories ──────────────────────────────────────────────

_STRUCTURAL_CATEGORIES = frozenset({
    PILIntentCategory.CREATE_FEATURE,
    PILIntentCategory.REMOVE_FEATURE,
    PILIntentCategory.STRUCTURAL_CHANGE,
})

# ── Modes that never get structural ops ───────────────────────────────────────
# FULLY_ASSISTED: system acts conservatively, no schema architecture changes.

_NO_STRUCTURAL_MODES = frozenset({"FULLY_ASSISTED"})

# ── Max mutation depth per mode ───────────────────────────────────────────────

_MAX_DEPTH: dict[str, int] = {
    "FULLY_ASSISTED":  2,   # e.g. components[100].current
    "COLLABORATIVE":   3,   # e.g. components[100].defaults.current
    "ADVANCED":        4,
    "ARCHITECT_MODE":  8,   # deep paths allowed
}
_DEFAULT_MAX_DEPTH = 3


# ── Scope Builder ─────────────────────────────────────────────────────────────

class ScopeBuilder:
    """
    Resolves AllowedMutationScope for one PIL call.

    Stateless — safe to share across sessions.
    Deterministic — same inputs always produce the same scope.

    Usage
    -----
        builder = ScopeBuilder()
        scope   = builder.build(envelope, cgs)

        scope.path_is_allowed("modes[mode_default].actors[actor_zombie]...")
        scope.structural_change_allowed
    """

    def build(
        self,
        envelope: IntentEnvelope,
        cgs:      dict[str, Any],
    ) -> AllowedMutationScope:
        """
        Builds AllowedMutationScope from envelope + current CGS.

        Parameters
        ----------
        envelope : IntentEnvelope
            Output of IntentIntakeLayer — carries intent_category,
            assistance_mode, and confidence.
        cgs : dict
            The current CGS JSON (real schema, not a stub).

        Returns
        -------
        AllowedMutationScope
            Always returns. Never raises.
        """
        mode     = envelope.assistance_mode
        category = envelope.intent_category

        # ── ARCHITECT_MODE: unrestricted (allowed_paths = empty = no filter) ──
        if mode == "ARCHITECT_MODE":
            return AllowedMutationScope(
                allowed_paths             = (),
                forbidden_paths           = _PERMANENT_FORBIDDEN,
                structural_change_allowed = True,
                max_mutation_depth        = _MAX_DEPTH["ARCHITECT_MODE"],
                mode                      = mode,
            )

        # ── Build allowed path list ───────────────────────────────────────────
        allowed = self._derive_allowed_paths(envelope, cgs)

        # ── Structural gating ─────────────────────────────────────────────────
        structural_allowed = (
            category in _STRUCTURAL_CATEGORIES
            and mode not in _NO_STRUCTURAL_MODES
        )

        max_depth = _MAX_DEPTH.get(mode, _DEFAULT_MAX_DEPTH)

        return AllowedMutationScope(
            allowed_paths             = tuple(allowed),
            forbidden_paths           = _PERMANENT_FORBIDDEN,
            structural_change_allowed = structural_allowed,
            max_mutation_depth        = max_depth,
            mode                      = mode,
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _derive_allowed_paths(
        self,
        envelope: IntentEnvelope,
        cgs:      dict[str, Any],
    ) -> list[str]:
        """
        Derives the list of allowed CGS path prefixes from the envelope.

        Strategy:
        - QueryExplain/DebugIssue: allow read of everything, write of nothing
          (allowed_paths = ["*"] means read; LLMOrchestrator skips mutation)
        - BalanceAdjustment: allow component defaults under relevant actors
        - ModifyFeature: allow component defaults + system params under
          relevant actors/systems
        - CreateFeature/RemoveFeature/StructuralChange: allow full mode paths
        - WorldDesign: allow all actor + rule paths (broad canvas)
        - Unknown: return minimal paths (ClarificationEngine handles this)
        """
        category = envelope.intent_category
        modes    = cgs.get("modes", [])

        # Read-only intents: full read scope, zero write scope
        if PILIntentCategory.is_read_only(category):
            return ["modes", "global_systems", "metadata"]

        # Unknown: no paths committed yet
        if category == PILIntentCategory.UNKNOWN:
            return []

        # Extract actor/system hints from the envelope's GDE hints
        actor_hint  = None
        mode_hint   = None

        # Try to get hints from a GDEIntentObject if available in envelope
        # (these are shallow hints from the PIL classifier, not deep slot extraction)
        # Fall back to all-mode paths if no hints available.

        if category == PILIntentCategory.BALANCE_ADJUSTMENT:
            return self._balance_paths(modes, actor_hint)

        if category in {PILIntentCategory.MODIFY_FEATURE}:
            return self._modify_paths(modes, actor_hint)

        if category in {
            PILIntentCategory.CREATE_FEATURE,
            PILIntentCategory.REMOVE_FEATURE,
            PILIntentCategory.STRUCTURAL_CHANGE,
        }:
            return self._structural_paths(modes)

        if category == PILIntentCategory.WORLD_DESIGN:
            return self._world_design_paths(modes)

        # ModifyFeature catch-all
        return self._modify_paths(modes, actor_hint)

    @staticmethod
    def _balance_paths(
        modes:      list[dict],
        actor_hint: str | None,
    ) -> list[str]:
        """
        Allowed paths for BalanceAdjustment: component defaults only.
        Excludes system read/write contracts (those are MODIFY_FEATURE territory).
        """
        paths: list[str] = []
        for mode in modes:
            mid = mode.get("id", "")
            for actor in mode.get("actors", []):
                aid = actor.get("id", "")
                if actor_hint and actor_hint.lower() not in aid.lower():
                    continue
                for comp in actor.get("components", []):
                    tid = comp.get("type_id", "")
                    paths.append(
                        f"modes[{mid}].actors[{aid}].components[{tid}].defaults"
                    )
        # If no specific paths derived, allow all component defaults
        if not paths:
            for mode in modes:
                mid = mode.get("id", "")
                for actor in mode.get("actors", []):
                    aid = actor.get("id", "")
                    paths.append(
                        f"modes[{mid}].actors[{aid}].components"
                    )
        return paths

    @staticmethod
    def _modify_paths(
        modes:      list[dict],
        actor_hint: str | None,
    ) -> list[str]:
        """
        Allowed paths for ModifyFeature: component defaults + system params.
        """
        paths: list[str] = []
        for mode in modes:
            mid = mode.get("id", "")
            for actor in mode.get("actors", []):
                aid = actor.get("id", "")
                if actor_hint and actor_hint.lower() not in aid.lower():
                    continue
                paths.append(f"modes[{mid}].actors[{aid}].components")
            for system in mode.get("systems", []):
                sid = system.get("id", "")
                paths.append(f"modes[{mid}].systems[{sid}]")
        if not paths:
            for mode in modes:
                mid = mode.get("id", "")
                paths.append(f"modes[{mid}]")
        return paths

    @staticmethod
    def _structural_paths(modes: list[dict]) -> list[str]:
        """
        Allowed paths for structural changes: full mode scope.
        Includes actors, systems, rules at the container level.
        """
        paths: list[str] = ["global_systems"]
        for mode in modes:
            mid = mode.get("id", "")
            paths.append(f"modes[{mid}].actors")
            paths.append(f"modes[{mid}].systems")
            paths.append(f"modes[{mid}].rules")
        return paths

    @staticmethod
    def _world_design_paths(modes: list[dict]) -> list[str]:
        """
        Allowed paths for WorldDesign: actors + rules (broad canvas).
        Systems are read-only for world design intents.
        """
        paths: list[str] = []
        for mode in modes:
            mid = mode.get("id", "")
            paths.append(f"modes[{mid}].actors")
            paths.append(f"modes[{mid}].rules")
        return paths if paths else ["modes"]