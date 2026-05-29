"""
safety_scope_guard.py — SafetyScopeGuard
==========================================
Final governance gate before GDE commit.

Runs all 5 safety guards and applies mode-aware risk thresholds to
produce one of three outcomes:
    Approved     — all guards pass; safe to commit
    SoftWarning  — non-blocking warnings; designer informed, can proceed
    Blocked      — at least one hard block; cannot commit

## Five Guards

    1. ScopeBoundaryGuard      — path allow-list, forbidden domains, structural gating
    2. DestructiveChangeGuard  — core component protection, system orphan check
    3. CascadeRiskGuard        — transitive system impact simulation
    4. DeterminismSafetyGuard  — nondeterministic values, cross-phase mutations
    5. PerformanceRiskGuard    — memory/CPU/event-load estimates

## Risk Threshold System

    FULLY_ASSISTED:  ANY block → Blocked; ANY warning → Blocked (conservative)
    COLLABORATIVE:   ANY block → Blocked; warnings aggregate to SoftWarning
    ADVANCED:        Hard blocks only → Blocked; soft blocks → SoftWarning
    ARCHITECT_MODE:  Only determinism + permanent-forbidden blocks apply

    Threshold overrides:
        DeterminismSafetyGuard blocks are ALWAYS hard (all modes).
        Permanent forbidden path blocks (metadata.cgs_hash etc.) are always hard.

## SafetyOutcome

    verdict:    "Approved" | "SoftWarning" | "Blocked"
    guard_results: dict[str, GuardResult]
    blocking_findings: list[str]   — from blocked guards
    warning_findings:  list[str]   — from warning guards
    blocking_guards:   list[str]   — guard names that hard-blocked
    warning_guards:    list[str]   — guard names that warned
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from scope_boundary_guard import ScopeBoundaryGuard, GuardResult
from destructive_change_guard import DestructiveChangeGuard
from cascade_risk_guard import CascadeRiskGuard
from determinism_safety_guard import DeterminismSafetyGuard
from performance_risk_guard import PerformanceRiskGuard

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mutation_planner"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "context_assembler"))

from mutation_planner import CommittedMutationPlan
from llm_context_packet import AllowedMutationScope


# ── Verdicts ──────────────────────────────────────────────────────────────────

class Verdict:
    APPROVED     = "Approved"
    SOFT_WARNING = "SoftWarning"
    BLOCKED      = "Blocked"


# ── Mode thresholds ───────────────────────────────────────────────────────────

# Guards that are ALWAYS hard-block regardless of mode
_ALWAYS_HARD_GUARDS = frozenset({"determinism_safety"})

# In ARCHITECT_MODE, only these guards can hard-block
_ARCHITECT_HARD_GUARDS = frozenset({"determinism_safety", "scope_boundary"})


# ── Safety Outcome ────────────────────────────────────────────────────────────

@dataclass
class SafetyOutcome:
    """
    Final result of SafetyScopeGuard.evaluate().

    Attributes
    ----------
    verdict            : str                    — Approved|SoftWarning|Blocked
    guard_results      : dict[str, GuardResult] — all five guard outputs
    blocking_findings  : list[str]              — from blocked guards
    warning_findings   : list[str]              — from warning guards
    blocking_guards    : list[str]              — names of hard-blocking guards
    warning_guards     : list[str]              — names of warning guards
    mode               : str                    — assistance mode at evaluation
    """
    verdict:           str
    guard_results:     dict[str, GuardResult]   = field(default_factory=dict)
    blocking_findings: list[str]                = field(default_factory=list)
    warning_findings:  list[str]                = field(default_factory=list)
    blocking_guards:   list[str]                = field(default_factory=list)
    warning_guards:    list[str]                = field(default_factory=list)
    mode:              str                      = "COLLABORATIVE"

    @property
    def is_approved(self) -> bool:
        return self.verdict == Verdict.APPROVED

    @property
    def is_blocked(self) -> bool:
        return self.verdict == Verdict.BLOCKED

    @property
    def is_soft_warning(self) -> bool:
        return self.verdict == Verdict.SOFT_WARNING

    @property
    def all_findings(self) -> list[str]:
        return self.blocking_findings + self.warning_findings

    def to_dict(self) -> dict:
        return {
            "verdict":          self.verdict,
            "mode":             self.mode,
            "blocking_guards":  self.blocking_guards,
            "warning_guards":   self.warning_guards,
            "blocking_findings": self.blocking_findings[:5],
            "warning_findings":  self.warning_findings[:5],
        }

    def __repr__(self) -> str:
        return (
            f"SafetyOutcome({self.verdict}, mode={self.mode}, "
            f"blocks={self.blocking_guards}, warns={self.warning_guards})"
        )


# ── Safety Scope Guard ────────────────────────────────────────────────────────

class SafetyScopeGuard:
    """
    Final governance gate: runs all 5 guards and applies risk thresholds.

    One instance per PIL session.

    Usage
    -----
        guard   = SafetyScopeGuard()
        outcome = guard.evaluate(
            plan            = committed_mutation_plan,
            current_cgs     = cgs,
            mode            = "COLLABORATIVE",
            scope           = allowed_mutation_scope,
            engine_metrics  = None,
        )
        if outcome.is_blocked:
            return PipelineResult(needs_clarification=True,
                                  error=outcome.blocking_findings[0])
        if outcome.is_soft_warning:
            show_warnings_to_designer(outcome.warning_findings)
        # proceed to GDE commit
    """

    def __init__(self) -> None:
        self._scope_guard       = ScopeBoundaryGuard()
        self._destructive_guard = DestructiveChangeGuard()
        self._cascade_guard     = CascadeRiskGuard()
        self._determinism_guard = DeterminismSafetyGuard()
        self._performance_guard = PerformanceRiskGuard()

    def evaluate(
        self,
        plan:           CommittedMutationPlan,
        current_cgs:    dict[str, Any],
        mode:           str                      = "COLLABORATIVE",
        scope:          AllowedMutationScope | None = None,
        engine_metrics: dict[str, Any] | None    = None,
    ) -> SafetyOutcome:
        """
        Runs all 5 guards and applies mode-aware risk thresholds.

        Parameters
        ----------
        plan           : CommittedMutationPlan
        current_cgs    : dict
        mode           : str            — assistance mode
        scope          : AllowedMutationScope | None
        engine_metrics : dict | None    — optional Phase 7 performance data

        Returns
        -------
        SafetyOutcome
        """
        # ── Run all 5 guards ──────────────────────────────────────────────────
        results: dict[str, GuardResult] = {
            "scope_boundary":   self._scope_guard.check(plan, scope),
            "destructive_change": self._destructive_guard.check(plan, current_cgs, mode),
            "cascade_risk":     self._cascade_guard.check(plan, current_cgs),
            "determinism_safety": self._determinism_guard.check(plan, current_cgs),
            "performance_risk": self._performance_guard.check(plan, current_cgs, engine_metrics),
        }

        # ── Apply mode thresholds ─────────────────────────────────────────────
        blocking_guards:   list[str] = []
        warning_guards:    list[str] = []
        blocking_findings: list[str] = []
        warning_findings:  list[str] = []

        for guard_name, result in results.items():
            if result.severity == "none":
                continue

            effective_severity = self._effective_severity(
                guard_name, result.severity, mode
            )

            if effective_severity == "block":
                blocking_guards.append(guard_name)
                blocking_findings.extend(result.findings)
            elif effective_severity == "warning":
                warning_guards.append(guard_name)
                warning_findings.extend(result.findings)

        # ── Determine verdict ─────────────────────────────────────────────────
        if blocking_guards:
            verdict = Verdict.BLOCKED
        elif warning_guards:
            # FULLY_ASSISTED: treat all warnings as blocks (safety first for beginners)
            if mode == "FULLY_ASSISTED":
                verdict  = Verdict.BLOCKED
                blocking_guards   = warning_guards
                blocking_findings = warning_findings
                warning_guards    = []
                warning_findings  = []
            else:
                verdict = Verdict.SOFT_WARNING
        else:
            verdict = Verdict.APPROVED

        return SafetyOutcome(
            verdict           = verdict,
            guard_results     = results,
            blocking_findings = blocking_findings,
            warning_findings  = warning_findings,
            blocking_guards   = blocking_guards,
            warning_guards    = warning_guards,
            mode              = mode,
        )

    # ── Mode threshold application ────────────────────────────────────────────

    @staticmethod
    def _effective_severity(
        guard_name: str,
        raw_severity: str,
        mode: str,
    ) -> str:
        """
        Applies mode-aware threshold to a raw severity.

        ALWAYS_HARD guards (determinism_safety): block stays block in all modes.
        ARCHITECT_MODE: non-ALWAYS_HARD blocks are downgraded to warnings.
        ADVANCED: soft-blocks from non-critical guards → warnings.
        COLLABORATIVE/FULLY_ASSISTED: all blocks stay blocks.
        """
        if raw_severity == "none":
            return "none"

        # Determinism is always hard
        if guard_name in _ALWAYS_HARD_GUARDS and raw_severity == "block":
            return "block"

        # ARCHITECT_MODE: only ALWAYS_HARD and scope_boundary can hard-block
        if mode == "ARCHITECT_MODE":
            if guard_name not in _ARCHITECT_HARD_GUARDS and raw_severity == "block":
                return "warning"   # downgrade to warning in expert mode
            return raw_severity

        # ADVANCED: destructive and cascade blocks downgraded to warnings
        if mode == "ADVANCED":
            if guard_name in {"destructive_change", "cascade_risk", "performance_risk"}:
                if raw_severity == "block":
                    return "warning"
            return raw_severity

        # COLLABORATIVE / FULLY_ASSISTED: return as-is
        return raw_severity