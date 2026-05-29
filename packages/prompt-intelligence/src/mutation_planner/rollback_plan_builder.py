"""
rollback_plan_builder.py — RollbackPlanBuilder
================================================
Prepares a rollback plan for every mutation before commit.

Atomicity guarantee: if GDE commit fails partway through, the rollback
plan can restore the CGS to its exact pre-mutation state. This pairs
with GDE's snapshot mechanism — the rollback plan is the PIL-layer record
of what needs to be undone.

## Rollback Strategy Per Op Type

    SET path=P value=V
        → Capture previous value at P from current_cgs.
          Rollback: SET path=P value=<previous>

    SCALE path=P value=F
        → Capture previous numeric value at P.
          Rollback: SET path=P value=<previous>
          (Using SET not SCALE to avoid floating-point drift on double-inversion)

    ADD_ACTOR actor_id=A
        → No previous state to capture (actor didn't exist).
          Rollback: REMOVE_ACTOR actor_id=A

    REMOVE_ACTOR actor_id=A
        → Capture full actor dict from current_cgs.
          Rollback: ADD_ACTOR with full actor dict as value.

    ADD_COMPONENT / REMOVE_COMPONENT
        → Same pattern: capture existing component dict for removes.

    ADD_SYSTEM / REMOVE_SYSTEM
        → Capture existing system dict for removes.

    ADD_RULE / REMOVE_RULE
        → Capture existing rule dict for removes.

## RollbackOp

    Mirror of MutationOp but carrying the inverse operation:
        path:         str    — same path
        op:           str    — inverse op (SET for rollback of SET/SCALE)
        value:        Any    — the previous value (or actor/system/rule dict)
        previous_hash: str   — CGS hash at capture time (for audit)

## Capture Failure

    If the previous value cannot be found in current_cgs (e.g. the path
    doesn't resolve — already caught by ValidationLoop), the rollback op
    gets value=None and is_partial=True. The RollbackPlan.is_complete
    property reflects this. Partial rollback plans are flagged for manual
    review but do not block the commit — GDE's snapshot is the ultimate
    safety net.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "llm_orchestrator"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "context_assembler"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "intent_intake"))

from pass2_dsl_draft import MutationOp


# ── Inverse Op Mapping ────────────────────────────────────────────────────────

_INVERSE_OPS: dict[str, str] = {
    "SET":              "SET",          # rollback SET with the previous value
    "SCALE":            "SET",          # rollback SCALE with the captured previous value
    "ADD_ACTOR":        "REMOVE_ACTOR",
    "REMOVE_ACTOR":     "ADD_ACTOR",
    "ADD_COMPONENT":    "REMOVE_COMPONENT",
    "REMOVE_COMPONENT": "ADD_COMPONENT",
    "ADD_SYSTEM":       "REMOVE_SYSTEM",
    "REMOVE_SYSTEM":    "ADD_SYSTEM",
    "ADD_RULE":         "REMOVE_RULE",
    "REMOVE_RULE":      "ADD_RULE",
}

# Path patterns for CGS traversal
_COMP_FIELD_RE = re.compile(
    r'^modes\[([^\]]+)\]\.actors\[([^\]]+)\]\.components\[(\d+)\]\.defaults\.(\w+)$'
)
_ACTOR_RE = re.compile(r'^modes\[([^\]]+)\]\.actors\[([^\]]+)\]')
_SYSTEM_RE = re.compile(r'^modes\[([^\]]+)\]\.systems\[([^\]]+)\]')
_RULE_RE   = re.compile(r'^modes\[([^\]]+)\]\.rules\[([^\]]+)\]')


# ── Rollback Op ───────────────────────────────────────────────────────────────

@dataclass
class RollbackOp:
    """
    One inverse mutation operation for rollback.

    Attributes
    ----------
    original_op     : MutationOp  — the forward operation this undoes
    rollback_op     : str         — inverse op type
    rollback_value  : Any         — value to restore (None if capture failed)
    capture_failed  : bool        — True if previous state could not be found
    capture_reason  : str         — reason for capture failure (if any)
    """
    original_op:    MutationOp
    rollback_op:    str
    rollback_value: Any   = None
    capture_failed: bool  = False
    capture_reason: str   = ""

    @property
    def is_complete(self) -> bool:
        return not self.capture_failed

    def to_dict(self) -> dict:
        return {
            "path":           self.original_op.path,
            "rollback_op":    self.rollback_op,
            "rollback_value": self.rollback_value,
            "capture_failed": self.capture_failed,
            "capture_reason": self.capture_reason,
        }

    def __repr__(self) -> str:
        status = "" if self.is_complete else " [partial]"
        return (
            f"RollbackOp({self.rollback_op}{status}: "
            f"{self.original_op.path[:50]!r})"
        )


# ── Rollback Plan ─────────────────────────────────────────────────────────────

@dataclass
class RollbackPlan:
    """
    Complete rollback plan for a MutationTransaction.

    Attributes
    ----------
    rollback_ops    : list[RollbackOp]  — one inverse op per forward op
    cgs_hash_before : str               — CGS hash at plan creation time
    is_complete     : bool              — True if all captures succeeded
    partial_count   : int               — number of partial (failed) captures
    """
    rollback_ops:    list[RollbackOp]
    cgs_hash_before: str              = ""

    @property
    def is_complete(self) -> bool:
        return all(op.is_complete for op in self.rollback_ops)

    @property
    def partial_count(self) -> int:
        return sum(1 for op in self.rollback_ops if op.capture_failed)

    @property
    def op_count(self) -> int:
        return len(self.rollback_ops)

    def to_dict(self) -> dict:
        return {
            "cgs_hash_before": self.cgs_hash_before,
            "is_complete":     self.is_complete,
            "partial_count":   self.partial_count,
            "rollback_ops":    [op.to_dict() for op in self.rollback_ops],
        }

    def __repr__(self) -> str:
        status = "complete" if self.is_complete else f"partial({self.partial_count} failed)"
        return f"RollbackPlan({self.op_count} ops, {status})"


# ── Rollback Plan Builder ─────────────────────────────────────────────────────

class RollbackPlanBuilder:
    """
    Builds a RollbackPlan from a list of MutationOps and the current CGS.

    Stateless — safe to share across sessions.
    Deterministic — same inputs always produce the same plan.

    Usage
    -----
        builder = RollbackPlanBuilder()
        plan    = builder.build(
            ops         = transaction.operations,
            current_cgs = cgs,
            cgs_hash    = current_hash,
        )
        if not plan.is_complete:
            log_warning(f"{plan.partial_count} partial captures")
    """

    def build(
        self,
        ops:         list[MutationOp],
        current_cgs: dict[str, Any],
        cgs_hash:    str = "",
    ) -> RollbackPlan:
        """
        Builds a RollbackPlan by capturing previous state for each op.

        Parameters
        ----------
        ops : list[MutationOp]
            Forward operations from MutationTransaction.
        current_cgs : dict
            Current CGS — used to capture previous values.
        cgs_hash : str
            CGS hash at capture time for audit trail.

        Returns
        -------
        RollbackPlan
        """
        rollback_ops: list[RollbackOp] = []

        for op in ops:
            rollback_op_type = _INVERSE_OPS.get(op.op, "SET")
            prev_value, failed, reason = self._capture_previous(op, current_cgs)

            rollback_ops.append(RollbackOp(
                original_op    = op,
                rollback_op    = rollback_op_type,
                rollback_value = prev_value,
                capture_failed = failed,
                capture_reason = reason,
            ))

        return RollbackPlan(
            rollback_ops    = rollback_ops,
            cgs_hash_before = cgs_hash,
        )

    # ── Previous state capture ────────────────────────────────────────────────

    def _capture_previous(
        self,
        op:          MutationOp,
        current_cgs: dict[str, Any],
    ) -> tuple[Any, bool, str]:
        """
        Captures the previous value for one operation.
        Returns (previous_value, capture_failed, failure_reason).
        """
        op_type = op.op

        # ADD_* ops: no previous state to capture (entity doesn't exist yet)
        if op_type.startswith("ADD_"):
            return None, False, ""

        # SET / SCALE: capture the current scalar value at the path
        if op_type in {"SET", "SCALE"}:
            return self._capture_field_value(op.path, current_cgs)

        # REMOVE_ACTOR: capture full actor dict
        if op_type == "REMOVE_ACTOR":
            return self._capture_actor(op.path, current_cgs)

        # REMOVE_COMPONENT: capture component dict
        if op_type == "REMOVE_COMPONENT":
            return self._capture_component(op.path, current_cgs)

        # REMOVE_SYSTEM: capture system dict
        if op_type == "REMOVE_SYSTEM":
            return self._capture_system(op.path, current_cgs)

        # REMOVE_RULE: capture rule dict
        if op_type == "REMOVE_RULE":
            return self._capture_rule(op.path, current_cgs)

        return None, True, f"No capture strategy for op type '{op_type}'"

    @staticmethod
    def _capture_field_value(
        path:        str,
        current_cgs: dict[str, Any],
    ) -> tuple[Any, bool, str]:
        """Captures a scalar field value from a CGS path."""
        m = _COMP_FIELD_RE.match(path)
        if not m:
            return None, True, f"Path grammar not recognised for capture: {path!r}"

        mid, aid, tid_str, field_name = m.groups()
        tid = int(tid_str)

        for mode in current_cgs.get("modes", []):
            if mode.get("id") != mid:
                continue
            for actor in mode.get("actors", []):
                if actor.get("id") != aid:
                    continue
                for comp in actor.get("components", []):
                    if comp.get("type_id") != tid:
                        continue
                    defaults = comp.get("defaults", {})
                    if field_name in defaults:
                        return defaults[field_name], False, ""
                    return None, True, (
                        f"Field '{field_name}' not found in component "
                        f"type_id={tid} on actor '{aid}'"
                    )

        return None, True, f"Path not resolved in CGS: {path!r}"

    @staticmethod
    def _capture_actor(
        path:        str,
        current_cgs: dict[str, Any],
    ) -> tuple[Any, bool, str]:
        """Captures a full actor dict."""
        m = _ACTOR_RE.match(path)
        if not m:
            return None, True, f"Cannot parse actor path: {path!r}"

        mid, aid = m.group(1), m.group(2)
        for mode in current_cgs.get("modes", []):
            if mode.get("id") != mid:
                continue
            for actor in mode.get("actors", []):
                if actor.get("id") == aid:
                    import copy
                    return copy.deepcopy(actor), False, ""

        return None, True, f"Actor '{aid}' not found in mode '{mid}'"

    @staticmethod
    def _capture_system(
        path:        str,
        current_cgs: dict[str, Any],
    ) -> tuple[Any, bool, str]:
        """Captures a full system dict."""
        m = _SYSTEM_RE.match(path)
        if not m:
            return None, True, f"Cannot parse system path: {path!r}"

        mid, sid = m.group(1), m.group(2)
        for mode in current_cgs.get("modes", []):
            if mode.get("id") != mid:
                continue
            for sys in mode.get("systems", []):
                if sys.get("id") == sid:
                    import copy
                    return copy.deepcopy(sys), False, ""

        return None, True, f"System '{sid}' not found in mode '{mid}'"

    @staticmethod
    def _capture_rule(
        path:        str,
        current_cgs: dict[str, Any],
    ) -> tuple[Any, bool, str]:
        """Captures a full rule dict."""
        m = _RULE_RE.match(path)
        if not m:
            return None, True, f"Cannot parse rule path: {path!r}"

        mid, rid = m.group(1), m.group(2)
        for mode in current_cgs.get("modes", []):
            if mode.get("id") != mid:
                continue
            for rule in mode.get("rules", []):
                if rule.get("id") == rid:
                    import copy
                    return copy.deepcopy(rule), False, ""

        return None, True, f"Rule '{rid}' not found in mode '{mid}'"

    @staticmethod
    def _capture_component(
        path:        str,
        current_cgs: dict[str, Any],
    ) -> tuple[Any, bool, str]:
        """Captures a full component dict."""
        # Path example: modes[mode_default].actors[actor_zombie].components[100]
        m = re.match(
            r'^modes\[([^\]]+)\]\.actors\[([^\]]+)\]\.components\[(\d+)\]',
            path,
        )
        if not m:
            return None, True, f"Cannot parse component path: {path!r}"

        mid, aid, tid_str = m.group(1), m.group(2), m.group(3)
        tid = int(tid_str)

        for mode in current_cgs.get("modes", []):
            if mode.get("id") != mid:
                continue
            for actor in mode.get("actors", []):
                if actor.get("id") != aid:
                    continue
                for comp in actor.get("components", []):
                    if comp.get("type_id") == tid:
                        import copy
                        return copy.deepcopy(comp), False, ""

        return None, True, (
            f"Component type_id={tid} not found on actor '{aid}' "
            f"in mode '{mid}'"
        )