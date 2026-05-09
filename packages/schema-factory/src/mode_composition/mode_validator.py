"""
mode_validator.py — ModeValidator
===================================
Validates individual game mode definitions from the CGS before the
ModeCompositionEngine merges them into the compiled schema.

## What a Mode Is
A CGS mode represents a distinct gameplay configuration — e.g. "survival",
"creative", "tutorial", "pvp_arena". Each mode has its own actor roster,
system list, and rules, layered on top of the global base schema.

## CGS Mode Dict Format
    {
        "id":          "mode_survival",
        "display_name":"Survival",
        "is_default":  True,          # at most one mode may be default
        "actors": [
            {"id": "actor_player", "actor_type": "PLAYER", "components": [...]}
        ],
        "systems": [
            {"id": "sys_hunger", "phase": "Simulation", "reads": [200], "writes": [200]}
        ],
        "rules": [
            {"id": "rule_starvation", "condition": "...", "effect": "..."}
        ],
    }

## Validation Rules
    Rule M1 — Mode ID is non-empty and unique across all modes
    Rule M2 — display_name is non-empty (soft warning)
    Rule M3 — actors list is a list (may be empty)
    Rule M4 — Each actor has a non-empty unique ID within this mode
    Rule M5 — Each actor references only registered component type_ids
    Rule M6 — systems list is a list (may be empty)
    Rule M7 — Each system has a non-empty unique ID within this mode
    Rule M8 — Each system phase is in VALID_PHASES
    Rule M9 — rules list is a list (may be empty)
    Rule M10— Each rule has a non-empty unique ID within this mode
    Rule M11— Exactly one mode across the full mode list is default (I3)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from ..system_registry.system_definition_registry import VALID_PHASES

if TYPE_CHECKING:
    from ..component_registry.component_definition_registry import (
        ComponentDefinitionRegistry,
    )


# ── Validation Result ─────────────────────────────────────────────────────────

@dataclass
class ModeValidationResult:
    """
    Result of validating one mode definition.

    Attributes
    ----------
    mode_id : str
        The ID of the mode that was validated (or "<missing>" if absent).
    errors : list[str]
        Hard failures — mode must not be compiled if non-empty.
    warnings : list[str]
        Soft issues — mode can compile but issues should be surfaced.
    """

    mode_id:  str
    errors:   list[str]
    warnings: list[str]

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    def __repr__(self) -> str:
        status = "VALID" if self.is_valid else f"INVALID ({len(self.errors)} errors)"
        return f"ModeValidationResult(mode={self.mode_id!r}, {status})"


# ── Mode Validator ────────────────────────────────────────────────────────────

class ModeValidator:
    """
    Validates CGS mode dicts individually and as a set.

    Per-mode validation: structural correctness, component refs, system phases.
    Cross-mode validation: unique IDs, exactly one default mode.

    Usage
    -----
        validator = ModeValidator(component_registry)

        # Validate individually
        result = validator.validate_one(mode_dict)

        # Validate the full set (includes cross-mode rules M1, M11)
        results = validator.validate_all(modes_list)
        errors  = validator.collect_errors(modes_list)
    """

    def __init__(self, component_registry: "ComponentDefinitionRegistry") -> None:
        self._registry = component_registry

    # ── Public API ────────────────────────────────────────────────────────────

    def validate_one(self, mode: dict[str, Any]) -> ModeValidationResult:
        """
        Validates a single mode dict in isolation (rules M2–M10).
        Does NOT check cross-mode uniqueness or default-mode count (M1, M11).
        """
        errors:   list[str] = []
        warnings: list[str] = []
        mode_id = mode.get("id", "")

        if not mode_id:
            errors.append(
                "Mode definition has an empty or missing 'id'. "
                "Every mode must have a unique non-empty ID."
            )
            return ModeValidationResult(
                mode_id="<missing>", errors=errors, warnings=warnings
            )

        self._rule_display_name(mode, mode_id, warnings)
        self._rule_actors(mode, mode_id, errors, warnings)
        self._rule_systems(mode, mode_id, errors)
        self._rule_rules(mode, mode_id, errors)

        return ModeValidationResult(mode_id=mode_id, errors=errors, warnings=warnings)

    def validate_all(
        self, modes: list[dict[str, Any]]
    ) -> list[ModeValidationResult]:
        """
        Validates all modes including cross-mode rules (M1, M11).
        Returns one result per mode in input order.
        """
        results = [self.validate_one(m) for m in modes]

        # M1: Unique mode IDs across the full set
        seen_ids: dict[str, int] = {}
        for i, mode in enumerate(modes):
            mid = mode.get("id", "")
            if not mid:
                continue
            if mid in seen_ids:
                results[i].errors.append(
                    f"Mode ID '{mid}' is duplicated "
                    f"(also appears at position {seen_ids[mid]}). "
                    f"Every mode must have a unique ID."
                )
            else:
                seen_ids[mid] = i

        # M11: Exactly one default mode
        default_indices = [
            i for i, m in enumerate(modes) if m.get("is_default", False)
        ]
        if not default_indices:
            # Attach to the first mode result, or create a synthetic one
            target = results[0] if results else None
            if target:
                target.errors.append(
                    "No mode is marked 'is_default: true'. "
                    "Exactly one mode must be the default. "
                    "The default mode is loaded when the game starts."
                )
        elif len(default_indices) > 1:
            for idx in default_indices:
                results[idx].errors.append(
                    f"Multiple modes are marked 'is_default: true' "
                    f"(found {len(default_indices)} defaults). "
                    f"Exactly one mode must be the default."
                )

        return results

    def collect_errors(self, modes: list[dict[str, Any]]) -> list[str]:
        """
        Validates all modes and returns a flat list of all error strings.
        Empty list means all modes are valid.
        """
        all_errors: list[str] = []
        for result in self.validate_all(modes):
            all_errors.extend(result.errors)
        return all_errors

    # ── Per-Mode Rules ────────────────────────────────────────────────────────

    @staticmethod
    def _rule_display_name(
        mode:     dict[str, Any],
        mode_id:  str,
        warnings: list[str],
    ) -> None:
        """M2 — display_name should be non-empty."""
        display = mode.get("display_name", "")
        if not display or not display.strip():
            warnings.append(
                f"[{mode_id}] Missing 'display_name'. "
                f"The builder UI uses display_name to label this mode. "
                f"Provide a short human-readable name."
            )

    def _rule_actors(
        self,
        mode:     dict[str, Any],
        mode_id:  str,
        errors:   list[str],
        warnings: list[str],
    ) -> None:
        """M3–M5 — actors is a list; IDs unique; component refs valid."""
        actors = mode.get("actors", [])
        if not isinstance(actors, list):
            errors.append(
                f"[{mode_id}] 'actors' must be a list, "
                f"got {type(actors).__name__}."
            )
            return

        seen: set[str] = set()
        for actor in actors:
            if not isinstance(actor, dict):
                errors.append(
                    f"[{mode_id}] Each actor entry must be a dict, "
                    f"got {type(actor).__name__}."
                )
                continue

            actor_id = actor.get("id", "")
            if not actor_id:
                errors.append(
                    f"[{mode_id}] Actor entry missing 'id'. "
                    f"Every actor must have a unique non-empty ID."
                )
                continue

            if actor_id in seen:
                errors.append(
                    f"[{mode_id}] Duplicate actor ID '{actor_id}' within mode. "
                    f"Actor IDs must be unique within each mode."
                )
            else:
                seen.add(actor_id)

            # M5: Component type_ids must be registered
            for comp in actor.get("components", []):
                if not isinstance(comp, dict):
                    continue
                type_id = comp.get("type_id")
                if isinstance(type_id, int) and not self._registry.has_component(type_id):
                    errors.append(
                        f"[{mode_id}] Actor '{actor_id}' references "
                        f"component type_id {type_id} which is not in the "
                        f"CompositeComponentRegistry. "
                        f"Declare the domain in game_config.yaml."
                    )

    @staticmethod
    def _rule_systems(
        mode:    dict[str, Any],
        mode_id: str,
        errors:  list[str],
    ) -> None:
        """M6–M8 — systems is a list; IDs unique; phases valid."""
        systems = mode.get("systems", [])
        if not isinstance(systems, list):
            errors.append(
                f"[{mode_id}] 'systems' must be a list, "
                f"got {type(systems).__name__}."
            )
            return

        seen: set[str] = set()
        for sys in systems:
            if not isinstance(sys, dict):
                errors.append(
                    f"[{mode_id}] Each system entry must be a dict."
                )
                continue

            sys_id = sys.get("id", "")
            if not sys_id:
                errors.append(
                    f"[{mode_id}] System entry missing 'id'."
                )
                continue

            if sys_id in seen:
                errors.append(
                    f"[{mode_id}] Duplicate system ID '{sys_id}' within mode."
                )
            else:
                seen.add(sys_id)

            phase = sys.get("phase", "")
            if phase and phase not in VALID_PHASES:
                errors.append(
                    f"[{mode_id}] System '{sys_id}' has invalid phase "
                    f"'{phase}'. Valid phases: {sorted(VALID_PHASES)}"
                )

    @staticmethod
    def _rule_rules(
        mode:    dict[str, Any],
        mode_id: str,
        errors:  list[str],
    ) -> None:
        """M9–M10 — rules is a list; IDs unique."""
        rules = mode.get("rules", [])
        if not isinstance(rules, list):
            errors.append(
                f"[{mode_id}] 'rules' must be a list, "
                f"got {type(rules).__name__}."
            )
            return

        seen: set[str] = set()
        for rule in rules:
            if not isinstance(rule, dict):
                errors.append(
                    f"[{mode_id}] Each rule entry must be a dict."
                )
                continue

            rule_id = rule.get("id", "")
            if not rule_id:
                errors.append(
                    f"[{mode_id}] Rule entry missing 'id'."
                )
                continue

            if rule_id in seen:
                errors.append(
                    f"[{mode_id}] Duplicate rule ID '{rule_id}' within mode."
                )
            else:
                seen.add(rule_id)