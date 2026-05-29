"""
performance_risk_guard.py — PerformanceRiskGuard
=================================================
Estimates the runtime performance impact of a mutation.

## What It Estimates

    1. Memory Impact
       Adding actors or components increases per-entity memory.
       Structural adds beyond a threshold warn that memory may spike.

    2. CPU Impact (via system graph complexity)
       More systems = more CPU per tick. Adding systems that have many
       reads/writes is costlier than adding simple systems.
       Estimated CPU cost = sum(reads + writes) for affected systems.

    3. Event Load
       Systems that write to component type_ids that many other systems
       read create high "event fan-out". Mutations that increase fan-out
       (e.g. adding a component that many systems read) are flagged.

    4. Engine Metrics Integration
       When Phase 7 engine feedback metrics are available
       (via packages/engine-feedback), the guard uses real tick
       timing data to estimate impact. When not available (most test
       environments), it uses static heuristics.

## Severity

    NONE:    estimated impact is within normal operating range
    WARNING: impact is notable but not blocking
    BLOCK:   impact estimate exceeds hard threshold
             (only triggers for extremely large structural changes —
              adding 100+ actors in one mutation, etc.)

## Why Conservative

    Performance estimation is inherently imprecise. The guard errs
    toward warnings over blocks. The designer and engineer should
    validate performance in the actual engine, not rely solely on
    static analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from scope_boundary_guard import GuardResult
from mutation_planner import CommittedMutationPlan


# ── Thresholds ────────────────────────────────────────────────────────────────

_ACTOR_ADD_WARN_COUNT  = 10    # adding > 10 actors at once → warning
_ACTOR_ADD_BLOCK_COUNT = 100   # adding > 100 actors → block
_CPU_COST_WARN         = 20    # total R+W ops across affected systems → warning
_CPU_COST_BLOCK        = 60    # hard block threshold
_EVENT_FAN_OUT_WARN    = 5     # > 5 systems reading a written component → warning


@dataclass
class PerformanceEstimate:
    """Performance impact estimate for a mutation."""
    memory_actor_delta:    int   = 0    # net actors added
    cpu_cost_estimate:     int   = 0    # sum of reads+writes on affected systems
    event_fan_out:         int   = 0    # max readers of a newly-written component
    uses_real_metrics:     bool  = False


class PerformanceRiskGuard:
    """
    Estimates runtime performance impact. Stateless, deterministic.
    """

    def check(
        self,
        plan:           CommittedMutationPlan,
        current_cgs:    dict[str, Any],
        engine_metrics: dict[str, Any] | None = None,
    ) -> GuardResult:
        findings: list[str] = []
        severity = "none"

        estimate = self._estimate(plan, current_cgs, engine_metrics)

        # Memory: actor additions
        if estimate.memory_actor_delta >= _ACTOR_ADD_BLOCK_COUNT:
            findings.append(
                f"BLOCKED: Mutation adds {estimate.memory_actor_delta} actors at once. "
                f"This exceeds the safe single-commit actor limit ({_ACTOR_ADD_BLOCK_COUNT}). "
                f"Split into multiple smaller mutations."
            )
            severity = "block"
        elif estimate.memory_actor_delta >= _ACTOR_ADD_WARN_COUNT:
            findings.append(
                f"WARNING: Mutation adds {estimate.memory_actor_delta} actors. "
                f"Monitor memory after commit."
            )
            severity = _escalate(severity, "warning")

        # CPU: affected system complexity
        if estimate.cpu_cost_estimate >= _CPU_COST_BLOCK:
            findings.append(
                f"BLOCKED: Estimated CPU cost {estimate.cpu_cost_estimate} "
                f"(sum of system R/W operations) exceeds block threshold "
                f"({_CPU_COST_BLOCK}). Simplify the mutation or split it."
            )
            severity = "block"
        elif estimate.cpu_cost_estimate >= _CPU_COST_WARN:
            findings.append(
                f"WARNING: Estimated CPU cost {estimate.cpu_cost_estimate} — "
                f"mutation affects many system read/write operations. "
                f"Profile tick performance after commit."
            )
            severity = _escalate(severity, "warning")

        # Event fan-out
        if estimate.event_fan_out >= _EVENT_FAN_OUT_WARN:
            findings.append(
                f"WARNING: Event fan-out of {estimate.event_fan_out} — "
                f"a written component is read by many systems. "
                f"High fan-out can degrade tick throughput."
            )
            severity = _escalate(severity, "warning")

        # Note when real metrics were used
        if estimate.uses_real_metrics and findings:
            findings.append(
                "(Estimates based on real engine tick metrics from Phase 7.)"
            )

        return GuardResult(
            guard    = "performance_risk",
            passed   = severity != "block",
            severity = severity,
            findings = findings,
        )

    def _estimate(
        self,
        plan:           CommittedMutationPlan,
        current_cgs:    dict[str, Any],
        engine_metrics: dict[str, Any] | None,
    ) -> PerformanceEstimate:
        actor_delta = 0
        for op in plan.ordered_ops:
            if op.op == "ADD_ACTOR":
                actor_delta += 1
            elif op.op == "REMOVE_ACTOR":
                actor_delta -= 1

        # CPU cost from affected systems
        cpu_cost = 0
        for sys_id in plan.affected_systems:
            sys = _find_system(sys_id, current_cgs)
            if sys:
                cpu_cost += len(sys.get("reads", [])) + len(sys.get("writes", []))

        # Event fan-out: max readers of any component written by affected systems
        read_map: dict[int, int] = {}   # type_id → reader count
        for mode in current_cgs.get("modes", []):
            for sys in mode.get("systems", []):
                for r in sys.get("reads", []):
                    read_map[r] = read_map.get(r, 0) + 1

        max_fan_out = 0
        for sys_id in plan.affected_systems:
            sys = _find_system(sys_id, current_cgs)
            if sys:
                for w in sys.get("writes", []):
                    max_fan_out = max(max_fan_out, read_map.get(w, 0))

        # If real engine metrics provided, use tick_time_ms to scale CPU estimate
        uses_real = False
        if engine_metrics and "avg_tick_ms" in engine_metrics:
            tick_ms = float(engine_metrics.get("avg_tick_ms", 0))
            if tick_ms > 0:
                # Scale: if tick is already > 15ms (60fps budget), be more conservative
                if tick_ms > 15.0:
                    cpu_cost = int(cpu_cost * 1.5)
                uses_real = True

        return PerformanceEstimate(
            memory_actor_delta = actor_delta,
            cpu_cost_estimate  = cpu_cost,
            event_fan_out      = max_fan_out,
            uses_real_metrics  = uses_real,
        )


def _find_system(
    system_id:   str,
    current_cgs: dict[str, Any],
) -> dict | None:
    for gs in current_cgs.get("global_systems", []):
        if gs.get("id") == system_id:
            return gs
    for mode in current_cgs.get("modes", []):
        for sys in mode.get("systems", []):
            if sys.get("id") == system_id:
                return sys
    return None


def _escalate(current: str, new: str) -> str:
    order = {"none": 0, "warning": 1, "block": 2}
    return current if order.get(current, 0) >= order.get(new, 0) else new