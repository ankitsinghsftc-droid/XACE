"""
destructive_change_guard.py — DestructiveChangeGuard
=====================================================
Prevents accidental deletion of components or systems that are
architecturally essential to the game's basic operation.

## What It Checks

    1. Core Component Protection
       Some UCL components are "core" — their removal breaks fundamental
       game mechanics. Deletion of core components is blocked in
       FULLY_ASSISTED and COLLABORATIVE modes:
           type_id=1   COMP_TRANSFORM_V1  — every actor needs a position
           type_id=2   COMP_IDENTITY_V1   — entity identity
           type_id=5   COMP_VELOCITY_V1   — all movement depends on this
           type_id=6   COMP_INPUT_V1      — required for Human-controlled actors

    2. Last-Instance Protection
       If removing an actor would leave a mode with zero actors, block it.
       A game mode with no actors is likely an error.

    3. System Cascade Check
       If removing a system would orphan other systems (break their
       depends_on chain), this is a cascade error that blocks commit.
       "Orphan" = a system whose depends_on references the removed system
       and has no other dependency to fall back to.

    4. Rule Integrity
       Removing a rule that is referenced by another rule's condition
       or effect expression is flagged as a warning.

## Severity

    Core component removal → BLOCK
    Last actor in mode    → BLOCK
    System orphan         → BLOCK
    Rule reference broken → WARNING (rules are advisory)
    ADVANCED/ARCHITECT_MODE: BLOCK → WARNING (expert override possible)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from scope_boundary_guard import GuardResult
from mutation_planner import CommittedMutationPlan

import re


# ── Core component type IDs ───────────────────────────────────────────────────

_CORE_COMPONENT_TYPE_IDS: frozenset[int] = frozenset({1, 2, 5, 6})

_CORE_COMPONENT_NAMES: dict[int, str] = {
    1: "COMP_TRANSFORM_V1 (actor position/rotation/scale)",
    2: "COMP_IDENTITY_V1  (entity identity and type)",
    5: "COMP_VELOCITY_V1  (movement velocity)",
    6: "COMP_INPUT_V1     (human input processing)",
}

# Modes where block → warning (expert can override)
_EXPERT_MODES: frozenset[str] = frozenset({"ADVANCED", "ARCHITECT_MODE"})

_REMOVE_OPS: frozenset[str] = frozenset({
    "REMOVE_ACTOR", "REMOVE_COMPONENT", "REMOVE_SYSTEM", "REMOVE_RULE"
})


class DestructiveChangeGuard:
    """
    Guards against accidental deletion of essential CGS elements.
    Stateless, deterministic.
    """

    def check(
        self,
        plan:        CommittedMutationPlan,
        current_cgs: dict[str, Any],
        mode:        str = "COLLABORATIVE",
    ) -> GuardResult:
        findings: list[str] = []
        severity = "none"

        for op in plan.ordered_ops:
            if op.op not in _REMOVE_OPS:
                continue

            if op.op == "REMOVE_COMPONENT":
                f, s = self._check_core_component(op, mode)
                findings.extend(f)
                severity = _escalate(severity, s)

            elif op.op == "REMOVE_ACTOR":
                f, s = self._check_last_actor(op, current_cgs, mode)
                findings.extend(f)
                severity = _escalate(severity, s)

            elif op.op == "REMOVE_SYSTEM":
                f, s = self._check_system_orphan(op, current_cgs, mode)
                findings.extend(f)
                severity = _escalate(severity, s)

            elif op.op == "REMOVE_RULE":
                f, s = self._check_rule_reference(op, current_cgs)
                findings.extend(f)
                severity = _escalate(severity, s)

        return GuardResult(
            guard    = "destructive_change",
            passed   = severity not in {"block"},
            severity = severity,
            findings = findings,
        )

    @staticmethod
    def _check_core_component(
        op:   Any,
        mode: str,
    ) -> tuple[list[str], str]:
        if op.type_id not in _CORE_COMPONENT_TYPE_IDS:
            return [], "none"

        name      = _CORE_COMPONENT_NAMES.get(op.type_id, f"type_id={op.type_id}")
        base_sev  = "warning" if mode in _EXPERT_MODES else "block"
        qualifier = " (expert override — proceed with caution)" if mode in _EXPERT_MODES else ""
        return [
            f"{'WARNING' if base_sev == 'warning' else 'BLOCKED'}: "
            f"Removing core component {name} from actor '{op.actor_id}'. "
            f"This will break fundamental game mechanics.{qualifier}"
        ], base_sev

    @staticmethod
    def _check_last_actor(
        op:          Any,
        current_cgs: dict[str, Any],
        mode:        str,
    ) -> tuple[list[str], str]:
        aid = op.actor_id or ""
        m   = re.match(r'^modes\[([^\]]+)\]', op.path)
        if not m:
            return [], "none"
        mid = m.group(1)

        # Count actors in the mode
        actor_count = 0
        for mode_dict in current_cgs.get("modes", []):
            if mode_dict.get("id") == mid:
                actor_count = len(mode_dict.get("actors", []))
                break

        if actor_count <= 1:
            base_sev = "warning" if mode in _EXPERT_MODES else "block"
            return [
                f"{'WARNING' if base_sev == 'warning' else 'BLOCKED'}: "
                f"Removing actor '{aid}' would leave mode '{mid}' with no actors. "
                f"A mode with zero actors is likely an error."
            ], base_sev

        return [], "none"

    @staticmethod
    def _check_system_orphan(
        op:          Any,
        current_cgs: dict[str, Any],
        mode:        str,
    ) -> tuple[list[str], str]:
        # Find the system being removed
        m = re.match(r'^modes\[([^\]]+)\]\.systems\[([^\]]+)\]', op.path)
        if not m:
            return [], "none"
        mid, sid = m.group(1), m.group(2)

        # Find systems that depend on this one
        orphans: list[str] = []
        for mode_dict in current_cgs.get("modes", []):
            if mode_dict.get("id") != mid:
                continue
            for sys in mode_dict.get("systems", []):
                if sid in sys.get("depends_on", []) and sys.get("id") != sid:
                    orphans.append(sys.get("id", "?"))

        if not orphans:
            return [], "none"

        base_sev = "warning" if mode in _EXPERT_MODES else "block"
        return [
            f"{'WARNING' if base_sev == 'warning' else 'BLOCKED'}: "
            f"Removing system '{sid}' would orphan: {', '.join(orphans)}. "
            f"These systems depend on '{sid}' via depends_on. "
            f"Update their depends_on before removing."
        ], base_sev

    @staticmethod
    def _check_rule_reference(
        op:          Any,
        current_cgs: dict[str, Any],
    ) -> tuple[list[str], str]:
        m = re.match(r'^modes\[([^\]]+)\]\.rules\[([^\]]+)\]', op.path)
        if not m:
            return [], "none"
        mid, rid = m.group(1), m.group(2)

        # Check if any other rule's condition/effect references this rule
        refs: list[str] = []
        for mode_dict in current_cgs.get("modes", []):
            if mode_dict.get("id") != mid:
                continue
            for rule in mode_dict.get("rules", []):
                if rule.get("id") == rid:
                    continue
                cond   = rule.get("condition", "")
                effect = rule.get("effect", "")
                if rid in cond or rid in effect:
                    refs.append(rule.get("id", "?"))

        if not refs:
            return [], "none"

        return [
            f"WARNING: Rule '{rid}' is referenced in rules: {', '.join(refs)}. "
            f"Removing it may break those rules' conditions or effects."
        ], "warning"


# ── Severity escalation helper ────────────────────────────────────────────────

def _escalate(current: str, new: str) -> str:
    """Returns the more severe of two severity strings."""
    order = {"none": 0, "warning": 1, "block": 2}
    return current if order.get(current, 0) >= order.get(new, 0) else new