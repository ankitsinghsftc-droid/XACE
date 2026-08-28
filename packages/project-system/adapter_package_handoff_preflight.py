"""
adapter_package_handoff_preflight.py - X10-061 handoff gate.

This module composes the existing launch-readiness validators into the single
gate that must pass before Builder copies an adapter package into a handoff
directory. It is intentionally editor-free and artifact-driven: expensive SGC
and runtime work happen in their existing proof paths, while this gate verifies
the retained evidence is current for the CGS hash being handed off.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parents[1]
ASSET_REGISTRY_DIR = REPO_ROOT / "packages" / "asset-registry"
BUILDER_SERVER_DIR = REPO_ROOT / "packages" / "builder-workspace" / "server"
TOOLS_DIR = REPO_ROOT / "tools"

for _path in (str(ASSET_REGISTRY_DIR), str(BUILDER_SERVER_DIR), str(TOOLS_DIR), str(PACKAGE_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from asset_reference_preflight import validate_before_adapter_package_handoff  # noqa: E402
from cgs_schema_validate import ValidationResult, validate_cgs  # noqa: E402
from project_manifest import MANIFEST_FILENAME, ProjectManifestError, load_manifest  # noqa: E402
from semantic_binding_status import evaluate_semantic_binding_status  # noqa: E402
from sgc_plan_validator import (  # noqa: E402
    SgcExecutionPlanContractError,
    SgcPlanValidationError,
    validate_persisted_execution_plan_contract,
    validate_sgc_plan_for_runtime_load,
)


REPORT_SCHEMA = "xace.adapter_package_handoff_preflight_report.v1"
EXPECTED_ADAPTER_VERSION = "0.1.0"
EXPECTED_ADAPTER_PROTOCOL_VERSION = 1
SUPPORTED_TARGETS = ("godot", "unity", "unreal")
CHECK_ORDER = (
    "target_engine",
    "cgs",
    "sgc_plan",
    "runtime_compatibility",
    "adapter_version",
    "assets",
    "bindings",
    "secrets",
)

TARGET_REQUIRED_FILES: dict[str, tuple[str, ...]] = {
    "godot": (
        "xace_protocol.gd",
        "xace_transport.gd",
        "xace_delta_applicator.gd",
        "xace_input_collector.gd",
    ),
    "unity": (
        "XACE.Adapter.Unity.asmdef",
        "XaceTransport.cs",
        "XaceDeltaApplicator.cs",
        "XaceInputCollector.cs",
    ),
    "unreal": (
        "XaceTransport.h",
        "XaceTransport.cpp",
        "XaceDeltaApplicator.h",
        "XaceDeltaApplicator.cpp",
    ),
}

_QUOTE = chr(34)

ADAPTER_VERSION_MARKERS: dict[str, dict[str, tuple[str, ...]]] = {
    "godot": {
        "xace_protocol.gd": ("const PROTOCOL_VERSION := 1", "adapter_version: String = " + _QUOTE + "0.1.0" + _QUOTE),
        "xace_transport.gd": ("adapter_version := " + _QUOTE + "0.1.0" + _QUOTE,),
    },
    "unity": {
        "XaceTransport.cs": ("public const uint ProtocolVersion = 1;", "adapterVersion = " + _QUOTE + "0.1.0" + _QUOTE),
    },
    "unreal": {
        "XaceTransport.cpp": ("constexpr uint32 XaceProtocolVersion = 1;", "TEXT(" + _QUOTE + "0.1.0" + _QUOTE + ")"),
        "XaceTransport.h": ("AdapterVersion = TEXT(" + _QUOTE + "0.1.0" + _QUOTE + ")",),
    },
}

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("anthropic_api_key", re.compile(r"sk-ant-[A-Za-z0-9][A-Za-z0-9_\-]{8,}")),
    ("generic_api_key", re.compile(r"sk-[A-Za-z0-9][A-Za-z0-9_\-]{8,}")),
    ("google_api_key", re.compile(r"AIza[0-9A-Za-z_\-]{20,}")),
    ("bearer_token", re.compile(r"(?i)Bearer\s+[A-Za-z0-9._~+\-/=]{12,}")),
    ("api_key_header", re.compile(r"(?i)(?:x-api-key|api-key)\s*[:=]\s*[A-Za-z0-9._~+\-/=]{12,}")),
)

TEXT_SUFFIXES = {
    ".cfg",
    ".cmd",
    ".cpp",
    ".cs",
    ".gd",
    ".h",
    ".ini",
    ".json",
    ".jsonl",
    ".log",
    ".md",
    ".py",
    ".rs",
    ".toml",
    ".ts",
    ".txt",
    ".yaml",
    ".yml",
}

SKIP_DIRS = {".git", "node_modules", "target", "dist", "build", "__pycache__"}


@dataclass(frozen=True)
class HandoffPreflightIssue:
    category: str
    code: str
    message: str
    path: str = ""
    severity: str = "error"
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def blocks_handoff(self) -> bool:
        return self.severity == "error"

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "severity": self.severity,
            "blocks_handoff": self.blocks_handoff,
            "evidence": self.evidence,
        }


def validate_adapter_package_handoff(
    project_root: str | Path,
    target: str,
    *,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Run every required pre-handoff gate and return a deterministic report."""

    project_dir = Path(project_root).resolve()
    repo_dir = Path(repo_root).resolve() if repo_root is not None else REPO_ROOT
    selected_target = _normalize_target(target)

    manifest, manifest_path, manifest_error = _load_manifest(project_dir)
    cgs_path = _project_cgs_path(project_dir, manifest)
    asset_root = _project_asset_root(project_dir, manifest)

    cgs, cgs_hash, cgs_check = _check_cgs(project_dir, cgs_path, manifest_error)
    checks = [
        _check_target_engine(selected_target, repo_dir, manifest),
        cgs_check,
        _check_sgc_plan(project_dir, cgs, cgs_hash),
        _check_runtime_compatibility(project_dir, cgs_hash),
        _check_adapter_version(selected_target, repo_dir),
        _check_assets(cgs, project_dir, asset_root, selected_target),
        _check_bindings(cgs, project_dir, asset_root, selected_target),
        _check_secrets(project_dir, cgs_path, asset_root, _adapter_source_dir(repo_dir, selected_target)),
    ]
    checks.sort(key=lambda check: CHECK_ORDER.index(check["name"]) if check["name"] in CHECK_ORDER else 999)
    ok = all(bool(check.get("ok")) for check in checks)
    blocking_categories = [check["name"] for check in checks if not bool(check.get("ok"))]
    return {
        "schema": REPORT_SCHEMA,
        "ok": ok,
        "blocked": not ok,
        "target": selected_target,
        "requested_target": str(target),
        "project_root": str(project_dir),
        "repo_root": str(repo_dir),
        "manifest_path": str(manifest_path),
        "manifest_engine_type": str(getattr(manifest, "engine_type", "") or ""),
        "cgs_path": str(cgs_path),
        "cgs_hash": cgs_hash,
        "asset_root": str(asset_root),
        "generated_at_utc": _utc_now(),
        "required_categories": list(CHECK_ORDER),
        "blocking_categories": blocking_categories,
        "checks_passed": sum(1 for check in checks if bool(check.get("ok"))),
        "checks_total": len(checks),
        "checks": checks,
        "handoff_allowed": ok,
        "shipping_boundary": "engine_project_owns_shipping_package",
    }


def write_adapter_package_handoff_preflight_report(
    project_root: str | Path,
    target: str,
    report: Mapping[str, Any],
) -> Path:
    """Persist the latest preflight report under the project .xace folder."""

    project_dir = Path(project_root).resolve()
    cgs_hash = str(report.get("cgs_hash") or "no-cgs-hash")
    stem = cgs_hash if re.fullmatch(r"[0-9a-f]{64}", cgs_hash) else "no-cgs-hash"
    path = (
        project_dir
        / ".xace"
        / "adapter_package_handoff_preflight"
        / _safe_segment(target)
        / f"{stem}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(report), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _check_target_engine(target: str, repo_root: Path, manifest: Any) -> dict[str, Any]:
    issues: list[HandoffPreflightIssue] = []
    if target not in SUPPORTED_TARGETS:
        issues.append(_issue("target_engine", "TARGET_ENGINE_UNSUPPORTED", f"Unsupported adapter package target: {target!r}."))
        return _check("target_engine", issues, details={"supported_targets": list(SUPPORTED_TARGETS)})
    source_dir = _adapter_source_dir(repo_root, target)
    if not source_dir.exists() or not source_dir.is_dir():
        issues.append(_issue("target_engine", "ADAPTER_SOURCE_MISSING", f"Adapter source directory is missing: {source_dir}", str(source_dir)))
    missing = [name for name in TARGET_REQUIRED_FILES[target] if not (source_dir / name).is_file()]
    for name in missing:
        issues.append(_issue("target_engine", "ADAPTER_REQUIRED_FILE_MISSING", f"Required {target} adapter file is missing: {name}", str(source_dir / name)))
    details = {
        "source_dir": str(source_dir),
        "required_files": list(TARGET_REQUIRED_FILES[target]),
        "manifest_engine_type": str(getattr(manifest, "engine_type", "") or ""),
    }
    return _check("target_engine", issues, details=details)


def _check_cgs(project_root: Path, cgs_path: Path, manifest_error: str) -> tuple[dict[str, Any] | None, str, dict[str, Any]]:
    issues: list[HandoffPreflightIssue] = []
    if manifest_error:
        issues.append(_issue("cgs", "PROJECT_MANIFEST_INVALID", manifest_error, str(project_root / MANIFEST_FILENAME)))
    if not cgs_path.is_file():
        issues.append(_issue("cgs", "CGS_FILE_MISSING", f"CGS file is missing: {cgs_path}", str(cgs_path)))
        return None, "", _check("cgs", issues, details={"cgs_path": str(cgs_path)})
    try:
        cgs = json.loads(cgs_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        issues.append(_issue("cgs", "CGS_JSON_INVALID", f"CGS is invalid JSON: {exc}", str(cgs_path)))
        return None, "", _check("cgs", issues, details={"cgs_path": str(cgs_path)})
    except OSError as exc:
        issues.append(_issue("cgs", "CGS_READ_FAILED", f"CGS file cannot be read: {exc}", str(cgs_path)))
        return None, "", _check("cgs", issues, details={"cgs_path": str(cgs_path)})
    if not isinstance(cgs, dict):
        issues.append(_issue("cgs", "CGS_TOP_LEVEL_INVALID", "CGS top-level JSON value must be an object.", str(cgs_path)))
        return None, "", _check("cgs", issues, details={"cgs_path": str(cgs_path)})

    validation = ValidationResult()
    validate_cgs(cgs, validation, allow_legacy_hash=False, allow_draft_hash=False)
    for error in validation.errors:
        issues.append(_issue("cgs", "CGS_SCHEMA_INVALID", error, str(cgs_path)))
    details = {
        "cgs_path": str(cgs_path),
        "declared_hash": validation.declared_hash,
        "computed_hash": validation.computed_hash,
        "warnings": list(validation.warnings),
    }
    cgs_hash = str((cgs.get("metadata") or {}).get("cgs_hash") or "")
    return cgs, cgs_hash, _check("cgs", issues, details=details)


def _check_sgc_plan(project_root: Path, cgs: dict[str, Any] | None, cgs_hash: str) -> dict[str, Any]:
    issues: list[HandoffPreflightIssue] = []
    if cgs is None or not cgs_hash:
        issues.append(_issue("sgc_plan", "CGS_UNAVAILABLE", "Cannot validate SGC plan until CGS passes."))
        return _check("sgc_plan", issues)
    plan_path = project_root / ".xace" / "execution_plans" / f"{cgs_hash}.plan.json"
    if not plan_path.is_file():
        issues.append(_issue("sgc_plan", "SGC_PLAN_MISSING", f"Persisted SGC plan is missing for CGS hash {cgs_hash}.", str(plan_path)))
        return _check("sgc_plan", issues, details={"plan_path": str(plan_path)})
    try:
        plan_text = plan_path.read_text(encoding="utf-8")
    except OSError as exc:
        issues.append(_issue("sgc_plan", "SGC_PLAN_READ_FAILED", f"Persisted SGC plan cannot be read: {exc}", str(plan_path)))
        return _check("sgc_plan", issues, details={"plan_path": str(plan_path)})

    contract_report: dict[str, Any] = {}
    runtime_report: dict[str, Any] = {}
    try:
        contract_report = validate_persisted_execution_plan_contract(
            cgs_hash,
            plan_text,
            storage_path=plan_path,
            require_persistence_metadata=True,
        )
    except SgcExecutionPlanContractError as exc:
        contract_report = exc.report
        for item in exc.report.get("issues", []):
            issues.append(_issue("sgc_plan", "SGC_PLAN_CONTRACT_INVALID", str(item), str(plan_path)))
    try:
        runtime_report = validate_sgc_plan_for_runtime_load(cgs, plan_text)
    except SgcPlanValidationError as exc:
        runtime_report = exc.report
        for item in exc.report.get("issues", []):
            issues.append(_issue("sgc_plan", "SGC_PLAN_RUNTIME_LOAD_INVALID", str(item), str(plan_path)))
    return _check(
        "sgc_plan",
        issues,
        details={
            "plan_path": str(plan_path),
            "contract_report": _compact_report(contract_report),
            "runtime_load_report": _compact_report(runtime_report),
        },
    )


def _check_runtime_compatibility(project_root: Path, cgs_hash: str) -> dict[str, Any]:
    issues: list[HandoffPreflightIssue] = []
    if not cgs_hash:
        issues.append(_issue("runtime_compatibility", "CGS_HASH_MISSING", "Cannot validate runtime compatibility without a CGS hash."))
        return _check("runtime_compatibility", issues)
    proof_path = project_root / ".xace" / "proof" / "runtime-compatibility" / f"{cgs_hash}.json"
    if not proof_path.is_file():
        issues.append(_issue("runtime_compatibility", "RUNTIME_COMPATIBILITY_PROOF_MISSING", f"Runtime compatibility proof is missing for CGS hash {cgs_hash}.", str(proof_path)))
        return _check("runtime_compatibility", issues, details={"proof_path": str(proof_path)})
    try:
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        issues.append(_issue("runtime_compatibility", "RUNTIME_COMPATIBILITY_PROOF_INVALID_JSON", f"Runtime compatibility proof is invalid JSON: {exc}", str(proof_path)))
        return _check("runtime_compatibility", issues, details={"proof_path": str(proof_path)})
    if not isinstance(proof, dict):
        issues.append(_issue("runtime_compatibility", "RUNTIME_COMPATIBILITY_PROOF_INVALID", "Runtime compatibility proof must be a JSON object.", str(proof_path)))
        return _check("runtime_compatibility", issues, details={"proof_path": str(proof_path)})
    if proof.get("schema") != "xace.runtime.plan_compatibility.v1":
        issues.append(_issue("runtime_compatibility", "RUNTIME_COMPATIBILITY_SCHEMA_INVALID", "Runtime compatibility proof schema is invalid.", str(proof_path)))
    if str(proof.get("cgs_hash") or "") != cgs_hash:
        issues.append(_issue("runtime_compatibility", "RUNTIME_COMPATIBILITY_HASH_MISMATCH", "Runtime compatibility proof CGS hash does not match current CGS.", str(proof_path)))
    if proof.get("ok") is not True:
        issues.append(_issue("runtime_compatibility", "RUNTIME_COMPATIBILITY_FAILED", "Runtime compatibility proof is not ok.", str(proof_path)))
    if proof.get("default_system_injected") is not False:
        issues.append(_issue("runtime_compatibility", "RUNTIME_DEFAULT_SYSTEM_INJECTED", "Runtime compatibility proof must show no default-system injection.", str(proof_path)))
    if proof.get("unsupported_systems"):
        issues.append(_issue("runtime_compatibility", "RUNTIME_UNSUPPORTED_SYSTEMS", "Runtime compatibility proof records unsupported systems.", str(proof_path), evidence={"unsupported_systems": proof.get("unsupported_systems")}))
    if proof.get("legacy_dropped_system_ids"):
        issues.append(_issue("runtime_compatibility", "RUNTIME_LEGACY_SYSTEMS_DROPPED", "Runtime compatibility proof records dropped legacy systems.", str(proof_path), evidence={"legacy_dropped_system_ids": proof.get("legacy_dropped_system_ids")}))
    return _check(
        "runtime_compatibility",
        issues,
        details={
            "proof_path": str(proof_path),
            "declared_system_count": len(proof.get("declared_system_ids", [])) if isinstance(proof.get("declared_system_ids"), list) else 0,
            "scheduled_system_count": len(proof.get("scheduled_system_ids", [])) if isinstance(proof.get("scheduled_system_ids"), list) else 0,
        },
    )


def _check_adapter_version(target: str, repo_root: Path) -> dict[str, Any]:
    issues: list[HandoffPreflightIssue] = []
    if target not in SUPPORTED_TARGETS:
        issues.append(_issue("adapter_version", "TARGET_ENGINE_UNAVAILABLE", "Cannot validate adapter version for an unsupported target."))
        return _check("adapter_version", issues)
    source_dir = _adapter_source_dir(repo_root, target)
    for relative_path, markers in ADAPTER_VERSION_MARKERS[target].items():
        path = source_dir / relative_path
        if not path.is_file():
            issues.append(_issue("adapter_version", "ADAPTER_VERSION_FILE_MISSING", f"Adapter version source file is missing: {relative_path}", str(path)))
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for marker in markers:
            if marker not in text:
                issues.append(_issue("adapter_version", "ADAPTER_VERSION_MARKER_MISSING", f"Adapter source lacks expected marker {marker!r}.", str(path)))
    return _check(
        "adapter_version",
        issues,
        details={
            "expected_adapter_version": EXPECTED_ADAPTER_VERSION,
            "expected_protocol_version": EXPECTED_ADAPTER_PROTOCOL_VERSION,
            "source_dir": str(source_dir),
        },
    )


def _check_assets(cgs: dict[str, Any] | None, project_root: Path, asset_root: Path, target: str) -> dict[str, Any]:
    issues: list[HandoffPreflightIssue] = []
    if cgs is None:
        issues.append(_issue("assets", "CGS_UNAVAILABLE", "Cannot validate assets until CGS passes."))
        return _check("assets", issues)
    if target not in SUPPORTED_TARGETS:
        issues.append(_issue("assets", "TARGET_ENGINE_UNAVAILABLE", "Cannot validate target asset support for an unsupported target."))
        return _check("assets", issues)
    report = validate_before_adapter_package_handoff(cgs, project_root=project_root, asset_root=asset_root, engine=target)
    for item in report.to_dict().get("issues", []):
        if item.get("blocks_handoff"):
            issues.append(_issue("assets", str(item.get("code") or "ASSET_PREFLIGHT_FAILED"), str(item.get("message") or "Asset preflight failed."), str(item.get("path") or ""), evidence=item))
    return _check("assets", issues, details={"asset_report": _compact_report(report.to_dict())})


def _check_bindings(cgs: dict[str, Any] | None, project_root: Path, asset_root: Path, target: str) -> dict[str, Any]:
    issues: list[HandoffPreflightIssue] = []
    if cgs is None:
        issues.append(_issue("bindings", "CGS_UNAVAILABLE", "Cannot validate semantic bindings until CGS passes."))
        return _check("bindings", issues)
    if target not in SUPPORTED_TARGETS:
        issues.append(_issue("bindings", "TARGET_ENGINE_UNAVAILABLE", "Cannot validate target bindings for an unsupported target."))
        return _check("bindings", issues)
    report = evaluate_semantic_binding_status(cgs, project_root=project_root, engines=(target,), asset_root=asset_root)
    for record in report.to_dict().get("records", []):
        if record.get("blocks_handoff"):
            issue_codes = record.get("issue_codes") if isinstance(record.get("issue_codes"), list) else []
            code = str(issue_codes[0]) if issue_codes else "SEMANTIC_BINDING_BLOCKED"
            issues.append(_issue("bindings", code, str(record.get("reason") or "Semantic binding blocks handoff."), str(record.get("binding_id") or ""), evidence=record))
    return _check("bindings", issues, details={"binding_report": _compact_report(report.to_dict())})


def _check_secrets(project_root: Path, cgs_path: Path, asset_root: Path, adapter_source: Path) -> dict[str, Any]:
    findings = _scan_secret_paths([project_root / MANIFEST_FILENAME, cgs_path, asset_root, adapter_source], project_root)
    issues = [
        _issue(
            "secrets",
            "SECRET_PATTERN_FOUND",
            f"Credential-looking secret found: {finding['kind']} at {finding['path']}:{finding['line']}",
            finding["path"],
            evidence=finding,
        )
        for finding in findings
    ]
    return _check("secrets", issues, details={"finding_count": len(findings)})


def _load_manifest(project_root: Path) -> tuple[Any, Path, str]:
    manifest_path = project_root / MANIFEST_FILENAME
    try:
        return load_manifest(project_root), manifest_path, ""
    except ProjectManifestError as exc:
        return None, manifest_path, str(exc)


def _project_cgs_path(project_root: Path, manifest: Any) -> Path:
    raw = str(getattr(manifest, "cgs_path", "") or "game.cgs.json")
    path = Path(raw)
    return path.resolve() if path.is_absolute() else (project_root / path).resolve()


def _project_asset_root(project_root: Path, manifest: Any) -> Path:
    raw = str(getattr(manifest, "asset_root", "") or "assets")
    path = Path(raw)
    return path.resolve() if path.is_absolute() else (project_root / path).resolve()


def _adapter_source_dir(repo_root: Path, target: str) -> Path:
    return repo_root / "adapters" / _safe_segment(target)


def _check(name: str, issues: list[HandoffPreflightIssue], *, details: dict[str, Any] | None = None) -> dict[str, Any]:
    blocking = [issue for issue in issues if issue.blocks_handoff]
    return {
        "name": name,
        "ok": not blocking,
        "blocked": bool(blocking),
        "issue_count": len(issues),
        "blocking_issue_count": len(blocking),
        "summary": "passed" if not blocking else f"blocked by {len(blocking)} issue(s)",
        "issues": [issue.to_dict() for issue in issues],
        "details": details or {},
    }


def _issue(
    category: str,
    code: str,
    message: str,
    path: str = "",
    *,
    evidence: dict[str, Any] | None = None,
) -> HandoffPreflightIssue:
    return HandoffPreflightIssue(category=category, code=code, message=message, path=path, evidence=evidence or {})


def _compact_report(report: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "schema",
        "ok",
        "blocked",
        "load_ready",
        "runtime_load_status",
        "cgs_hash",
        "schema_version",
        "plan_version",
        "adapter_protocol_version",
        "migration_status",
        "plan_hash",
        "error_count",
        "warning_count",
        "record_count",
        "asset_refs_checked",
        "asset_files_checked",
        "asset_hashes_checked",
        "fallbacks_documented",
        "issues",
    )
    return {key: report[key] for key in keys if key in report}


def _scan_secret_paths(paths: Iterable[Path], project_root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for raw in paths:
        path = Path(raw).resolve()
        if path in seen or not path.exists():
            continue
        seen.add(path)
        files = _iter_text_files(path) if path.is_dir() else [path]
        for file_path in files:
            findings.extend(_scan_secret_file(file_path, project_root))
    return findings


def _iter_text_files(root: Path) -> Iterable[Path]:
    for file_path in sorted(root.rglob("*")):
        if not file_path.is_file() or not _looks_text(file_path):
            continue
        if any(part in SKIP_DIRS or part.startswith("target-") for part in file_path.relative_to(root).parts[:-1]):
            continue
        yield file_path


def _scan_secret_file(path: Path, project_root: Path) -> list[dict[str, Any]]:
    if not _looks_text(path):
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            return []
    except OSError:
        return []
    findings: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if "[REDACTED_SECRET]" in line:
            continue
        for kind, pattern in SECRET_PATTERNS:
            for match in pattern.finditer(line):
                findings.append({
                    "path": _display_path(path, project_root),
                    "line": line_number,
                    "column": match.start() + 1,
                    "kind": kind,
                    "preview": _redacted_preview(line, match.start(), match.end()),
                })
    return findings


def _looks_text(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES or path.name in {MANIFEST_FILENAME, "project.godot"}


def _display_path(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        try:
            return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
        except ValueError:
            return str(path)


def _redacted_preview(line: str, start: int, end: int) -> str:
    return (line[:start] + "[REDACTED_SECRET]" + line[end:]).strip()[:180]


def _normalize_target(target: str) -> str:
    return str(target).strip().lower().replace("-", "_")


def _safe_segment(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value).strip().lower())
    return cleaned.strip("._") or "unknown"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
