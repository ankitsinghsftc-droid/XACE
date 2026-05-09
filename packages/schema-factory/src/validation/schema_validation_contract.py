"""
schema_validation_contract.py — SchemaValidationContract
==========================================================
Full structural validation of a CGS dict before it is committed.

This is the last gate before a MutationTransaction is applied to the CGS.
If any check here fails, the transaction is rejected in its entirety (I8).

## Responsibility Division
SchemaValidationContract answers: "Is this CGS structurally consistent?"
InvariantChecker answers: "Does this CGS obey the global laws?"

Both must pass for a CGS commit to proceed. SchemaValidationContract runs
first because InvariantChecker assumes structural correctness.

## What Is Checked Here
    C1  — All actor IDs are unique across the entire CGS (all modes)
    C2  — All system IDs are unique across the entire CGS
    C3  — All rule IDs are unique within each mode
    C4  — Every system depends_on resolves to a known system ID
    C5  — Every component type_id referenced by any actor exists in the registry
    C6  — Every component type_id in system reads/writes exists in the registry
    C8  — No AssetReference has status UNRESOLVED (I12)
    C9  — Every mode has a schema_version field (I14 — save compatibility)
    C10 — At least one mode is marked is_default=True
    C11 — The CGS metadata.version field is present and valid
    C12 — Global system ID overrides by mode systems are flagged (warning)
    C13 — The CGS metadata.cgs_hash is non-empty
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..component_registry.component_definition_registry import (
        ComponentDefinitionRegistry,
    )


# ── Validation Report ─────────────────────────────────────────────────────────

@dataclass
class ValidationReport:
    """
    Result of running SchemaValidationContract against a CGS dict.

    Attributes
    ----------
    errors : list[str]
        Hard failures. CGS commit must be blocked if non-empty.
    warnings : list[str]
        Soft issues. Commit is allowed but surfaced to the designer.
    """

    errors:   list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    def error_count(self) -> int:
        return len(self.errors)

    def merge(self, other: "ValidationReport") -> None:
        """Merges another report into this one in-place."""
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)

    def __repr__(self) -> str:
        status = "VALID" if self.is_valid else f"INVALID ({len(self.errors)} errors)"
        return f"ValidationReport({status}, {len(self.warnings)} warnings)"


# ── Schema Validation Contract ────────────────────────────────────────────────

class SchemaValidationContract:
    """
    Validates a full CGS dict for structural consistency.

    Stateless — one call to validate() per transaction pre-commit check.
    All checks are read-only; the CGS dict is never mutated.

    Usage
    -----
        contract = SchemaValidationContract(component_registry)
        report   = contract.validate(cgs_dict)
        if not report.is_valid:
            raise ValidationFailure(report.errors)
    """

    def __init__(self, component_registry: "ComponentDefinitionRegistry") -> None:
        self._registry = component_registry

    def validate(self, cgs: dict[str, Any]) -> ValidationReport:
        """
        Runs all structural checks against the CGS dict.
        Collects every error and warning before returning — never stop-at-first.
        """
        report = ValidationReport()

        self._check_metadata(cgs, report)
        self._check_cgs_hash_present(cgs, report)
        self._check_default_mode(cgs, report)
        self._check_actor_id_uniqueness(cgs, report)
        self._check_system_id_uniqueness(cgs, report)
        self._check_rule_id_uniqueness(cgs, report)

        all_system_ids = self._collect_all_system_ids(cgs)
        self._check_system_dependency_refs(cgs, all_system_ids, report)
        self._check_actor_component_refs(cgs, report)
        self._check_system_component_refs(cgs, report)
        self._check_unresolved_asset_refs(cgs, report)
        self._check_mode_schema_versions(cgs, report)
        self._check_global_system_overrides(cgs, report)

        return report

    # ── C11 — Metadata ────────────────────────────────────────────────────────

    @staticmethod
    def _check_metadata(cgs: dict[str, Any], report: ValidationReport) -> None:
        metadata = cgs.get("metadata", {})
        if not isinstance(metadata, dict):
            report.errors.append(
                "CGS 'metadata' must be a dict with 'version' and 'name'."
            )
            return

        version = metadata.get("version", "")
        if not version:
            report.errors.append(
                "CGS metadata.version is missing. Format: MAJOR.MINOR.PATCH."
            )
        else:
            parts = str(version).split(".")
            if len(parts) != 3 or not all(p.isdigit() for p in parts):
                report.errors.append(
                    f"CGS metadata.version '{version}' is not a valid "
                    f"MAJOR.MINOR.PATCH string."
                )

        if not str(metadata.get("name", "")).strip():
            report.warnings.append(
                "CGS metadata.name is missing. Provide a name for the game."
            )

    # ── C13 — CGS hash present ────────────────────────────────────────────────

    @staticmethod
    def _check_cgs_hash_present(
        cgs: dict[str, Any], report: ValidationReport
    ) -> None:
        if not cgs.get("metadata", {}).get("cgs_hash", ""):
            report.errors.append(
                "CGS metadata.cgs_hash is missing. "
                "SchemaVersionManager must set this before committing."
            )

    # ── C10 — Default mode ────────────────────────────────────────────────────

    @staticmethod
    def _check_default_mode(
        cgs: dict[str, Any], report: ValidationReport
    ) -> None:
        modes = cgs.get("modes", [])
        if not isinstance(modes, list) or not modes:
            report.errors.append(
                "CGS 'modes' must be a non-empty list. "
                "Every game must have at least one mode."
            )
            return

        defaults = [m for m in modes if m.get("is_default", False)]
        if not defaults:
            report.errors.append(
                "No mode is marked 'is_default: true'. "
                "Exactly one mode must be the default entry point."
            )
        elif len(defaults) > 1:
            ids = sorted(m.get("id", "?") for m in defaults)
            report.errors.append(
                f"Multiple modes marked 'is_default': {ids}. "
                f"Exactly one mode must be default."
            )

    # ── C1 — Actor ID uniqueness ──────────────────────────────────────────────

    @staticmethod
    def _check_actor_id_uniqueness(
        cgs: dict[str, Any], report: ValidationReport
    ) -> None:
        seen: dict[str, str] = {}
        for mode in cgs.get("modes", []):
            mode_id = mode.get("id", "?")
            for actor in mode.get("actors", []):
                aid = actor.get("id", "")
                if not aid:
                    continue
                if aid in seen:
                    report.errors.append(
                        f"Duplicate actor ID '{aid}' in mode '{mode_id}' "
                        f"(also in mode '{seen[aid]}'). "
                        f"Actor IDs must be unique across the entire CGS."
                    )
                else:
                    seen[aid] = mode_id

    # ── C2 — System ID uniqueness ─────────────────────────────────────────────

    @staticmethod
    def _check_system_id_uniqueness(
        cgs: dict[str, Any], report: ValidationReport
    ) -> None:
        seen: dict[str, str] = {}

        for sys in cgs.get("global_systems", []):
            sid = sys.get("id", "")
            if not sid:
                continue
            if sid in seen:
                report.errors.append(
                    f"Duplicate system ID '{sid}' in global_systems "
                    f"(first seen: {seen[sid]})."
                )
            else:
                seen[sid] = "global_systems"

        for mode in cgs.get("modes", []):
            mode_id = mode.get("id", "?")
            for sys in mode.get("systems", []):
                sid = sys.get("id", "")
                if not sid:
                    continue
                context = f"mode '{mode_id}'"
                # Mode systems may intentionally share a global ID (override) —
                # duplication is only an error across non-global mode systems.
                if sid in seen and seen[sid] != "global_systems":
                    report.errors.append(
                        f"Duplicate system ID '{sid}' in mode '{mode_id}' "
                        f"(first seen: {seen[sid]}). "
                        f"Non-global system IDs must be unique across modes."
                    )
                elif sid not in seen:
                    seen[sid] = context

    # ── C3 — Rule ID uniqueness within each mode ──────────────────────────────

    @staticmethod
    def _check_rule_id_uniqueness(
        cgs: dict[str, Any], report: ValidationReport
    ) -> None:
        for mode in cgs.get("modes", []):
            mode_id = mode.get("id", "?")
            seen: set[str] = set()
            for rule in mode.get("rules", []):
                rid = rule.get("id", "")
                if not rid:
                    continue
                if rid in seen:
                    report.errors.append(
                        f"Duplicate rule ID '{rid}' in mode '{mode_id}'."
                    )
                else:
                    seen.add(rid)

    # ── C4 — System dependency references ─────────────────────────────────────

    @staticmethod
    def _check_system_dependency_refs(
        cgs:            dict[str, Any],
        all_system_ids: set[str],
        report:         ValidationReport,
    ) -> None:
        def check(sys: dict, context: str) -> None:
            sid = sys.get("id", "?")
            for dep in sys.get("depends_on", []):
                if dep == sid:
                    report.errors.append(
                        f"System '{sid}' ({context}) depends_on itself."
                    )
                elif dep not in all_system_ids:
                    report.errors.append(
                        f"System '{sid}' ({context}) depends_on '{dep}' "
                        f"which is not registered in the CGS."
                    )

        for sys in cgs.get("global_systems", []):
            check(sys, "global")
        for mode in cgs.get("modes", []):
            mode_id = mode.get("id", "?")
            for sys in mode.get("systems", []):
                check(sys, f"mode '{mode_id}'")

    # ── C5 — Actor component refs ─────────────────────────────────────────────

    def _check_actor_component_refs(
        self, cgs: dict[str, Any], report: ValidationReport
    ) -> None:
        for mode in cgs.get("modes", []):
            mode_id  = mode.get("id", "?")
            for actor in mode.get("actors", []):
                actor_id = actor.get("id", "?")
                for comp in actor.get("components", []):
                    type_id = comp.get("type_id")
                    if isinstance(type_id, int):
                        if not self._registry.has_component(type_id):
                            report.errors.append(
                                f"Actor '{actor_id}' in mode '{mode_id}' "
                                f"references unregistered component type_id {type_id}."
                            )

    # ── C6 — System component refs ────────────────────────────────────────────

    def _check_system_component_refs(
        self, cgs: dict[str, Any], report: ValidationReport
    ) -> None:
        def check(sys: dict, context: str) -> None:
            sid = sys.get("id", "?")
            for type_id in sys.get("reads", []) + sys.get("writes", []):
                if isinstance(type_id, int) and not self._registry.has_component(type_id):
                    report.errors.append(
                        f"System '{sid}' ({context}) reads/writes "
                        f"unregistered component type_id {type_id}."
                    )

        for sys in cgs.get("global_systems", []):
            check(sys, "global")
        for mode in cgs.get("modes", []):
            mode_id = mode.get("id", "?")
            for sys in mode.get("systems", []):
                check(sys, f"mode '{mode_id}'")

    # ── C8 / I12 — UNRESOLVED asset references ────────────────────────────────

    @staticmethod
    def _check_unresolved_asset_refs(
        cgs: dict[str, Any], report: ValidationReport
    ) -> None:
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
                            report.errors.append(
                                f"Actor '{actor_id}' in mode '{mode_id}', "
                                f"component {type_id}, field '{fname}' has "
                                f"an UNRESOLVED AssetReference. "
                                f"Resolve or replace before committing (I12)."
                            )

    # ── C9 / I14 — Mode schema versions ──────────────────────────────────────

    @staticmethod
    def _check_mode_schema_versions(
        cgs: dict[str, Any], report: ValidationReport
    ) -> None:
        for mode in cgs.get("modes", []):
            mode_id = mode.get("id", "?")
            if not mode.get("schema_version"):
                report.warnings.append(
                    f"Mode '{mode_id}' is missing 'schema_version'. "
                    f"Save files use this to identify schema compatibility (I14)."
                )

    # ── C12 — Global system override detection (warning) ─────────────────────

    @staticmethod
    def _check_global_system_overrides(
        cgs: dict[str, Any], report: ValidationReport
    ) -> None:
        global_ids = {
            s.get("id") for s in cgs.get("global_systems", []) if s.get("id")
        }
        for mode in cgs.get("modes", []):
            mode_id = mode.get("id", "?")
            for sys in mode.get("systems", []):
                sid = sys.get("id", "")
                if sid and sid in global_ids:
                    report.warnings.append(
                        f"Mode '{mode_id}' system '{sid}' overrides a "
                        f"global system. Mode definition takes precedence. "
                        f"Verify this override is intentional."
                    )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _collect_all_system_ids(cgs: dict[str, Any]) -> set[str]:
        ids: set[str] = set()
        for s in cgs.get("global_systems", []):
            if s.get("id"):
                ids.add(s["id"])
        for mode in cgs.get("modes", []):
            for s in mode.get("systems", []):
                if s.get("id"):
                    ids.add(s["id"])
        return ids