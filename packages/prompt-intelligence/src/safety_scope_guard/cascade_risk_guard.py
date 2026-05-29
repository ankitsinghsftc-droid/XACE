"""
cascade_risk_guard.py — CascadeRiskGuard
=========================================
Simulates indirect mutation impact across the full system dependency graph.

A mutation touching component type_id=5 (COMP_VELOCITY_V1) directly
affects MovementSystem. But it also indirectly affects every system
that depends on MovementSystem — and every system that depends on those
systems. This guard counts the full transitive cascade and warns when
the blast radius is too large.

## Cascade Simulation

    For each operation:
        1. Find all systems that read/write the mutated component type_id
           (direct impact)
        2. BFS/DFS through the depends_on graph to find all downstream
           systems (transitive impact)
        3. Sum up total affected systems

    Thresholds:
        ≤ 2 systems affected → NONE (normal)
        3–5 systems affected → WARNING
        > 5 systems affected → WARNING (not BLOCK — cascade is informational)
        > 8 systems affected → BLOCK (mutation affects most of the game logic)

## Why Not Always Block?

    Large cascade is not necessarily wrong — restructuring the movement
    system is expected to affect many things. The guard's job is to make
    the designer aware of the blast radius, not to prevent all large changes.
    BLOCK is reserved for cascade so large (>8) that it's almost certainly
    unintentional.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from scope_boundary_guard import GuardResult
from mutation_planner import CommittedMutationPlan


# ── Thresholds ────────────────────────────────────────────────────────────────

_WARN_THRESHOLD  = 3
_BLOCK_THRESHOLD = 8


class CascadeRiskGuard:
    """
    Simulates indirect system impact for each mutation operation.
    Stateless, deterministic.
    """

    def check(
        self,
        plan:        CommittedMutationPlan,
        current_cgs: dict[str, Any],
    ) -> GuardResult:
        findings: list[str] = []
        severity = "none"

        # Build system graph
        read_map, write_map, dep_map = _build_system_graph(current_cgs)

        # Collect all touched type_ids
        touched_ids: set[int] = {op.type_id for op in plan.ordered_ops if op.type_id}
        if not touched_ids:
            return GuardResult(guard="cascade_risk", passed=True,
                               severity="none", findings=[])

        # Find direct systems
        direct: set[str] = set()
        for tid in touched_ids:
            direct.update(read_map.get(tid, set()))
            direct.update(write_map.get(tid, set()))

        # BFS transitive cascade via depends_on
        all_affected = set(direct)
        frontier = set(direct)
        visited: set[str] = set(direct)

        while frontier:
            next_frontier: set[str] = set()
            for sid in frontier:
                for downstream in dep_map.get(sid, set()):
                    if downstream not in visited:
                        visited.add(downstream)
                        all_affected.add(downstream)
                        next_frontier.add(downstream)
            frontier = next_frontier

        total = len(all_affected)

        if total > _BLOCK_THRESHOLD:
            severity = "block"
            findings.append(
                f"BLOCKED: Mutation cascades to {total} systems "
                f"(direct={len(direct)}, transitive={total - len(direct)}). "
                f"This exceeds the cascade block threshold ({_BLOCK_THRESHOLD}). "
                f"The mutation likely affects most game logic — verify intent."
            )
        elif total >= _WARN_THRESHOLD:
            severity = "warning"
            affected_list = sorted(all_affected)[:6]
            findings.append(
                f"WARNING: Mutation cascades to {total} systems: "
                f"{', '.join(affected_list)}"
                f"{'...' if total > 6 else ''}. "
                f"Test all affected systems after commit."
            )

        return GuardResult(
            guard    = "cascade_risk",
            passed   = severity != "block",
            severity = severity,
            findings = findings,
        )


def _build_system_graph(cgs: dict[str, Any]) -> tuple[
    dict[int, set[str]],   # read_map:  type_id → systems that read it
    dict[int, set[str]],   # write_map: type_id → systems that write it
    dict[str, set[str]],   # dep_map:   system_id → systems that depend on it
]:
    read_map:  dict[int, set[str]] = {}
    write_map: dict[int, set[str]] = {}
    dep_map:   dict[str, set[str]] = {}

    def _index(systems: list[dict]) -> None:
        for sys in systems:
            sid = sys.get("id", "")
            for r in sys.get("reads", []):
                read_map.setdefault(r, set()).add(sid)
            for w in sys.get("writes", []):
                write_map.setdefault(w, set()).add(sid)
            for dep in sys.get("depends_on", []):
                dep_map.setdefault(dep, set()).add(sid)

    _index(cgs.get("global_systems", []))
    for mode in cgs.get("modes", []):
        _index(mode.get("systems", []))

    return read_map, write_map, dep_map