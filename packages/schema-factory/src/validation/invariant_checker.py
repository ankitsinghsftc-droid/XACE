"""
invariant_checker.py — InvariantChecker
=========================================
Checks all global invariants (I1–I15) from CLAUDE.md against a validated
CGS dict and its associated registries.

Runs AFTER SchemaValidationContract — assumes structural correctness.

## Invariant Status

Statically checkable (checked here):
    I4  — No self-scheduling in depends_on
    I6  — All systems marked deterministic=True
    I7  — metadata.version and cgs_hash present
    I8  — cgs_hash present (atomic commit indicator)
    I11 — GCL namespace isolation (name + type_id range)
    I12 — No UNRESOLVED AssetReferences
    I14 — Every mode has schema_version

Runtime-only (not_checkable=True, always pass here):
    I1  — Component tables never contain EntityIDs not in EntityStore
    I2  — ALL structural changes through Mutation Gate
    I3  — CGS is single source of truth
    I5  — Engine adapters mirror state only
    I9  — Events never modify state directly
    I10 — Snapshot restore reconstructs world state exactly
    I13 — Engine feedback at tick boundaries only
    I15 — Same WorldSnapshot + ProgressSave → identical gameplay
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..component_registry.component_definition_registry import (
        ComponentDefinitionRegistry,
    )


# ── Invariant Result ──────────────────────────────────────────────────────────

@dataclass
class InvariantResult:
    """Result of checking one invariant."""

    invariant_id:  str
    description:   str
    passed:        bool
    errors:        list[str] = field(default_factory=list)
    not_checkable: bool      = False   # True for runtime-only invariants

    def __repr__(self) -> str:
        if self.not_checkable:
            status = "N/A (runtime)"
        elif self.passed:
            status = "PASS"
        else:
            status = f"FAIL ({len(self.errors)} violation(s))"
        return f"InvariantResult({self.invariant_id}: {status})"


# ── Invariant Report ──────────────────────────────────────────────────────────

@dataclass
class InvariantReport:
    """Full report from InvariantChecker, one result per invariant I1–I15."""

    results: list[InvariantResult] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return all(r.passed or r.not_checkable for r in self.results)

    def failed_invariants(self) -> list[InvariantResult]:
        return [r for r in self.results if not r.passed and not r.not_checkable]

    def all_errors(self) -> list[str]:
        errors: list[str] = []
        for r in self.results:
            errors.extend(r.errors)
        return errors

    def get(self, invariant_id: str) -> InvariantResult | None:
        for r in self.results:
            if r.invariant_id == invariant_id:
                return r
        return None

    def summary(self) -> str:
        checkable = [r for r in self.results if not r.not_checkable]
        passed    = sum(1 for r in checkable if r.passed)
        failed    = len(checkable) - passed
        runtime   = len(self.results) - len(checkable)
        return (
            f"Invariants: {passed}/{len(checkable)} passed, "
            f"{failed} failed, {runtime} runtime-only (N/A)"
        )

    def __repr__(self) -> str:
        return f"InvariantReport({self.summary()})"


# ── Invariant Checker ─────────────────────────────────────────────────────────

class InvariantChecker:
    """
    Checks all 15 global XACE invariants against a CGS dict.

    Usage
    -----
        checker = InvariantChecker(component_registry)
        report  = checker.check(cgs)
        if not report.is_valid:
            raise InvariantViolation(report.all_errors())
    """

    # Runtime-only invariants — always recorded as not_checkable
    _RUNTIME_INVARIANTS: list[tuple[str, str]] = [
        ("I1",  "Component tables never contain EntityIDs not in EntityStore"),
        ("I2",  "ALL structural changes through Mutation Gate"),
        ("I3",  "CGS is single source of truth"),
        ("I5",  "Engine adapters mirror state only"),
        ("I9",  "Events never modify state directly"),
        ("I10", "Snapshot restore reconstructs world state exactly"),
        ("I13", "Engine feedback at tick boundaries only"),
        ("I15", "Same WorldSnapshot + ProgressSave → identical gameplay"),
    ]

    def __init__(
        self,
        component_registry: "ComponentDefinitionRegistry",
    ) -> None:
        self._components = component_registry

    def check(self, cgs: dict[str, Any]) -> InvariantReport:
        """
        Runs all 15 invariant checks and returns a full InvariantReport.
        All invariants run regardless of earlier failures.
        Results are sorted I1 → I15 (D11).
        """
        report = InvariantReport()

        # Runtime-only — always pass
        for iid, desc in self._RUNTIME_INVARIANTS:
            report.results.append(InvariantResult(
                invariant_id=iid,
                description=desc,
                passed=True,
                not_checkable=True,
            ))

        # Statically checkable
        report.results.extend([
            self._check_i4(cgs),
            self._check_i6(cgs),
            self._check_i7(cgs),
            self._check_i8(cgs),
            self._check_i11(),
            self._check_i12(cgs),
            self._check_i14(cgs),
        ])

        # Sort I1 → I15 for deterministic report order (D11)
        report.results.sort(key=lambda r: _sort_key(r.invariant_id))
        return report

    # ── I4 ────────────────────────────────────────────────────────────────────

    @staticmethod
    def _check_i4(cgs: dict[str, Any]) -> InvariantResult:
        """No system lists itself in depends_on (no self-scheduling)."""
        errors: list[str] = []

        def scan(systems: list, ctx: str) -> None:
            for sys in systems:
                sid = sys.get("id", "")
                if sid and sid in sys.get("depends_on", []):
                    errors.append(
                        f"[I4] System '{sid}' ({ctx}) depends_on itself. "
                        f"Self-scheduling is prohibited — system order comes "
                        f"from the ExecutionPlan only (I4)."
                    )

        scan(cgs.get("global_systems", []), "global")
        for mode in cgs.get("modes", []):
            scan(mode.get("systems", []), f"mode '{mode.get('id', '?')}'")

        return InvariantResult(
            invariant_id="I4",
            description="System order defined ONLY by ExecutionPlan. No self-scheduling.",
            passed=not errors,
            errors=errors,
        )

    # ── I6 ────────────────────────────────────────────────────────────────────

    @staticmethod
    def _check_i6(cgs: dict[str, Any]) -> InvariantResult:
        """All systems must be deterministic=True."""
        errors: list[str] = []

        def scan(systems: list, ctx: str) -> None:
            for sys in systems:
                if not sys.get("deterministic", True):
                    errors.append(
                        f"[I6] System '{sys.get('id', '?')}' ({ctx}) is "
                        f"deterministic=False. All systems must be deterministic "
                        f"(I6, D6). Non-deterministic systems break replays."
                    )

        scan(cgs.get("global_systems", []), "global")
        for mode in cgs.get("modes", []):
            scan(mode.get("systems", []), f"mode '{mode.get('id', '?')}'")

        return InvariantResult(
            invariant_id="I6",
            description="No module may introduce nondeterministic behaviour into runtime.",
            passed=not errors,
            errors=errors,
        )

    # ── I7 ────────────────────────────────────────────────────────────────────

    @staticmethod
    def _check_i7(cgs: dict[str, Any]) -> InvariantResult:
        """metadata.version and cgs_hash are both present and non-empty."""
        errors:   list[str] = []
        metadata = cgs.get("metadata", {})

        if not metadata.get("version"):
            errors.append(
                "[I7] CGS metadata.version is missing. "
                "The runtime validates this against the ExecutionPlan version "
                "before executing any tick (I7, D10)."
            )
        if not metadata.get("cgs_hash"):
            errors.append(
                "[I7] CGS metadata.cgs_hash is missing. "
                "The runtime cross-references this with the ExecutionPlan "
                "compiled_from_cgs_hash to detect stale plans (D10)."
            )

        return InvariantResult(
            invariant_id="I7",
            description="Runtime never runs with schema version mismatch.",
            passed=not errors,
            errors=errors,
        )

    # ── I8 ────────────────────────────────────────────────────────────────────

    @staticmethod
    def _check_i8(cgs: dict[str, Any]) -> InvariantResult:
        """CGS has a cgs_hash, indicating it was committed atomically."""
        errors: list[str] = []
        if not cgs.get("metadata", {}).get("cgs_hash"):
            errors.append(
                "[I8] CGS has no cgs_hash — this indicates a partial or "
                "uncommitted state. All mutations must be applied atomically "
                "via SchemaVersionManager.bump_*() before use (I8)."
            )

        return InvariantResult(
            invariant_id="I8",
            description="Schema mutations applied atomically. Partial commits FORBIDDEN.",
            passed=not errors,
            errors=errors,
        )

    # ── I11 ───────────────────────────────────────────────────────────────────

    def _check_i11(self) -> InvariantResult:
        """GCL components: no UCL/DCL name collision, type_ids >= 10000."""
        errors: list[str] = []

        for err in self._components.validate_gcl_no_collision():
            errors.append(f"[I11] {err}")

        for defn in self._components.gcl_definitions():
            if defn.type_id < 10_000:
                errors.append(
                    f"[I11] GCL component '{defn.name}' type_id={defn.type_id} "
                    f"is below the GCL minimum (10000). "
                    f"GCL type_ids must be >= 10000 (I11)."
                )

        return InvariantResult(
            invariant_id="I11",
            description="GCL components never enter DCL or UCL namespaces.",
            passed=not errors,
            errors=errors,
        )

    # ── I12 ───────────────────────────────────────────────────────────────────

    @staticmethod
    def _check_i12(cgs: dict[str, Any]) -> InvariantResult:
        """No UNRESOLVED AssetReferences in committed CGS."""
        errors: list[str] = []

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
                            errors.append(
                                f"[I12] Actor '{actor_id}' mode '{mode_id}' "
                                f"component {type_id} field '{fname}' has "
                                f"UNRESOLVED AssetReference. "
                                f"PLACEHOLDER/LINKED/MISSING are permitted (I12)."
                            )

        return InvariantResult(
            invariant_id="I12",
            description="UNRESOLVED asset references never enter committed CGS.",
            passed=not errors,
            errors=errors,
        )

    # ── I14 ───────────────────────────────────────────────────────────────────

    @staticmethod
    def _check_i14(cgs: dict[str, Any]) -> InvariantResult:
        """Every mode carries schema_version for save file compatibility."""
        errors: list[str] = []

        for mode in cgs.get("modes", []):
            mode_id = mode.get("id", "?")
            if not mode.get("schema_version"):
                errors.append(
                    f"[I14] Mode '{mode_id}' missing 'schema_version'. "
                    f"Save files record this to identify schema compatibility "
                    f"for migration (I14, Audit 7)."
                )

        return InvariantResult(
            invariant_id="I14",
            description="Every mode carries schema_version for save compatibility.",
            passed=not errors,
            errors=errors,
        )


# ── Sort Helper (D11) ─────────────────────────────────────────────────────────

def _sort_key(invariant_id: str) -> int:
    try:
        return int(invariant_id.lstrip("I"))
    except ValueError:
        return 999