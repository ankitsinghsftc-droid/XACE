"""
asset_validator.py — Validates asset references before CGS commit (Audit 2, I12).

Global Invariant I12: UNRESOLVED asset references never enter committed CGS.

The AssetValidator is called by the Schema Factory and GDE before any
CGS mutation is committed. It scans all asset_id strings in the proposed
mutation, resolves each against the AssetManifest, and raises a
ValidationFailure if any are UNRESOLVED.

## What the Validator Checks
1. UNRESOLVED references — any asset_id in the CGS not present in the
   manifest is UNRESOLVED. This is always a blocker (I12).
2. Asset ID format — all asset_ids must match the canonical naming pattern
   from AssetNamingPolicy. Malformed IDs indicate a CGS corruption bug.
3. Type consistency — the AssetType in the manifest must match what the
   component field expects. Mismatches indicate a wrong ID was used.
4. Missing references — MISSING assets are reported as warnings, not errors.
   The CGS can be committed with MISSING refs, but the builder UI warns.

## Non-Blocking Warnings
PLACEHOLDER and MISSING assets do not block commit. They generate warnings
that are surfaced in the builder UI. The designer can ship a game that
still has PLACEHOLDER assets — the engine renders grey boxes, but the
game logic works.

## Integration Points
- Schema Factory calls validate_schema_package() before returning
- GDE calls validate_mutation() before applying a DSLTransaction
- Both receive a ValidationReport — they decide whether to block or warn
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from asset_manifest import AssetManifest
from asset_naming_policy import AssetNamingPolicy
from asset_reference import AssetReference
from asset_status_enum import AssetStatus
from asset_type_enum import AssetType


# ── Validation Issue ──────────────────────────────────────────────────────────

@dataclass
class AssetValidationIssue:
    """A single validation issue found during asset reference checking."""
    asset_id: str
    severity: str           # "error" | "warning" | "info"
    code: str               # machine-readable code, e.g. "UNRESOLVED_REF"
    message: str
    expected_type: Optional[AssetType] = None
    actual_type: Optional[AssetType] = None
    component_path: Optional[str] = None   # CGS path where the ref was found

    @property
    def is_error(self) -> bool:
        return self.severity == "error"

    @property
    def is_warning(self) -> bool:
        return self.severity == "warning"

    def to_dict(self) -> dict:
        return {
            "asset_id": self.asset_id,
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "expected_type": self.expected_type.value if self.expected_type else None,
            "actual_type": self.actual_type.value if self.actual_type else None,
            "component_path": self.component_path,
        }


# ── Validation Report ─────────────────────────────────────────────────────────

@dataclass
class AssetValidationReport:
    """
    Full result of one asset validation pass.
    Returned to the Schema Factory / GDE to decide whether to block commit.
    """
    issues: list[AssetValidationIssue] = field(default_factory=list)
    asset_ids_checked: int = 0

    @property
    def errors(self) -> list[AssetValidationIssue]:
        """All blocking errors (severity == 'error')."""
        return [i for i in self.issues if i.is_error]

    @property
    def warnings(self) -> list[AssetValidationIssue]:
        """All non-blocking warnings."""
        return [i for i in self.issues if i.is_warning]

    @property
    def blocks_commit(self) -> bool:
        """
        True if this report contains any errors that block CGS commit.
        Only UNRESOLVED references and malformed IDs block commit (I12).
        """
        return any(i.is_error for i in self.issues)

    @property
    def is_clean(self) -> bool:
        """True if there are no issues at all."""
        return not self.issues

    def add_issue(self, issue: AssetValidationIssue) -> None:
        self.issues.append(issue)

    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.is_error)

    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.is_warning)

    def summary(self) -> str:
        """One-line summary for logging."""
        if self.is_clean:
            return f"Asset validation passed ({self.asset_ids_checked} refs checked)"
        parts = []
        if self.error_count():
            parts.append(f"{self.error_count()} error(s)")
        if self.warning_count():
            parts.append(f"{self.warning_count()} warning(s)")
        return (
            f"Asset validation: {', '.join(parts)} "
            f"({self.asset_ids_checked} refs checked)"
        )

    def to_dict(self) -> dict:
        return {
            "blocks_commit": self.blocks_commit,
            "asset_ids_checked": self.asset_ids_checked,
            "error_count": self.error_count(),
            "warning_count": self.warning_count(),
            "issues": [i.to_dict() for i in self.issues],
        }


# ── Asset Validator ───────────────────────────────────────────────────────────

class AssetValidator:
    """
    Validates asset_id references in CGS mutations before commit.

    Enforces Global Invariant I12:
    UNRESOLVED asset references never enter committed CGS.
    """

    def __init__(self, manifest: AssetManifest) -> None:
        self._manifest = manifest

    # ── Primary API ───────────────────────────────────────────────────────

    def validate_asset_id(
        self,
        asset_id: str,
        expected_type: Optional[AssetType] = None,
        component_path: Optional[str] = None,
    ) -> AssetValidationReport:
        """
        Validates a single asset_id string.

        Checks:
        1. Canonical format (AssetNamingPolicy.is_valid)
        2. Presence in the manifest (not UNRESOLVED)
        3. Status (PLACEHOLDER/LINKED/MISSING → warning vs error)
        4. Type consistency (if expected_type provided)
        """
        report = AssetValidationReport(asset_ids_checked=1)

        # ── Check 1: Format ────────────────────────────────────────────────
        if not AssetNamingPolicy.is_valid(asset_id):
            report.add_issue(AssetValidationIssue(
                asset_id=asset_id,
                severity="error",
                code="MALFORMED_ASSET_ID",
                message=(
                    f"Asset ID '{asset_id}' does not match the canonical XACE "
                    "naming pattern. Expected format: "
                    "[entity_type]_[entity_name]_[suffix]_v[N] "
                    "(e.g. character_knight_mesh_v1)"
                ),
                component_path=component_path,
            ))
            return report  # cannot check further without a valid ID

        # ── Check 2: Presence in manifest ─────────────────────────────────
        ref = self._manifest.get(asset_id)
        if ref is None:
            report.add_issue(AssetValidationIssue(
                asset_id=asset_id,
                severity="error",
                code="UNRESOLVED_REF",
                message=(
                    f"Asset '{asset_id}' is not registered in the Asset Registry "
                    "(UNRESOLVED). This reference cannot be committed to the CGS (I12). "
                    "The asset must be registered before the CGS mutation is applied."
                ),
                expected_type=expected_type,
                component_path=component_path,
            ))
            return report

        # ── Check 3: Status ────────────────────────────────────────────────
        if ref.status == AssetStatus.UNRESOLVED:
            # Should not happen if manifest is consistent, but guard anyway
            report.add_issue(AssetValidationIssue(
                asset_id=asset_id,
                severity="error",
                code="UNRESOLVED_REF",
                message=(
                    f"Asset '{asset_id}' has status UNRESOLVED in the manifest. "
                    "This is a registration bug. Fix the auto-registration flow."
                ),
                component_path=component_path,
            ))
        elif ref.status == AssetStatus.MISSING:
            report.add_issue(AssetValidationIssue(
                asset_id=asset_id,
                severity="warning",
                code="MISSING_ASSET",
                message=(
                    f"Asset '{asset_id}' is MISSING — the file was previously linked "
                    "but can no longer be found. The engine will render a placeholder. "
                    "Re-link the asset when possible."
                ),
                component_path=component_path,
            ))
        elif ref.status == AssetStatus.PLACEHOLDER:
            report.add_issue(AssetValidationIssue(
                asset_id=asset_id,
                severity="warning",
                code="PLACEHOLDER_ASSET",
                message=(
                    f"Asset '{asset_id}' is still a PLACEHOLDER. "
                    "Game logic works but the engine will render a grey box / play silence. "
                    "Link a real asset when ready."
                ),
                component_path=component_path,
            ))

        # ── Check 4: Type consistency ──────────────────────────────────────
        if expected_type is not None and ref.asset_type != expected_type:
            report.add_issue(AssetValidationIssue(
                asset_id=asset_id,
                severity="error",
                code="ASSET_TYPE_MISMATCH",
                message=(
                    f"Asset '{asset_id}' has type {ref.asset_type.value} "
                    f"but the component field expects {expected_type.value}. "
                    "A wrong asset ID was used."
                ),
                expected_type=expected_type,
                actual_type=ref.asset_type,
                component_path=component_path,
            ))

        return report

    def validate_asset_id_list(
        self,
        asset_ids: list[str],
        expected_type: Optional[AssetType] = None,
        component_path: Optional[str] = None,
    ) -> AssetValidationReport:
        """
        Validates a list of asset_ids and merges all issues into one report.
        Used when a component field holds multiple asset references.
        """
        combined = AssetValidationReport()
        for asset_id in sorted(asset_ids):  # sorted for determinism (D11)
            single = self.validate_asset_id(asset_id, expected_type, component_path)
            combined.issues.extend(single.issues)
            combined.asset_ids_checked += 1
        return combined

    def validate_manifest(self) -> AssetValidationReport:
        """
        Validates the entire manifest.

        Returns a report covering every registered reference.
        Used at session load to detect any stale UNRESOLVED entries.
        """
        report = AssetValidationReport()
        for ref in self._manifest.all_refs():
            single = self.validate_asset_id(ref.asset_id, ref.asset_type)
            report.issues.extend(single.issues)
            report.asset_ids_checked += 1
        return report

    def validate_no_unresolved(self) -> AssetValidationReport:
        """
        Fast path — only checks for UNRESOLVED references.
        Called by the GDE immediately before committing a transaction (I12).
        """
        report = AssetValidationReport()
        unresolved = self._manifest.get_all_unresolved()
        for ref in unresolved:
            report.add_issue(AssetValidationIssue(
                asset_id=ref.asset_id,
                severity="error",
                code="UNRESOLVED_REF",
                message=(
                    f"Asset '{ref.asset_id}' is UNRESOLVED. "
                    "CGS commit blocked (I12)."
                ),
            ))
            report.asset_ids_checked += 1
        return report

    def validate_reference(
        self,
        ref: AssetReference,
        expected_type: Optional[AssetType] = None,
        component_path: Optional[str] = None,
    ) -> AssetValidationReport:
        """
        Validates an AssetReference object directly (bypasses manifest lookup).
        Used when the reference is already in hand, e.g. during migration.
        """
        report = AssetValidationReport(asset_ids_checked=1)

        if ref.status == AssetStatus.UNRESOLVED:
            report.add_issue(AssetValidationIssue(
                asset_id=ref.asset_id,
                severity="error",
                code="UNRESOLVED_REF",
                message=f"AssetReference '{ref.asset_id}' has status UNRESOLVED.",
                component_path=component_path,
            ))
        elif ref.status == AssetStatus.MISSING:
            report.add_issue(AssetValidationIssue(
                asset_id=ref.asset_id,
                severity="warning",
                code="MISSING_ASSET",
                message=f"Asset '{ref.asset_id}' is MISSING — re-link when possible.",
                component_path=component_path,
            ))

        if expected_type and ref.asset_type != expected_type:
            report.add_issue(AssetValidationIssue(
                asset_id=ref.asset_id,
                severity="error",
                code="ASSET_TYPE_MISMATCH",
                message=(
                    f"Type mismatch: asset is {ref.asset_type.value}, "
                    f"field expects {expected_type.value}."
                ),
                expected_type=expected_type,
                actual_type=ref.asset_type,
                component_path=component_path,
            ))

        return report