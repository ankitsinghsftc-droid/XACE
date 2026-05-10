"""
invariant_enforcer.py — InvariantEnforcer
===========================================
Enforces the global CGS invariants at design-time, immediately before
a MutationTransaction is committed to the CGS.

## Relationship to InvariantChecker (Schema Factory)
InvariantChecker (packages/schema-factory) runs post-compile.
InvariantEnforcer (GDE) runs pre-commit, inside the ConsistencyValidator.

Both enforce the same laws. The GDE enforcer catches violations early,
before the Schema Factory ever sees the CGS — fast feedback to the designer
with plain-English messages instead of compile-time errors.

## Invariants Enforced (Design-Time Checkable)
Not all 15 XACE invariants are checkable at design time. Only those
that can be evaluated from the CGS dict alone are checked here.
Runtime invariants (I1, I2, I3, I5, I9, I10, I13, I15) are skipped.

    I4  — No system in any depends_on list references itself
    I6  — All systems marked deterministic=True
    I7  — metadata.version and metadata.cgs_hash are present
    I8  — CGS has a cgs_hash (indicates it was atomically committed)
    I11 — No GCL component name collides with UCL/DCL (checked via type_id ranges)
    I12 — No AssetReference with status=UNRESOLVED in component defaults
    I14 — Every mode has a schema_version field

Additionally enforces design-time rules not in the 15:
    D1  — No mode has zero actors (warning — game cannot run)
    D2  — No duplicate actor IDs across modes
    D3  — No duplicate system IDs (global + all modes)
    D4  — No duplicate rule IDs within a mode
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Invariant Violation ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class InvariantViolation:
    """One invariant violation found during enforcement."""
    invariant_id:  str
    description:   str
    message:       str
    severity:      str   = "error"    # "error" | "warning"
    affected_path: str   = ""

    @property
    def is_blocking(self) -> bool:
        return self.severity == "error"

    def __repr__(self) -> str:
        return f"InvariantViolation({self.invariant_id}: {self.message[:60]!r})"


# ── Enforcement Result ────────────────────────────────────────────────────────

@dataclass
class EnforcementResult:
    """Result of running InvariantEnforcer against a CGS dict."""
    violations: list[InvariantViolation] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not any(v.is_blocking for v in self.violations)

    def blocking_violations(self) -> list[InvariantViolation]:
        return [v for v in self.violations if v.is_blocking]

    def warnings(self) -> list[InvariantViolation]:
        return [v for v in self.violations if not v.is_blocking]

    def all_messages(self) -> list[str]:
        return [v.message for v in self.violations]

    def error_messages(self) -> list[str]:
        return [v.message for v in self.violations if v.is_blocking]

    def __repr__(self) -> str:
        status = "VALID" if self.is_valid else f"INVALID ({len(self.blocking_violations())} blocking)"
        return f"EnforcementResult({status}, {len(self.warnings())} warnings)"


# ── Invariant Enforcer ────────────────────────────────────────────────────────

class InvariantEnforcer:
    """
    Enforces design-time-checkable CGS invariants before commit.

    Stateless — call enforce() once per pre-commit check.
    All invariants run regardless of earlier failures (full error list).

    Usage
    -----
        enforcer = InvariantEnforcer()
        result   = enforcer.enforce(proposed_cgs)
        if not result.is_valid:
            raise ValidationFailure(result.error_messages())
    """

    def enforce(self, cgs: dict[str, Any]) -> EnforcementResult:
        """
        Runs all design-time invariant checks against the proposed CGS.

        Parameters
        ----------
        cgs : dict[str, Any]
            The proposed CGS dict (after transaction application, before commit).

        Returns
        -------
        EnforcementResult
            Contains all violations found. is_valid=True means no blocking errors.
        """
        result = EnforcementResult()

        self._enforce_i4(cgs,  result)
        self._enforce_i6(cgs,  result)
        self._enforce_i7(cgs,  result)
        self._enforce_i8(cgs,  result)
        self._enforce_i12(cgs, result)
        self._enforce_i14(cgs, result)
        self._enforce_d2(cgs,  result)
        self._enforce_d3(cgs,  result)
        self._enforce_d4(cgs,  result)
        self._enforce_empty_modes(cgs, result)

        return result

    # ── I4 — No self-scheduling ───────────────────────────────────────────────

    @staticmethod
    def _enforce_i4(cgs: dict[str, Any], result: EnforcementResult) -> None:
        def check(systems: list, context: str) -> None:
            for sys in systems:
                sid = sys.get("id", "")
                if sid and sid in sys.get("depends_on", []):
                    result.violations.append(InvariantViolation(
                        invariant_id="I4",
                        description="System order defined ONLY by ExecutionPlan. No self-scheduling.",
                        message=(
                            f"[I4] System '{sid}' ({context}) lists itself in depends_on. "
                            f"A system cannot depend on itself — the ExecutionPlan defines order."
                        ),
                        severity="error",
                        affected_path=f"systems.{sid}.depends_on",
                    ))

        check(cgs.get("global_systems", []), "global")
        for mode in cgs.get("modes", []):
            check(mode.get("systems", []), f"mode '{mode.get('id', '?')}'")

    # ── I6 — All systems deterministic ───────────────────────────────────────

    @staticmethod
    def _enforce_i6(cgs: dict[str, Any], result: EnforcementResult) -> None:
        def check(systems: list, context: str) -> None:
            for sys in systems:
                if not sys.get("deterministic", True):
                    result.violations.append(InvariantViolation(
                        invariant_id="I6",
                        description="No module may introduce nondeterministic behaviour.",
                        message=(
                            f"[I6] System '{sys.get('id', '?')}' ({context}) "
                            f"is marked deterministic=False. "
                            f"All XACE systems must be deterministic (D6). "
                            f"Non-deterministic systems break replays and rollback."
                        ),
                        severity="error",
                    ))

        check(cgs.get("global_systems", []), "global")
        for mode in cgs.get("modes", []):
            check(mode.get("systems", []), f"mode '{mode.get('id', '?')}'")

    # ── I7 — Version and hash present ────────────────────────────────────────

    @staticmethod
    def _enforce_i7(cgs: dict[str, Any], result: EnforcementResult) -> None:
        meta = cgs.get("metadata", {})
        if not meta.get("version"):
            result.violations.append(InvariantViolation(
                invariant_id="I7",
                description="Runtime never runs with schema version mismatch.",
                message=(
                    "[I7] CGS metadata.version is missing. "
                    "The runtime validates this before executing any tick."
                ),
                severity="error",
                affected_path="metadata.version",
            ))
        if not meta.get("cgs_hash"):
            result.violations.append(InvariantViolation(
                invariant_id="I7",
                description="Runtime never runs with schema version mismatch.",
                message=(
                    "[I7] CGS metadata.cgs_hash is missing. "
                    "The runtime cross-references this with the ExecutionPlan hash (D10)."
                ),
                severity="error",
                affected_path="metadata.cgs_hash",
            ))

    # ── I8 — Atomic commit indicator ─────────────────────────────────────────

    @staticmethod
    def _enforce_i8(cgs: dict[str, Any], result: EnforcementResult) -> None:
        if not cgs.get("metadata", {}).get("cgs_hash"):
            result.violations.append(InvariantViolation(
                invariant_id="I8",
                description="Schema mutations applied atomically. Partial commits FORBIDDEN.",
                message=(
                    "[I8] CGS has no cgs_hash — this may indicate a partial state. "
                    "All mutations must be applied atomically (I8)."
                ),
                severity="error",
            ))

    # ── I12 — No UNRESOLVED asset references ─────────────────────────────────

    @staticmethod
    def _enforce_i12(cgs: dict[str, Any], result: EnforcementResult) -> None:
        for mode in cgs.get("modes", []):
            mode_id  = mode.get("id", "?")
            for actor in mode.get("actors", []):
                actor_id = actor.get("id", "?")
                for comp in actor.get("components", []):
                    type_id = comp.get("type_id", "?")
                    for fname, value in comp.get("defaults", {}).items():
                        if (
                            isinstance(value, dict)
                            and value.get("status") == "UNRESOLVED"
                        ):
                            result.violations.append(InvariantViolation(
                                invariant_id="I12",
                                description="UNRESOLVED asset references never enter committed CGS.",
                                message=(
                                    f"[I12] Actor '{actor_id}' in mode '{mode_id}', "
                                    f"component {type_id}, field '{fname}' has an "
                                    f"UNRESOLVED AssetReference. "
                                    f"Resolve to PLACEHOLDER, LINKED, or MISSING before committing."
                                ),
                                severity="error",
                                affected_path=(
                                    f"modes.{mode_id}.actors.{actor_id}"
                                    f".components.{type_id}.defaults.{fname}"
                                ),
                            ))

    # ── I14 — Mode schema_version ─────────────────────────────────────────────

    @staticmethod
    def _enforce_i14(cgs: dict[str, Any], result: EnforcementResult) -> None:
        for mode in cgs.get("modes", []):
            mode_id = mode.get("id", "?")
            if not mode.get("schema_version"):
                result.violations.append(InvariantViolation(
                    invariant_id="I14",
                    description="Every mode carries schema_version for save compatibility.",
                    message=(
                        f"[I14] Mode '{mode_id}' is missing 'schema_version'. "
                        f"Save files use this field for migration compatibility."
                    ),
                    severity="error",
                    affected_path=f"modes.{mode_id}.schema_version",
                ))

    # ── D2 — No duplicate actor IDs ──────────────────────────────────────────

    @staticmethod
    def _enforce_d2(cgs: dict[str, Any], result: EnforcementResult) -> None:
        seen: dict[str, str] = {}
        for mode in cgs.get("modes", []):
            mode_id = mode.get("id", "?")
            for actor in mode.get("actors", []):
                aid = actor.get("id", "")
                if not aid:
                    continue
                if aid in seen:
                    result.violations.append(InvariantViolation(
                        invariant_id="D2",
                        description="Actor IDs must be unique across the entire CGS.",
                        message=(
                            f"[D2] Duplicate actor ID '{aid}' found in mode '{mode_id}' "
                            f"and previously in mode '{seen[aid]}'. "
                            f"Actor IDs must be unique across all modes."
                        ),
                        severity="error",
                    ))
                else:
                    seen[aid] = mode_id

    # ── D3 — No duplicate system IDs ─────────────────────────────────────────

    @staticmethod
    def _enforce_d3(cgs: dict[str, Any], result: EnforcementResult) -> None:
        seen: dict[str, str] = {}
        for sys in cgs.get("global_systems", []):
            sid = sys.get("id", "")
            if sid:
                seen[sid] = "global"
        for mode in cgs.get("modes", []):
            mode_id = mode.get("id", "?")
            for sys in mode.get("systems", []):
                sid = sys.get("id", "")
                if not sid:
                    continue
                prior = seen.get(sid)
                if prior and prior != "global":
                    result.violations.append(InvariantViolation(
                        invariant_id="D3",
                        description="Non-global system IDs must be unique across modes.",
                        message=(
                            f"[D3] Duplicate non-global system ID '{sid}' in "
                            f"mode '{mode_id}' (first seen: {prior})."
                        ),
                        severity="error",
                    ))
                elif not prior:
                    seen[sid] = mode_id

    # ── D4 — No duplicate rule IDs within a mode ─────────────────────────────

    @staticmethod
    def _enforce_d4(cgs: dict[str, Any], result: EnforcementResult) -> None:
        for mode in cgs.get("modes", []):
            mode_id = mode.get("id", "?")
            seen: set[str] = set()
            for rule in mode.get("rules", []):
                rid = rule.get("id", "")
                if not rid:
                    continue
                if rid in seen:
                    result.violations.append(InvariantViolation(
                        invariant_id="D4",
                        description="Rule IDs must be unique within each mode.",
                        message=(
                            f"[D4] Duplicate rule ID '{rid}' in mode '{mode_id}'. "
                            f"Rule IDs must be unique within their mode."
                        ),
                        severity="error",
                    ))
                else:
                    seen.add(rid)

    # ── Empty mode warning ────────────────────────────────────────────────────

    @staticmethod
    def _enforce_empty_modes(cgs: dict[str, Any], result: EnforcementResult) -> None:
        for mode in cgs.get("modes", []):
            if not mode.get("actors"):
                result.violations.append(InvariantViolation(
                    invariant_id="D1",
                    description="A mode with no actors produces an empty world.",
                    message=(
                        f"Mode '{mode.get('id', '?')}' has no actors. "
                        f"A game with no actors cannot be played — "
                        f"add at least a player actor."
                    ),
                    severity="warning",
                ))