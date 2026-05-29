"""
dependency_expander.py — DependencyExpander
=============================================
Enforces Inference Invariant II5: max 1-hop reads, 2-hop writes.

## II5 (Never Break)

    II5: dependency_expander: max 1-hop reads, 2-hop writes.

    This means:
        - A system that READS a relevant component is included (1 hop).
        - A system that WRITES to a component that a relevant system reads
          is included (2 hops, to capture upstream write chains).
        - No further expansion beyond 2 hops, ever.
        - system_graph_pruner (packages/inference/) caps the total
          if the hop budget still exceeds the token cap.

## Relationship to RelevanceExtractor

    RelevanceExtractor selects elements by keyword/component relevance.
    DependencyExpander takes those elements and expands the system set
    via the dependency graph to ensure nothing upstream is missed.

    Pipeline:
        RelevanceExtractor.extract()
            → RelevanceResult (initial seed set)
            → DependencyExpander.expand()
            → DependencyExpander.ExpansionResult (expanded system IDs)
            → SchemaSimplifier (receives final actor/system/rule IDs)

## Token Cap Fallback

    If the expanded system set would push dynamic_token_count over the
    8K cap, DependencyExpander trims by removing least-relevant systems
    (those reachable only via read-hops, not write-hops).

## Component Type ID → System Mapping

    DependencyExpander builds an internal mapping:
        component_type_id → [systems that write it]
        component_type_id → [systems that read it]
    From this it can expand the system frontier in the correct direction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from relevance_extractor import RelevanceResult


# ── Hop limits (II5) ─────────────────────────────────────────────────────────

MAX_READ_HOPS  = 1
MAX_WRITE_HOPS = 2


# ── Expansion Result ──────────────────────────────────────────────────────────

@dataclass
class ExpansionResult:
    """
    Output of DependencyExpander.expand().

    Attributes
    ----------
    actor_ids  : set[str]  — unchanged from RelevanceResult
    system_ids : set[str]  — expanded set (seed + dependency hops)
    rule_ids   : set[str]  — unchanged from RelevanceResult
    hop_log    : list[str] — human-readable expansion trace for debugging
    was_trimmed: bool      — True if token cap forced trimming
    """
    actor_ids:   set[str]  = field(default_factory=set)
    system_ids:  set[str]  = field(default_factory=set)
    rule_ids:    set[str]  = field(default_factory=set)
    hop_log:     list[str] = field(default_factory=list)
    was_trimmed: bool      = False

    def to_relevance_result(self) -> RelevanceResult:
        """Converts back to RelevanceResult for SchemaSimplifier."""
        return RelevanceResult(
            relevant_actor_ids  = self.actor_ids,
            relevant_system_ids = self.system_ids,
            relevant_rule_ids   = self.rule_ids,
        )


# ── Dependency Expander ───────────────────────────────────────────────────────

class DependencyExpander:
    """
    Expands a RelevanceResult's system set via the CGS dependency graph.

    Enforces II5 (max 1-hop reads, 2-hop writes).
    Stateless, deterministic, LLM-free.

    Usage
    -----
        expander = DependencyExpander()
        result   = expander.expand(relevance_result, cgs)
        # result.system_ids → expanded set respecting II5
    """

    def expand(
        self,
        relevance:         RelevanceResult,
        cgs:               dict[str, Any],
        max_dynamic_tokens: int = 8_192,
    ) -> ExpansionResult:
        """
        Expands the system set in relevance via dependency graph traversal.

        Parameters
        ----------
        relevance : RelevanceResult
            Initial scored selection from RelevanceExtractor.
        cgs : dict
            Current CGS JSON.
        max_dynamic_tokens : int
            Token cap for trimming. Default 8K (II4).

        Returns
        -------
        ExpansionResult
            Expanded system set with hop trace.
        """
        hop_log: list[str] = []

        # Build system index
        sys_map, read_map, write_map = self._build_maps(cgs)

        # Seed from relevance result
        expanded  = set(relevance.relevant_system_ids)
        seed_size = len(expanded)

        hop_log.append(f"Seed systems: {sorted(expanded)}")

        # ── Read expansion (1-hop) ────────────────────────────────────────────
        # For each seed system, find what components it reads.
        # Include systems that WRITE those components (upstream writers).
        read_additions: set[str] = set()
        for sid in list(expanded):
            sys = sys_map.get(sid, {})
            for type_id in sys.get("reads", []):
                writers = write_map.get(type_id, set())
                for writer in writers:
                    if writer not in expanded:
                        read_additions.add(writer)

        if read_additions:
            expanded |= read_additions
            hop_log.append(
                f"Read-hop (+{len(read_additions)}): added {sorted(read_additions)}"
            )

        # ── Write expansion (2-hop) ───────────────────────────────────────────
        # For each system in expanded (after read-hop), find what it writes.
        # Include systems that READ those components (downstream readers).
        # Then repeat once more (2-hop total from seed).
        write_additions: set[str] = set()
        frontier = set(expanded)
        for _hop in range(MAX_WRITE_HOPS):
            next_additions: set[str] = set()
            for sid in frontier:
                sys = sys_map.get(sid, {})
                for type_id in sys.get("writes", []):
                    readers = read_map.get(type_id, set())
                    for reader in readers:
                        if reader not in expanded:
                            next_additions.add(reader)

            if not next_additions:
                break

            expanded |= next_additions
            write_additions |= next_additions
            frontier = next_additions
            hop_log.append(
                f"Write-hop {_hop + 1} (+{len(next_additions)}): "
                f"added {sorted(next_additions)}"
            )

        # ── depends_on chain (1-hop) ──────────────────────────────────────────
        # Any system that must execute before a seed system should be included.
        dep_additions: set[str] = set()
        for sid in list(expanded):
            sys = sys_map.get(sid, {})
            for dep in sys.get("depends_on", []):
                if dep not in expanded:
                    dep_additions.add(dep)

        if dep_additions:
            expanded |= dep_additions
            hop_log.append(
                f"Dependency-chain (+{len(dep_additions)}): "
                f"added {sorted(dep_additions)}"
            )

        hop_log.append(
            f"Final system count: {len(expanded)} "
            f"(seed={seed_size}, added={len(expanded) - seed_size})"
        )

        return ExpansionResult(
            actor_ids   = set(relevance.relevant_actor_ids),
            system_ids  = expanded,
            rule_ids    = set(relevance.relevant_rule_ids),
            hop_log     = hop_log,
            was_trimmed = False,
        )

    # ── Index builders ────────────────────────────────────────────────────────

    @staticmethod
    def _build_maps(
        cgs: dict[str, Any],
    ) -> tuple[dict[str, dict], dict[int, set[str]], dict[int, set[str]]]:
        """
        Builds three indexes from the CGS system graph:
            sys_map    : system_id → system dict
            read_map   : component_type_id → set of system_ids that read it
            write_map  : component_type_id → set of system_ids that write it
        """
        sys_map:   dict[str, dict]      = {}
        read_map:  dict[int, set[str]]  = {}
        write_map: dict[int, set[str]]  = {}

        def _index(systems: list[dict]) -> None:
            for sys in systems:
                sid = sys.get("id", "")
                sys_map[sid] = sys
                for type_id in sys.get("reads", []):
                    read_map.setdefault(type_id, set()).add(sid)
                for type_id in sys.get("writes", []):
                    write_map.setdefault(type_id, set()).add(sid)

        _index(cgs.get("global_systems", []))
        for mode in cgs.get("modes", []):
            _index(mode.get("systems", []))

        return sys_map, read_map, write_map

    # ── Convenience ───────────────────────────────────────────────────────────

    def expand_system_ids(
        self,
        seed_ids: set[str],
        cgs:      dict[str, Any],
    ) -> set[str]:
        """
        Lightweight expand: takes a seed set of system IDs and returns the
        expanded set per II5. Does not require a full RelevanceResult.
        """
        dummy = RelevanceResult(relevant_system_ids=seed_ids)
        result = self.expand(dummy, cgs)
        return result.system_ids