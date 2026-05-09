"""
mode_composition_engine.py — ModeCompositionEngine
====================================================
Merges the CGS global base schema with each mode's specific overrides
to produce a fully resolved ComposedMode per game mode.

## What Composition Does
The CGS has two levels of definition:
    1. global_systems — systems active in EVERY mode (e.g. InputSystem)
    2. modes[*]       — per-mode actors, systems, and rules

Composition merges these into a single flat ComposedMode per mode so
downstream stages (BlueprintCompiler, SystemDefinitionRegistry) work
with one unified view rather than two levels.

## Merge Rules
    Actors:  Per-mode only. Global actors are not supported — every actor
             is tied to the mode(s) it exists in. An actor with an empty
             mode_scope appears in all modes (see EntityBlueprint.mode_scope).

    Systems: Global systems appear in every ComposedMode. Per-mode systems
             are added on top. If a mode system has the same ID as a global
             system, the mode system OVERRIDES the global one (mode wins).
             Override is surfaced as a warning — intentional overrides are
             valid but accidental ones are a common mistake.

    Rules:   Per-mode only. Rules are always mode-scoped.

## Mode Isolation
Actors and rules from one mode must not bleed into another. The engine
validates this after composition: no actor or rule ID appears in more
than one ComposedMode unless it was explicitly declared in both.

## Determinism (D11)
All list fields in ComposedMode are sorted by ID before being stored.
Same CGS → identical ComposedMode for each mode, always.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Composed Mode ─────────────────────────────────────────────────────────────

@dataclass
class ComposedMode:
    """
    Fully resolved schema for one game mode after base + override merge.

    This is the direct input to BlueprintCompiler and SystemDefinitionRegistry
    during SchemaFactory.compile(). It is not stored in the CompiledSchemaPackage —
    the compiled outputs (BlueprintRegistry, SystemDefinitionRegistry) are.

    Attributes
    ----------
    mode_id : str
        Mode identifier. Matches the CGS mode dict "id" field.
    display_name : str
        Human-readable mode name.
    is_default : bool
        True for the mode loaded at game start.
    actors : list[dict]
        Fully merged actor definitions for this mode, sorted by ID (D11).
    systems : list[dict]
        Fully merged system definitions (global + mode override), sorted (D11).
    rules : list[dict]
        Mode-specific rule definitions, sorted by ID (D11).
    overridden_system_ids : list[str]
        System IDs where a mode-level definition overrode a global definition.
        Surfaced as warnings during compilation.
    """

    mode_id:                str
    display_name:           str
    is_default:             bool
    actors:                 list[dict[str, Any]] = field(default_factory=list)
    systems:                list[dict[str, Any]] = field(default_factory=list)
    rules:                  list[dict[str, Any]] = field(default_factory=list)
    overridden_system_ids:  list[str]            = field(default_factory=list)

    def actor_ids(self) -> list[str]:
        return [a["id"] for a in self.actors]

    def system_ids(self) -> list[str]:
        return [s["id"] for s in self.systems]

    def rule_ids(self) -> list[str]:
        return [r["id"] for r in self.rules]

    def get_actor(self, actor_id: str) -> dict[str, Any] | None:
        for a in self.actors:
            if a.get("id") == actor_id:
                return a
        return None

    def get_system(self, system_id: str) -> dict[str, Any] | None:
        for s in self.systems:
            if s.get("id") == system_id:
                return s
        return None

    def __repr__(self) -> str:
        default_mark = " [default]" if self.is_default else ""
        return (
            f"ComposedMode(id={self.mode_id!r}{default_mark}, "
            f"actors={len(self.actors)}, systems={len(self.systems)}, "
            f"rules={len(self.rules)})"
        )


# ── Composition Warning ───────────────────────────────────────────────────────

@dataclass
class CompositionWarning:
    """A non-fatal issue detected during mode composition."""
    mode_id:  str
    message:  str


# ── Composition Result ────────────────────────────────────────────────────────

@dataclass
class CompositionResult:
    """
    Output of ModeCompositionEngine.compose_all().

    Attributes
    ----------
    composed_modes : list[ComposedMode]
        One ComposedMode per CGS mode, in CGS declaration order.
    default_mode_id : str | None
        ID of the default mode, or None if none was marked.
    warnings : list[CompositionWarning]
        Non-fatal issues (system overrides, empty mode actors, etc.)
    """

    composed_modes:  list[ComposedMode]
    default_mode_id: str | None
    warnings:        list[CompositionWarning] = field(default_factory=list)

    def get_mode(self, mode_id: str) -> ComposedMode | None:
        for m in self.composed_modes:
            if m.mode_id == mode_id:
                return m
        return None

    def all_mode_ids(self) -> list[str]:
        return [m.mode_id for m in self.composed_modes]

    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    def warning_messages(self) -> list[str]:
        return [w.message for w in self.warnings]


# ── Mode Composition Engine ───────────────────────────────────────────────────

class ModeCompositionEngine:
    """
    Merges global base schema with per-mode overrides.

    Stateless — one call to compose_all() per SchemaFactory.compile() run.

    Usage
    -----
        result = ModeCompositionEngine.compose_all(cgs)
        for composed in result.composed_modes:
            blueprint_compiler.compile_all(composed.actors, schema_version)
            system_registry.register_all(composed.systems)
    """

    @classmethod
    def compose_all(cls, cgs: dict[str, Any]) -> CompositionResult:
        """
        Composes every mode in the CGS with the global base schema.

        Parameters
        ----------
        cgs : dict[str, Any]
            The full canonical CGS dict.

        Returns
        -------
        CompositionResult
            Contains one ComposedMode per mode, plus warnings.
        """
        global_systems = cgs.get("global_systems", [])
        modes          = cgs.get("modes", [])
        warnings:        list[CompositionWarning] = []
        composed_modes:  list[ComposedMode]       = []
        default_mode_id: str | None               = None

        for mode_dict in modes:
            composed, mode_warnings = cls._compose_one(mode_dict, global_systems)
            composed_modes.append(composed)
            warnings.extend(mode_warnings)
            if composed.is_default:
                default_mode_id = composed.mode_id

        # Validate mode isolation post-composition (D11 — sorted for determinism)
        isolation_warnings = cls._validate_isolation(composed_modes)
        warnings.extend(isolation_warnings)

        return CompositionResult(
            composed_modes=composed_modes,
            default_mode_id=default_mode_id,
            warnings=warnings,
        )

    @classmethod
    def compose_one(
        cls,
        mode_dict:      dict[str, Any],
        global_systems: list[dict[str, Any]],
    ) -> tuple[ComposedMode, list[CompositionWarning]]:
        """
        Composes a single mode dict with the global systems list.
        Public entry point for single-mode recompilation (after a mode mutation).
        """
        return cls._compose_one(mode_dict, global_systems)

    # ── Internal ──────────────────────────────────────────────────────────────

    @classmethod
    def _compose_one(
        cls,
        mode_dict:      dict[str, Any],
        global_systems: list[dict[str, Any]],
    ) -> tuple[ComposedMode, list[CompositionWarning]]:
        """Merges one mode dict with the global system list."""
        mode_id      = mode_dict.get("id", "")
        display_name = mode_dict.get("display_name", mode_id)
        is_default   = bool(mode_dict.get("is_default", False))
        warnings:    list[CompositionWarning] = []

        # ── Actors (mode-only, sorted by ID for D11) ──────────────────────────
        actors = sorted(
            mode_dict.get("actors", []),
            key=lambda a: a.get("id", ""),
        )
        if not actors:
            warnings.append(CompositionWarning(
                mode_id=mode_id,
                message=(
                    f"[{mode_id}] Mode has no actors defined. "
                    f"A game with no actors will produce an empty world."
                ),
            ))

        # ── Systems (global + mode override, sorted by ID for D11) ───────────
        global_sys_map: dict[str, dict[str, Any]] = {
            s["id"]: s for s in global_systems if "id" in s
        }
        mode_sys_map: dict[str, dict[str, Any]] = {
            s["id"]: s
            for s in mode_dict.get("systems", [])
            if "id" in s
        }

        # Detect overrides before merging
        overridden: list[str] = sorted(
            sid for sid in mode_sys_map if sid in global_sys_map
        )
        for sid in overridden:
            warnings.append(CompositionWarning(
                mode_id=mode_id,
                message=(
                    f"[{mode_id}] Mode system '{sid}' overrides a global system "
                    f"with the same ID. The mode-specific definition takes precedence. "
                    f"Verify this override is intentional."
                ),
            ))

        # Merge: start with globals, then apply mode overrides (mode wins)
        merged_sys_map = {**global_sys_map, **mode_sys_map}
        systems = sorted(merged_sys_map.values(), key=lambda s: s.get("id", ""))

        # ── Rules (mode-only, sorted by ID for D11) ───────────────────────────
        rules = sorted(
            mode_dict.get("rules", []),
            key=lambda r: r.get("id", ""),
        )

        composed = ComposedMode(
            mode_id=mode_id,
            display_name=display_name,
            is_default=is_default,
            actors=actors,
            systems=systems,
            rules=rules,
            overridden_system_ids=overridden,
        )
        return composed, warnings

    @staticmethod
    def _validate_isolation(
        composed_modes: list[ComposedMode],
    ) -> list[CompositionWarning]:
        """
        Validates that actor and rule IDs do not accidentally bleed across modes.

        A shared actor ID across modes is valid ONLY when the actor definition
        is intentionally identical (e.g. the player actor appears in every mode).
        We flag it as a warning so the designer can confirm intent.
        Systems are exempt — global systems intentionally appear in all modes.
        """
        warnings: list[CompositionWarning] = []

        # Build actor_id → [mode_ids] map
        actor_to_modes: dict[str, list[str]] = {}
        for composed in composed_modes:
            for actor_id in composed.actor_ids():
                actor_to_modes.setdefault(actor_id, []).append(composed.mode_id)

        # Rule_id → [mode_ids] map
        rule_to_modes: dict[str, list[str]] = {}
        for composed in composed_modes:
            for rule_id in composed.rule_ids():
                rule_to_modes.setdefault(rule_id, []).append(composed.mode_id)

        # Warn on shared actor IDs (sorted for D11)
        for actor_id, mode_ids in sorted(actor_to_modes.items()):
            if len(mode_ids) > 1:
                warnings.append(CompositionWarning(
                    mode_id=mode_ids[0],
                    message=(
                        f"Actor '{actor_id}' appears in multiple modes: "
                        f"{sorted(mode_ids)}. "
                        f"If intentional, ensure the actor definition is "
                        f"consistent across modes."
                    ),
                ))

        # Warn on shared rule IDs (sorted for D11)
        for rule_id, mode_ids in sorted(rule_to_modes.items()):
            if len(mode_ids) > 1:
                warnings.append(CompositionWarning(
                    mode_id=mode_ids[0],
                    message=(
                        f"Rule '{rule_id}' appears in multiple modes: "
                        f"{sorted(mode_ids)}. "
                        f"Rules are mode-scoped — verify this is intentional."
                    ),
                ))

        return warnings