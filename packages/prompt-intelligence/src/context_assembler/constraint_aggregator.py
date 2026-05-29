"""
constraint_aggregator.py — ConstraintAggregator
=================================================
Collects architectural constraints that go into the LLM cached prefix.

## Why Constraints Belong in the Cached Prefix

    Constraints are stable across calls — they don't change unless the
    game's schema changes. Anthropic's prompt_cache_control lets us mark
    these as a static prefix so they are sent once and reused at near-zero
    cost on subsequent calls with the same CGS hash.

    Per Inference Invariant II9:
        Design + Structural + Behavioral memory → cached prefix
        Session + Safety memory → per-prompt body

    Constraints are the "Structural" and "Behavioral" layer here.

## What Counts as a Constraint

    1. D-rules — Determinism rules extracted from the CGS system graph
       (which systems write to which components, phase ordering, etc.)
       These tell the LLM what it CANNOT change without breaking replay.

    2. R/W Contracts — component read/write contracts per system.
       "AISystem writes component 5 (COMP_VELOCITY_V1) — any mutation to
       max_linear_speed must account for this system's write."

    3. Dependency Ordering — systems that depend on other systems.
       "MovementSystem depends on InputSystem — do not reorder these."

    4. Mode Invariants — any is_default mode rules, actor control_type
       constraints, etc.

    5. Global Frozen Rules — permanent architectural rules that never
       change regardless of CGS content:
           - Entity IDs are u64, immutable after spawn
           - Component type_ids are UCL-defined, cannot be invented
           - Phase ordering: Input → Simulation → PostSimulation → Render
           - All systems must be deterministic (deterministic: true)

## Output Format

    Each constraint is a compact English sentence.
    The list is deduplicated. Order: global_frozen → d_rules → rw_contracts
    → dependency_ordering → mode_invariants.

    These sentences feed directly into the cached prompt prefix that
    prompt_cache.py (packages/inference) marks with cache_control.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Global Frozen Constraints ─────────────────────────────────────────────────
# These never change regardless of CGS content.

_GLOBAL_FROZEN: tuple[str, ...] = (
    "Entity IDs are u64 values assigned at spawn; they are immutable and may never be changed by mutations.",
    "Component type_ids are defined by the UCL (Universal Component Library); you may not invent new type_id values.",
    "Phase execution order is fixed: Input → Simulation → PostSimulation → Render. Do not reorder phases.",
    "All systems must have deterministic: true. Non-deterministic systems are forbidden.",
    "The CGS hash (metadata.cgs_hash) is computed by the engine; mutations must never set it directly.",
    "Schema version (metadata.schema_version) is bumped by CGSManager; mutations must never set it directly.",
    "The MutationGate validates every field write; mutations that bypass the gate will be rejected.",
    "Component defaults may only contain JSON-serializable scalar or nested-object values; no functions or code.",
)


# ── Constraint Set ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ConstraintSet:
    """
    Aggregated set of constraints for one LLM call.

    Attributes
    ----------
    global_frozen : tuple[str, ...]
        Engine-level invariants that never change.
    d_rules : tuple[str, ...]
        Determinism rules derived from the current CGS system graph.
    rw_contracts : tuple[str, ...]
        Component read/write contracts per system.
    dependency_ordering : tuple[str, ...]
        System dependency chain statements.
    mode_invariants : tuple[str, ...]
        Mode-level invariants (control_type, defaults, etc.).

    all_constraints : property → tuple[str, ...]
        Concatenation of all layers in stable order.
    estimated_tokens : int
        Character-based estimate for cached prefix sizing.
    """
    global_frozen:       tuple[str, ...]
    d_rules:             tuple[str, ...]
    rw_contracts:        tuple[str, ...]
    dependency_ordering: tuple[str, ...]
    mode_invariants:     tuple[str, ...]
    estimated_tokens:    int = 0

    @property
    def all_constraints(self) -> tuple[str, ...]:
        return (
            self.global_frozen
            + self.d_rules
            + self.rw_contracts
            + self.dependency_ordering
            + self.mode_invariants
        )

    @property
    def count(self) -> int:
        return len(self.all_constraints)

    def to_list(self) -> list[str]:
        return list(self.all_constraints)


# ── Constraint Aggregator ─────────────────────────────────────────────────────

class ConstraintAggregator:
    """
    Extracts and formats architectural constraints from a CGS.

    Stateless — safe to share across sessions.
    Deterministic — same CGS always produces the same constraint set.
    LLM-free — pure structural analysis.

    Usage
    -----
        aggregator = ConstraintAggregator()
        constraints = aggregator.aggregate(cgs)
        # constraints.all_constraints → tuple of English sentences
        # constraints.estimated_tokens → int for cached prefix budget
    """

    def aggregate(self, cgs: dict[str, Any]) -> ConstraintSet:
        """
        Aggregates constraints from a CGS.

        Parameters
        ----------
        cgs : dict
            The current CGS JSON dict (real schema).

        Returns
        -------
        ConstraintSet
            All constraint layers assembled and deduplicated.
        """
        d_rules             = self._extract_d_rules(cgs)
        rw_contracts        = self._extract_rw_contracts(cgs)
        dependency_ordering = self._extract_dependency_ordering(cgs)
        mode_invariants     = self._extract_mode_invariants(cgs)

        all_text = (
            _GLOBAL_FROZEN
            + d_rules
            + rw_contracts
            + dependency_ordering
            + mode_invariants
        )
        token_estimate = max(1, sum(len(s) for s in all_text) // 4)

        return ConstraintSet(
            global_frozen       = _GLOBAL_FROZEN,
            d_rules             = d_rules,
            rw_contracts        = rw_contracts,
            dependency_ordering = dependency_ordering,
            mode_invariants     = mode_invariants,
            estimated_tokens    = token_estimate,
        )

    # ── D-Rules ───────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_d_rules(cgs: dict[str, Any]) -> tuple[str, ...]:
        """
        Derives determinism rules from the system graph.
        Each system that writes a component generates a D-rule:
        "SystemX writes component Y — mutation to Y's defaults affects
        SystemX's output each tick."
        """
        rules: list[str] = []
        seen: set[str] = set()

        def _process_systems(systems: list[dict], scope: str) -> None:
            for sys in systems:
                sid   = sys.get("id", "?")
                det   = sys.get("deterministic", True)
                reads  = sys.get("reads",  [])
                writes = sys.get("writes", [])

                if not det:
                    stmt = (
                        f"WARNING: {sid} ({scope}) is non-deterministic — "
                        f"this violates engine invariants and must be corrected."
                    )
                    if stmt not in seen:
                        seen.add(stmt)
                        rules.append(stmt)

                for w in writes:
                    stmt = (
                        f"{sid} ({scope}) writes component type_id={w}; "
                        f"mutations to that component's defaults affect {sid}'s output each tick."
                    )
                    if stmt not in seen:
                        seen.add(stmt)
                        rules.append(stmt)

        _process_systems(cgs.get("global_systems", []), "global")
        for mode in cgs.get("modes", []):
            _process_systems(mode.get("systems", []), f"mode={mode.get('id','?')}")

        return tuple(rules)

    # ── R/W Contracts ─────────────────────────────────────────────────────────

    @staticmethod
    def _extract_rw_contracts(cgs: dict[str, Any]) -> tuple[str, ...]:
        """
        Derives R/W contract statements:
        "SystemX reads components [A, B] and writes [C, D]."
        Helps the LLM understand data flow before proposing mutations.
        """
        contracts: list[str] = []
        seen: set[str] = set()

        def _process(systems: list[dict]) -> None:
            for sys in systems:
                sid    = sys.get("id", "?")
                reads  = sys.get("reads",  [])
                writes = sys.get("writes", [])
                if not reads and not writes:
                    continue
                r_str = ", ".join(str(r) for r in reads)  if reads  else "none"
                w_str = ", ".join(str(w) for w in writes) if writes else "none"
                stmt  = f"{sid}: reads=[{r_str}], writes=[{w_str}]."
                if stmt not in seen:
                    seen.add(stmt)
                    contracts.append(stmt)

        _process(cgs.get("global_systems", []))
        for mode in cgs.get("modes", []):
            _process(mode.get("systems", []))

        return tuple(contracts)

    # ── Dependency Ordering ───────────────────────────────────────────────────

    @staticmethod
    def _extract_dependency_ordering(cgs: dict[str, Any]) -> tuple[str, ...]:
        """
        Derives execution-order constraints from system depends_on fields.
        "MovementSystem must execute after InputSystem — do not reorder."
        """
        ordering: list[str] = []
        seen: set[str] = set()

        def _process(systems: list[dict]) -> None:
            for sys in systems:
                sid  = sys.get("id", "?")
                deps = sys.get("depends_on", [])
                for dep in deps:
                    stmt = (
                        f"{sid} depends on {dep} — "
                        f"{sid} must execute after {dep}; do not reorder or remove {dep}."
                    )
                    if stmt not in seen:
                        seen.add(stmt)
                        ordering.append(stmt)

        _process(cgs.get("global_systems", []))
        for mode in cgs.get("modes", []):
            _process(mode.get("systems", []))

        return tuple(ordering)

    # ── Mode Invariants ───────────────────────────────────────────────────────

    @staticmethod
    def _extract_mode_invariants(cgs: dict[str, Any]) -> tuple[str, ...]:
        """
        Derives mode-level invariants:
        - Which mode is default
        - Actor control types (Human vs AiProxy vs Scripted)
        """
        invariants: list[str] = []
        seen: set[str] = set()

        for mode in cgs.get("modes", []):
            mid        = mode.get("id", "?")
            is_default = mode.get("is_default", False)

            if is_default:
                stmt = f"'{mid}' is the default mode; it must always exist in the CGS."
                if stmt not in seen:
                    seen.add(stmt)
                    invariants.append(stmt)

            for actor in mode.get("actors", []):
                aid  = actor.get("id", "?")
                ctrl = actor.get("control_type", "?")
                stmt = (
                    f"Actor '{aid}' in mode '{mid}' has control_type='{ctrl}'; "
                    f"this affects which input and AI components are valid for it."
                )
                if stmt not in seen:
                    seen.add(stmt)
                    invariants.append(stmt)

        return tuple(invariants)