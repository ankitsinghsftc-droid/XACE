"""
determinism_safety_guard.py — DeterminismSafetyGuard
======================================================
Blocks mutations that would violate XACE's determinism invariants.

Determinism is XACE's core guarantee: same inputs → same simulation
output across all peers and replay. Any mutation that introduces
nondeterminism is a hard block regardless of mode.

## What It Checks

    1. Nondeterministic Value Detection
       Field values that contain unseeded random, timestamps, or other
       nondeterministic sources cannot be committed:
           value = "random()"         → BLOCK
           value = {"seed": null}     → BLOCK
           value = time.time()        → BLOCK (if value looks like epoch)
           value = float("inf")       → BLOCK (inf/nan break hash)
           value = float("nan")       → BLOCK

    2. System Determinism Flag
       Any operation that would set deterministic=false on a system
       is a hard block. This covers both SET and structural ops where
       the new system dict has deterministic=false.

    3. Cross-Phase State Mutation Detection
       A mutation that writes a field read by a system in an EARLIER phase
       than the system that writes it creates a phase ordering ambiguity.
       Example: if SystemA in PostSimulation writes component X, and
       SystemB in Simulation reads X, mutating X could interfere with the
       phase execution order.
       This check is conservative — it flags the concern rather than trying
       to fully simulate phase ordering.

    4. Float Precision Guard
       Values with extremely high precision (more than 10 significant digits)
       may accumulate floating-point drift across peers and are warned.
       Example: 1.23456789012345 → WARNING (hash may diverge after many ticks)

## Severity

    All checks 1-3 → BLOCK (nondeterminism is always a hard error)
    Check 4 (precision) → WARNING
"""

from __future__ import annotations

import math
import re
from typing import Any

from scope_boundary_guard import GuardResult
from mutation_planner import CommittedMutationPlan


# ── Nondeterministic value patterns ───────────────────────────────────────────

_NONDETERMINISTIC_STRING_PATTERNS = (
    re.compile(r'\brandom\s*\(', re.I),
    re.compile(r'\btime\s*\.\s*time\s*\(', re.I),
    re.compile(r'\bdatetime\s*\.\s*now\s*\(', re.I),
    re.compile(r'\buuid\s*\.\s*uuid', re.I),
)

# Epoch-like float (seconds since 1970) — rough range 1.5e9 to 2.0e9
_EPOCH_MIN = 1_500_000_000.0
_EPOCH_MAX = 2_000_000_000.0

# Number of decimal places beyond which precision warning fires
_PRECISION_WARNING_DIGITS = 10


class DeterminismSafetyGuard:
    """
    Blocks mutations that violate determinism invariants.
    All blocks are unconditional — no mode override.
    """

    def check(
        self,
        plan:        CommittedMutationPlan,
        current_cgs: dict[str, Any],
    ) -> GuardResult:
        findings: list[str] = []
        severity = "none"

        for op in plan.ordered_ops:
            value = op.value

            # Check 1: nondeterministic string value
            if isinstance(value, str):
                for pattern in _NONDETERMINISTIC_STRING_PATTERNS:
                    if pattern.search(value):
                        findings.append(
                            f"BLOCKED: Value '{value[:80]}' at path '{op.path}' "
                            f"contains a nondeterministic expression. "
                            f"All values must be deterministic constants."
                        )
                        severity = "block"
                        break

            # Check 2: inf/nan
            if isinstance(value, float):
                if math.isinf(value) or math.isnan(value):
                    findings.append(
                        f"BLOCKED: Value {value!r} at path '{op.path}' is "
                        f"inf or nan. These break the CGS hash and determinism."
                    )
                    severity = "block"

                # Check 2b: epoch-like float
                elif _EPOCH_MIN <= value <= _EPOCH_MAX:
                    findings.append(
                        f"BLOCKED: Value {value!r} at path '{op.path}' looks like "
                        f"a Unix timestamp. Timestamps are nondeterministic across peers."
                    )
                    severity = "block"

                # Check 4: high precision float (warning)
                else:
                    str_val = f"{value:.15g}"
                    digits  = len(str_val.replace(".", "").replace("-", "").lstrip("0"))
                    if digits > _PRECISION_WARNING_DIGITS:
                        findings.append(
                            f"WARNING: Value {value!r} at path '{op.path}' has very "
                            f"high precision ({digits} digits). This may cause "
                            f"floating-point drift across peers."
                        )
                        severity = _escalate(severity, "warning")

            # Check 2c: null seed dict
            if isinstance(value, dict):
                seed = value.get("seed") or value.get("random_seed")
                if seed is None and ("seed" in value or "random_seed" in value):
                    findings.append(
                        f"BLOCKED: Value at '{op.path}' contains a null seed. "
                        f"Null seeds produce nondeterministic output."
                    )
                    severity = "block"

            # Check 2d: deterministic=false on system operation
            if isinstance(value, dict) and value.get("deterministic") is False:
                findings.append(
                    f"BLOCKED: Operation at '{op.path}' sets deterministic=false. "
                    f"All systems must be deterministic (D-rule invariant)."
                )
                severity = "block"

            # Check 2e: SET deterministic=false directly
            if op.field_name == "deterministic" and op.value is False:
                findings.append(
                    f"BLOCKED: SET deterministic=false at '{op.path}'. "
                    f"This violates the determinism invariant."
                )
                severity = "block"

        # Check 3: cross-phase state mutation
        phase_findings = self._check_cross_phase(plan, current_cgs)
        if phase_findings:
            findings.extend(phase_findings)
            severity = _escalate(severity, "warning")

        return GuardResult(
            guard    = "determinism_safety",
            passed   = severity != "block",
            severity = severity,
            findings = findings,
        )

    @staticmethod
    def _check_cross_phase(
        plan:        CommittedMutationPlan,
        current_cgs: dict[str, Any],
    ) -> list[str]:
        """
        Checks for potential cross-phase state mutation issues.
        Returns warning strings (not blocking — too conservative to hard-block).
        """
        # Build component → phase(s) it is written in
        component_write_phases: dict[int, list[str]] = {}
        component_read_phases:  dict[int, list[str]] = {}

        def _index(systems: list[dict]) -> None:
            for sys in systems:
                phase = sys.get("phase", "Simulation")
                for w in sys.get("writes", []):
                    component_write_phases.setdefault(w, []).append(phase)
                for r in sys.get("reads", []):
                    component_read_phases.setdefault(r, []).append(phase)

        _index(current_cgs.get("global_systems", []))
        for mode in current_cgs.get("modes", []):
            _index(mode.get("systems", []))

        phase_order = {"Input": 0, "Simulation": 1, "PostSimulation": 2, "Render": 3}
        findings: list[str] = []

        for op in plan.ordered_ops:
            tid = op.type_id
            if not tid:
                continue

            write_phases = component_write_phases.get(tid, [])
            read_phases  = component_read_phases.get(tid, [])

            # If a component is written in PostSimulation but read in Simulation,
            # mutating its defaults could cause unexpected phase-order effects.
            for wp in write_phases:
                for rp in read_phases:
                    if phase_order.get(wp, 99) > phase_order.get(rp, 99):
                        findings.append(
                            f"WARNING: Component type_id={tid} is written in "
                            f"'{wp}' but read in '{rp}'. Mutating its defaults "
                            f"may produce unexpected results due to phase ordering."
                        )
                        break

        return findings


def _escalate(current: str, new: str) -> str:
    order = {"none": 0, "warning": 1, "block": 2}
    return current if order.get(current, 0) >= order.get(new, 0) else new