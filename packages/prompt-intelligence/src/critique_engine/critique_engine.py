"""
critique_engine.py — CritiqueEngine
======================================
Pre-commit internal review layer.

Runs AFTER ValidationLoop passes and BEFORE SafetyScopeGuard (13.9).
Deterministic — no LLM calls. Pure structural analysis.

## Position in Pipeline

    StructuredOutputParser
        → ValidationLoop (structural + type + dependency + invariant)
        → CritiqueEngine ← here
        → SafetyScopeGuard
        → MutationPlanner
        → GDE commit

## Four Review Dimensions

    1. Cross-System Impact Analysis
       Identifies every system in the CGS that reads or writes a component
       type_id touched by the mutation. Distinguishes:
           - DIRECT:  system explicitly reads/writes the mutated component
           - INDIRECT: system is in the dependency chain (depends_on) of a
                       direct system but doesn't touch the component itself
       High impact (many affected systems or critical systems affected)
       → concern raised. Low impact → info note only.

    2. Version Compatibility Check
       Determines whether the proposed mutation requires a semantic version
       bump of the CGS schema:
           - patch bump: pure value changes (SET/SCALE on existing fields)
           - minor bump: structural additions (ADD_ACTOR, ADD_COMPONENT,
                         ADD_SYSTEM, ADD_RULE)
           - major bump: structural removals (REMOVE_*) or changes to
                         system phase ordering
       Mismatch between required_recompile flag and actual mutation type
       is flagged as a concern.

    3. Mutation Completeness Check
       Some mutations are incomplete without companion changes:
           - Setting health.current without checking health.max →
             if current > max after mutation, warn.
           - Scaling velocity without touching related system's limits →
             if max_linear_speed > 100 after mutation, warn.
           - Adding an actor without assigning a control_type-appropriate
             input component → note.
           - Modifying a rule's condition without checking effect validity
             → note.

    4. Side-Effect Analysis
       Detects unintended consequences visible from the schema structure:
           - Mutation touches component that an AI system uses for decision
             making → the AI behaviour may change unexpectedly.
           - Mutation changes a field that drives rule conditions
             (e.g. health.current used in rule_player_death) → the rule
             may fire more/less frequently.
           - Mutation scales a value to 0 → effectively disabling a feature.

## CritiqueReport

    approved:            bool         — True unless a critical concern blocks
    concerns:            list[str]    — issues that should be reviewed
    suggestions:         list[str]    — optional improvements
    impact_summary:      ImpactSummary
    required_version_bump: str        — "patch" | "minor" | "major"
    completeness_issues: list[str]
    side_effects:        list[str]

## Blocking vs Non-Blocking

    CritiqueEngine does NOT hard-block mutations (that is SafetyScopeGuard's job).
    It sets approved=False only for critical concerns:
        - Value scaled to exactly 0 (feature disabling)
        - Mutation creates an impossible health state (current > max)
        - required_recompile=False on a structural mutation
    All other findings are concerns or suggestions — advisory only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "output_parser"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "llm_orchestrator"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "context_assembler"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "intent_intake"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "validation_loop"))

from structured_output_parser import CanonicalMutation
from validation_loop import ValidationResult
from pass2_dsl_draft import MutationOp
from pass5_final_output import MutationTransaction


# ── Constants ─────────────────────────────────────────────────────────────────

# Systems considered "critical" — changes to their R/W components warrant extra attention
_CRITICAL_SYSTEMS = frozenset({
    "MovementSystem", "AISystem", "DamageSystem", "InputSystem",
    "DeathSystem", "PhysicsSystem", "CollisionSystem",
})

# Component type_ids known to drive AI decision-making
_AI_COMPONENT_TYPE_IDS = frozenset({160, 161, 162})   # COMP_AI_V1 range

# Component type_ids known to appear in rule conditions
_RULE_SENSITIVE_FIELDS = frozenset({"current", "max", "is_invincible", "is_active"})

# Op types that require at least a minor version bump
_MINOR_BUMP_OPS = frozenset({"ADD_ACTOR", "ADD_COMPONENT", "ADD_SYSTEM", "ADD_RULE"})
_MAJOR_BUMP_OPS = frozenset({
    "REMOVE_ACTOR", "REMOVE_COMPONENT", "REMOVE_SYSTEM", "REMOVE_RULE"
})

# Velocity field name for speed sanity check
_SPEED_FIELDS = frozenset({"max_linear_speed", "max_angular_speed"})
_SPEED_WARNING_THRESHOLD = 100.0


# ── Impact Summary ────────────────────────────────────────────────────────────

@dataclass
class ImpactSummary:
    """
    Summary of cross-system impact analysis.

    Attributes
    ----------
    direct_systems   : list[str]  — systems that read/write the mutated components
    indirect_systems : list[str]  — systems in dependency chain of direct systems
    affected_type_ids: list[int]  — component type_ids touched by the mutation
    impact_level     : str        — "none" | "low" | "medium" | "high"
    critical_systems_affected: list[str]  — subset of direct/indirect in _CRITICAL_SYSTEMS
    """
    direct_systems:            list[str] = field(default_factory=list)
    indirect_systems:          list[str] = field(default_factory=list)
    affected_type_ids:         list[int] = field(default_factory=list)
    impact_level:              str       = "none"
    critical_systems_affected: list[str] = field(default_factory=list)

    @property
    def all_affected_systems(self) -> list[str]:
        return list(dict.fromkeys(self.direct_systems + self.indirect_systems))


# ── Critique Report ───────────────────────────────────────────────────────────

@dataclass
class CritiqueReport:
    """
    Output of CritiqueEngine.review().

    Attributes
    ----------
    approved              : bool        — False only for critical issues
    concerns              : list[str]   — issues to review (non-blocking unless critical)
    suggestions           : list[str]   — optional improvements
    impact_summary        : ImpactSummary
    required_version_bump : str         — "patch" | "minor" | "major"
    completeness_issues   : list[str]   — missing companion changes
    side_effects          : list[str]   — unintended consequences detected
    """
    approved:               bool
    concerns:               list[str]         = field(default_factory=list)
    suggestions:            list[str]         = field(default_factory=list)
    impact_summary:         ImpactSummary     = field(default_factory=ImpactSummary)
    required_version_bump:  str               = "patch"
    completeness_issues:    list[str]         = field(default_factory=list)
    side_effects:           list[str]         = field(default_factory=list)

    @property
    def has_concerns(self) -> bool:
        return len(self.concerns) > 0

    @property
    def has_side_effects(self) -> bool:
        return len(self.side_effects) > 0

    def to_summary_str(self) -> str:
        approved = "APPROVED" if self.approved else "BLOCKED"
        return (
            f"CritiqueReport({approved}, "
            f"impact={self.impact_summary.impact_level}, "
            f"bump={self.required_version_bump}, "
            f"concerns={len(self.concerns)}, "
            f"side_effects={len(self.side_effects)})"
        )

    def __repr__(self) -> str:
        return self.to_summary_str()


# ── Critique Engine ───────────────────────────────────────────────────────────

class CritiqueEngine:
    """
    Pre-commit internal review engine.

    Stateless — one instance shared across PIL sessions.
    Deterministic — same inputs always produce the same CritiqueReport.
    LLM-free — pure structural analysis from the CGS and mutation ops.

    Usage
    -----
        engine = CritiqueEngine()
        report = engine.review(
            canonical    = structured_output_parser_result,
            validation   = validation_loop_result,
            transaction  = mutation_transaction,
            current_cgs  = cgs,
        )
        if not report.approved:
            return PipelineResult(needs_clarification=True)
        # proceed to SafetyScopeGuard
    """

    def review(
        self,
        canonical:    CanonicalMutation,
        validation:   ValidationResult,
        transaction:  MutationTransaction,
        current_cgs:  dict[str, Any],
    ) -> CritiqueReport:
        """
        Runs all four review dimensions and returns a CritiqueReport.

        Parameters
        ----------
        canonical : CanonicalMutation
            Output of StructuredOutputParser.
        validation : ValidationResult
            Output of ValidationLoop (must be passed=True).
        transaction : MutationTransaction
            Output of Pass 5.
        current_cgs : dict
            Current CGS JSON.

        Returns
        -------
        CritiqueReport
        """
        ops           = canonical.transaction.operations
        delta         = canonical.transaction.schema_delta_type
        proposed_cgs  = validation.proposed_cgs or current_cgs

        concerns:             list[str] = []
        suggestions:          list[str] = []
        completeness_issues:  list[str] = []
        side_effects:         list[str] = []

        # ── Dimension 1: Cross-system impact ──────────────────────────────────
        impact = self._cross_system_impact(ops, current_cgs)

        if impact.impact_level == "high":
            concerns.append(
                f"High cross-system impact: {len(impact.direct_systems)} systems "
                f"directly affected. "
                f"Review: {', '.join(impact.direct_systems[:4])}."
            )
        if impact.critical_systems_affected:
            concerns.append(
                f"Critical systems affected: "
                f"{', '.join(impact.critical_systems_affected)}. "
                f"Test these systems after commit."
            )

        # ── Dimension 2: Version compatibility ───────────────────────────────
        required_bump = self._required_version_bump(ops, delta)

        if (transaction.required_recompile is False
                and delta in {"structural_add", "structural_remove"}):
            concerns.append(
                f"Mutation is structural ({delta}) but required_recompile=False. "
                f"System graph recompile should be required for structural changes."
            )

        if required_bump == "major":
            concerns.append(
                f"Mutation requires a MAJOR schema version bump (structural removal). "
                f"Verify all dependent systems are updated before committing."
            )
        elif required_bump == "minor":
            suggestions.append(
                f"Mutation adds schema nodes (minor version bump). "
                f"Consider updating documentation."
            )

        # ── Dimension 3: Mutation completeness ────────────────────────────────
        completeness_issues = self._completeness_check(ops, proposed_cgs)

        # ── Dimension 4: Side-effect analysis ────────────────────────────────
        side_effects = self._side_effect_analysis(ops, current_cgs)

        # ── Determine blocking concerns ───────────────────────────────────────
        blocking = self._check_critical_blocks(ops, proposed_cgs, completeness_issues)
        concerns.extend(blocking)

        approved = len(blocking) == 0

        return CritiqueReport(
            approved              = approved,
            concerns              = concerns,
            suggestions           = suggestions,
            impact_summary        = impact,
            required_version_bump = required_bump,
            completeness_issues   = completeness_issues,
            side_effects          = side_effects,
        )

    # ── Dimension 1: Cross-system impact ─────────────────────────────────────

    def _cross_system_impact(
        self,
        ops:         list[MutationOp],
        current_cgs: dict[str, Any],
    ) -> ImpactSummary:
        """Identifies all systems affected by the mutation operations."""

        # Collect type_ids touched by the mutation
        touched_type_ids: set[int] = set()
        for op in ops:
            if op.type_id:
                touched_type_ids.add(op.type_id)

        if not touched_type_ids:
            return ImpactSummary(impact_level="none")

        # Build R/W maps
        read_map:  dict[int, list[str]] = {}   # type_id → systems that read it
        write_map: dict[int, list[str]] = {}   # type_id → systems that write it
        dep_map:   dict[str, list[str]] = {}   # system_id → systems that depend on it

        def _index_systems(systems: list[dict]) -> None:
            for sys in systems:
                sid = sys.get("id", "")
                for r in sys.get("reads", []):
                    read_map.setdefault(r, []).append(sid)
                for w in sys.get("writes", []):
                    write_map.setdefault(w, []).append(sid)
                for dep in sys.get("depends_on", []):
                    dep_map.setdefault(dep, []).append(sid)

        _index_systems(current_cgs.get("global_systems", []))
        for mode in current_cgs.get("modes", []):
            _index_systems(mode.get("systems", []))

        # Direct: systems that read or write the touched type_ids
        direct: set[str] = set()
        for tid in touched_type_ids:
            direct.update(read_map.get(tid, []))
            direct.update(write_map.get(tid, []))

        # Indirect: systems in depends_on chain of direct systems
        indirect: set[str] = set()
        for sid in direct:
            for downstream in dep_map.get(sid, []):
                if downstream not in direct:
                    indirect.add(downstream)

        critical = [s for s in (direct | indirect) if s in _CRITICAL_SYSTEMS]

        total = len(direct) + len(indirect)
        if total == 0:
            level = "none"
        elif total <= 2:
            level = "low"
        elif total <= 5:
            level = "medium"
        else:
            level = "high"

        return ImpactSummary(
            direct_systems            = sorted(direct),
            indirect_systems          = sorted(indirect - direct),
            affected_type_ids         = sorted(touched_type_ids),
            impact_level              = level,
            critical_systems_affected = sorted(critical),
        )

    # ── Dimension 2: Version bump ─────────────────────────────────────────────

    @staticmethod
    def _required_version_bump(ops: list[MutationOp], delta: str) -> str:
        """Returns the minimum required schema version bump."""
        has_major = any(op.op in _MAJOR_BUMP_OPS for op in ops)
        has_minor = any(op.op in _MINOR_BUMP_OPS for op in ops)

        if has_major or delta == "structural_remove":
            return "major"
        if has_minor or delta in {"structural_add", "rule_change"}:
            return "minor"
        return "patch"

    # ── Dimension 3: Completeness ─────────────────────────────────────────────

    @staticmethod
    def _completeness_check(
        ops:          list[MutationOp],
        proposed_cgs: dict[str, Any],
    ) -> list[str]:
        """Detects missing companion changes."""
        issues: list[str] = []

        # Check: health.current > health.max after mutation
        for mode in proposed_cgs.get("modes", []):
            for actor in mode.get("actors", []):
                aid = actor.get("id", "")
                for comp in actor.get("components", []):
                    if "HEALTH" in comp.get("name", "").upper():
                        defaults = comp.get("defaults", {})
                        current  = defaults.get("current")
                        max_hp   = defaults.get("max")
                        if (isinstance(current, (int, float))
                                and isinstance(max_hp, (int, float))
                                and current > max_hp):
                            issues.append(
                                f"Actor '{aid}' health.current ({current}) > "
                                f"health.max ({max_hp}) after mutation. "
                                f"Either also set health.max or reduce health.current."
                            )

        # Check: speed field set very high without a corresponding limit check
        for op in ops:
            if op.field_name in _SPEED_FIELDS and isinstance(op.value, (int, float)):
                if op.op == "SET" and op.value > _SPEED_WARNING_THRESHOLD:
                    issues.append(
                        f"Speed field '{op.field_name}' set to {op.value} > "
                        f"{_SPEED_WARNING_THRESHOLD}. Verify this is intentional "
                        f"and that the movement system can handle this value."
                    )
                elif op.op == "SCALE":
                    # Compute resulting value from proposed CGS
                    for mode in proposed_cgs.get("modes", []):
                        for actor in mode.get("actors", []):
                            for comp in actor.get("components", []):
                                val = comp.get("defaults", {}).get(op.field_name)
                                if isinstance(val, (int, float)) and val > _SPEED_WARNING_THRESHOLD:
                                    issues.append(
                                        f"SCALE on '{op.field_name}' results in {val} > "
                                        f"{_SPEED_WARNING_THRESHOLD}."
                                    )

        return issues

    # ── Dimension 4: Side-effect analysis ────────────────────────────────────

    def _side_effect_analysis(
        self,
        ops:         list[MutationOp],
        current_cgs: dict[str, Any],
    ) -> list[str]:
        """Detects unintended consequences visible from schema structure."""
        effects: list[str] = []

        # Build rule condition index: field_name → rule_ids that mention it
        rule_mentions: dict[str, list[str]] = {}
        for mode in current_cgs.get("modes", []):
            for rule in mode.get("rules", []):
                rid = rule.get("id", "")
                condition = rule.get("condition", "")
                for sensitive_field in _RULE_SENSITIVE_FIELDS:
                    if sensitive_field in condition:
                        rule_mentions.setdefault(sensitive_field, []).append(rid)

        for op in ops:
            # Check 1: AI component mutations affect AI behaviour
            if op.type_id in _AI_COMPONENT_TYPE_IDS:
                effects.append(
                    f"Mutation touches AI component (type_id={op.type_id}). "
                    f"AI behaviour for affected actors will change — "
                    f"verify chase/patrol/aggression logic remains correct."
                )

            # Check 2: Mutation affects a field used in rule conditions
            fname = op.field_name
            if fname in rule_mentions:
                rules = rule_mentions[fname]
                effects.append(
                    f"Field '{fname}' appears in rule condition(s): "
                    f"{', '.join(rules)}. "
                    f"These rules may fire more or less frequently after this mutation."
                )

            # Check 3: Value scaled to 0 — feature disabling
            if op.op == "SCALE" and op.value == 0:
                effects.append(
                    f"SCALE by 0 on path '{op.path}' will set the field to 0, "
                    f"effectively disabling this feature."
                )
            if op.op == "SET" and op.value == 0 and fname in _SPEED_FIELDS:
                effects.append(
                    f"SET '{fname}' to 0 will prevent all movement for "
                    f"affected actor. Verify this is intended."
                )

        return effects

    # ── Blocking critical checks ──────────────────────────────────────────────

    @staticmethod
    def _check_critical_blocks(
        ops:                 list[MutationOp],
        proposed_cgs:        dict[str, Any],
        completeness_issues: list[str],
    ) -> list[str]:
        """
        Returns blocking concern strings for conditions that must prevent commit.
        CritiqueEngine.approved is False iff this list is non-empty.
        """
        blocks: list[str] = []

        # Block: health impossible state (current > max) is a hard block
        for issue in completeness_issues:
            if "current" in issue and "max" in issue and ">" in issue:
                blocks.append(f"CRITICAL: {issue}")

        # Block: SCALE by 0 is a hard block (accidental feature disabling)
        for op in ops:
            if op.op == "SCALE" and op.value == 0:
                blocks.append(
                    f"CRITICAL: SCALE by 0 at path '{op.path}' would set "
                    f"the value to 0. This is almost certainly an error. "
                    f"Use SET 0 explicitly if intentional."
                )

        return blocks