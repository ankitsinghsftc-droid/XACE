"""
mutation_planner.py — MutationPlanner
=======================================
Builds a CommittedMutationPlan from a validated, critiqued MutationTransaction.

## Position in the Pipeline

    CritiqueEngine.review()
        → CritiqueReport (approved=True)
        → MutationPlanner.plan()
        → CommittedMutationPlan
        → SafetyScopeGuard (13.9)
        → GDE commit (CGSManager.commit)

## CommittedMutationPlan

    The plan carries everything GDE needs to apply the mutation atomically:
        - Ordered operations (dependency-safe execution order)
        - RollbackPlan (for GDE to revert if commit fails partway)
        - Schema version bump type ("patch" | "minor" | "major")
        - Human-readable mutation description for commit log

    MutationPlanner does NOT apply mutations. It organises and annotates.
    The actual apply step is in GDE's TransactionExecutor.

## Operation Ordering

    Raw operations from Pass 2/5 may be in any order. The planner
    sorts them into a safe execution order:

    Tier 1 — Structural removals (must go first — clear space)
        REMOVE_RULE, REMOVE_COMPONENT, REMOVE_SYSTEM, REMOVE_ACTOR

    Tier 2 — Structural additions (build new nodes)
        ADD_ACTOR, ADD_SYSTEM, ADD_COMPONENT, ADD_RULE

    Tier 3 — Value mutations (modify existing fields)
        SET, SCALE

    Within each tier, operations are stable-sorted by path
    (lexicographic) for deterministic ordering across identical inputs.

## Dependency Resolution

    If the same component type_id appears in multiple operations, the
    planner ensures they are ordered by path depth (shallower paths first)
    to avoid applying a child mutation before the parent exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "llm_orchestrator"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "context_assembler"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "intent_intake"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from pass2_dsl_draft import MutationOp
from pass5_final_output import MutationTransaction
from rollback_plan_builder import RollbackPlanBuilder, RollbackPlan

try:
    from critique_engine.critique_engine import CritiqueReport
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "critique_engine"))
    from critique_engine import CritiqueReport


# ── Operation tier for ordering ───────────────────────────────────────────────

_OP_TIER: dict[str, int] = {
    "REMOVE_RULE":      0,
    "REMOVE_COMPONENT": 1,
    "REMOVE_SYSTEM":    2,
    "REMOVE_ACTOR":     3,
    "ADD_ACTOR":        4,
    "ADD_SYSTEM":       5,
    "ADD_COMPONENT":    6,
    "ADD_RULE":         7,
    "SET":              8,
    "SCALE":            9,
}

_DEFAULT_TIER = 8


# ── Committed Mutation Plan ───────────────────────────────────────────────────

@dataclass
class CommittedMutationPlan:
    """
    Final, ordered, rollback-ready plan handed to SafetyScopeGuard and GDE.

    Attributes
    ----------
    ordered_ops          : list[MutationOp]   — ops in safe execution order
    rollback_plan        : RollbackPlan        — inverse operations for GDE
    schema_delta_type    : str                 — from MutationTransaction
    version_bump         : str                 — "patch" | "minor" | "major"
    confidence_score     : float               — from MutationTransaction
    risk_level           : str                 — from MutationTransaction
    required_recompile   : bool                — from MutationTransaction + critique
    affected_systems     : list[str]           — from MutationTransaction + critique
    mutation_description : str                 — human-readable commit log entry
    critique_concerns    : list[str]           — from CritiqueReport (advisory)
    critique_suggestions : list[str]           — from CritiqueReport (advisory)
    """
    ordered_ops:          list[MutationOp]
    rollback_plan:        RollbackPlan
    schema_delta_type:    str
    version_bump:         str
    confidence_score:     float
    risk_level:           str
    required_recompile:   bool
    affected_systems:     list[str]            = field(default_factory=list)
    mutation_description: str                  = ""
    critique_concerns:    list[str]            = field(default_factory=list)
    critique_suggestions: list[str]            = field(default_factory=list)

    @property
    def op_count(self) -> int:
        return len(self.ordered_ops)

    @property
    def rollback_is_complete(self) -> bool:
        return self.rollback_plan.is_complete

    @property
    def is_safe_to_commit(self) -> bool:
        """True when confidence is high and risk is not 'high'."""
        return self.confidence_score >= 0.70 and self.risk_level != "high"

    def to_dict(self) -> dict:
        return {
            "schema_delta_type":    self.schema_delta_type,
            "version_bump":         self.version_bump,
            "confidence_score":     round(self.confidence_score, 3),
            "risk_level":           self.risk_level,
            "required_recompile":   self.required_recompile,
            "affected_systems":     self.affected_systems,
            "op_count":             self.op_count,
            "rollback_is_complete": self.rollback_is_complete,
            "mutation_description": self.mutation_description,
            "critique_concerns":    self.critique_concerns,
            "critique_suggestions": self.critique_suggestions,
        }

    def __repr__(self) -> str:
        safe   = "safe" if self.is_safe_to_commit else "UNSAFE"
        recomp = " [recompile]" if self.required_recompile else ""
        return (
            f"CommittedMutationPlan({safe}{recomp}, "
            f"ops={self.op_count}, "
            f"bump={self.version_bump}, "
            f"conf={self.confidence_score:.2f})"
        )


# ── Mutation Planner ──────────────────────────────────────────────────────────

class MutationPlanner:
    """
    Builds a CommittedMutationPlan from a validated MutationTransaction
    and its CritiqueReport.

    Stateless — one instance shared across PIL sessions.

    Usage
    -----
        planner = MutationPlanner()
        plan    = planner.plan(
            transaction  = mutation_transaction,
            critique     = critique_report,
            current_cgs  = cgs,
            cgs_hash     = current_hash,
        )
        # pass plan to SafetyScopeGuard
    """

    def __init__(self) -> None:
        self._rollback_builder = RollbackPlanBuilder()

    def plan(
        self,
        transaction:  MutationTransaction,
        critique:     CritiqueReport,
        current_cgs:  dict[str, Any],
        cgs_hash:     str = "",
    ) -> CommittedMutationPlan:
        """
        Builds the CommittedMutationPlan.

        Parameters
        ----------
        transaction : MutationTransaction
            Output of Pass 5 (final pipeline output).
        critique    : CritiqueReport
            Output of CritiqueEngine.review() — must be approved.
        current_cgs : dict
            Current CGS for rollback capture and path resolution.
        cgs_hash    : str
            Current CGS hash for rollback audit trail.

        Returns
        -------
        CommittedMutationPlan
        """
        # ── Step 1: Order operations ──────────────────────────────────────────
        ordered_ops = self._order_operations(transaction.operations)

        # ── Step 2: Build rollback plan ───────────────────────────────────────
        rollback_plan = self._rollback_builder.build(
            ops         = ordered_ops,
            current_cgs = current_cgs,
            cgs_hash    = cgs_hash,
        )

        # ── Step 3: Determine version bump ────────────────────────────────────
        version_bump = critique.required_version_bump

        # ── Step 4: Determine recompile requirement ───────────────────────────
        # Use the more conservative of transaction and critique values
        required_recompile = (
            transaction.required_recompile
            or critique.impact_summary.impact_level in {"high"}
            or transaction.schema_delta_type in {"structural_add", "structural_remove"}
        )

        # ── Step 5: Assemble affected systems ─────────────────────────────────
        affected_systems = list(dict.fromkeys(
            transaction.affected_systems
            + critique.impact_summary.all_affected_systems
        ))

        # ── Step 6: Build mutation description ───────────────────────────────
        description = self._build_description(transaction, critique, ordered_ops)

        return CommittedMutationPlan(
            ordered_ops          = ordered_ops,
            rollback_plan        = rollback_plan,
            schema_delta_type    = transaction.schema_delta_type,
            version_bump         = version_bump,
            confidence_score     = transaction.confidence_score,
            risk_level           = transaction.risk_level,
            required_recompile   = required_recompile,
            affected_systems     = affected_systems,
            mutation_description = description,
            critique_concerns    = list(critique.concerns),
            critique_suggestions = list(critique.suggestions),
        )

    # ── Operation ordering ────────────────────────────────────────────────────

    @staticmethod
    def _order_operations(ops: list[MutationOp]) -> list[MutationOp]:
        """
        Sorts operations into safe execution order.
        Stable sort: tier first, then path (lexicographic) within tier.
        """
        return sorted(
            ops,
            key=lambda op: (
                _OP_TIER.get(op.op, _DEFAULT_TIER),
                op.path,
            ),
        )

    # ── Description assembly ──────────────────────────────────────────────────

    @staticmethod
    def _build_description(
        transaction: MutationTransaction,
        critique:    CritiqueReport,
        ops:         list[MutationOp],
    ) -> str:
        """
        Builds a human-readable commit log entry ≤300 chars.
        Uses the mutation_summary from Pass 5 if available and informative.
        """
        if transaction.mutation_summary and len(transaction.mutation_summary) > 10:
            base = transaction.mutation_summary.rstrip(".")
        else:
            # Synthesise from operations
            op_summaries = []
            for op in ops[:3]:   # show at most 3
                field = op.field_name or op.path.split(".")[-1]
                actor = op.actor_id or "entity"
                if op.op in {"SET", "SCALE"}:
                    op_summaries.append(
                        f"{op.op.lower()} {actor}.{field}={op.value!r}"
                    )
                else:
                    op_summaries.append(f"{op.op.lower()} {actor}")
            base = "; ".join(op_summaries) if op_summaries else "mutation"

        suffix = f" [{critique.required_version_bump} bump]" \
            if critique.required_version_bump != "patch" else ""

        full = f"{base}{suffix}"
        return full[:300]