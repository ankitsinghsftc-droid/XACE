#!/usr/bin/env python3
"""Export and validate a self-contained XACE debug report.

The debug report is intentionally local-only and self-contained. It captures the
debugger evidence needed to reproduce a runtime/debugger question without
requiring the original working project: debugger state, replay inputs, hash logs,
the SGC plan, mutation log, and adapter feedback.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = REPO_ROOT / "packages" / "builder-workspace" / "server"
PROJECT_SYSTEM_DIR = REPO_ROOT / "packages" / "project-system"

for import_path in (SERVER_DIR, PROJECT_SYSTEM_DIR, REPO_ROOT / "tools"):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

try:  # pragma: no cover - exercised through the CLI proof.
    from project_manifest import MANIFEST_FILENAME, load_manifest  # type: ignore
except Exception:  # pragma: no cover - fallback keeps validation usable in thin checkouts.
    MANIFEST_FILENAME = "xace.project.json"
    load_manifest = None  # type: ignore[assignment]

from secret_redaction import REDACTED_SECRET, redact_text, redact_value  # noqa: E402
from security_secret_scan import scan_paths  # noqa: E402


SCHEMA = "xace.exportable_debug_report.v1"
VALIDATION_SCHEMA = "xace.exportable_debug_report.validation.v1"
ARTIFACT_MANIFEST_SCHEMA = "xace.exportable_debug_report.artifact_manifest.v1"
REQUIRED_SECTIONS = (
    "debugger_state",
    "replay_inputs",
    "hash_logs",
    "sgc_plan",
    "mutation_log",
    "adapter_feedback",
)
SECTION_FILENAMES = {
    "debugger_state": "debugger_state.json",
    "replay_inputs": "replay_inputs.json",
    "hash_logs": "hash_logs.json",
    "sgc_plan": "sgc_plan.json",
    "mutation_log": "mutation_log.json",
    "adapter_feedback": "adapter_feedback.json",
}
SECTION_SCHEMAS = {
    "debugger_state": "xace.debug_report.debugger_state.v1",
    "replay_inputs": "xace.debug_report.replay_inputs.v1",
    "hash_logs": "xace.debug_report.hash_logs.v1",
    "mutation_log": "xace.debug_report.mutation_log.v1",
    "adapter_feedback": "xace.debug_report.adapter_feedback.v1",
}
JSONL_SECTIONS = {"mutation_log", "adapter_feedback"}
MAX_JSONL_RECORDS = 8192
HASH_HEX_LENGTH = 64


class DebugReportError(RuntimeError):
    """Raised when a debug report cannot be exported or loaded."""


def create_debug_report(
    *,
    project: Path | None,
    output: Path,
    artifact_dir: Path | None,
    report_id: str,
    debugger_state: Path | None = None,
    replay_inputs: Path | None = None,
    hash_log: Path | None = None,
    sgc_plan: Path | None = None,
    mutation_log: Path | None = None,
    adapter_feedback: Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Create a redacted, self-contained debug report JSON file."""

    output = output.resolve()
    if output.exists() and not overwrite:
        raise DebugReportError(f"Debug report already exists: {output}. Pass --overwrite to replace it.")
    output.parent.mkdir(parents=True, exist_ok=True)

    artifact_root = artifact_dir.resolve() if artifact_dir else None
    if artifact_root:
        artifact_root.mkdir(parents=True, exist_ok=True)

    project_context = _project_context(project)
    explicit_paths = {
        "debugger_state": debugger_state,
        "replay_inputs": replay_inputs,
        "hash_logs": hash_log,
        "sgc_plan": sgc_plan,
        "mutation_log": mutation_log,
        "adapter_feedback": adapter_feedback,
    }
    resolved_sources = _resolve_sources(project_context, explicit_paths)

    sections: dict[str, Any] = {}
    source_manifest: list[dict[str, Any]] = []
    for section in REQUIRED_SECTIONS:
        source_path = resolved_sources.get(section)
        if source_path is None:
            raise DebugReportError(f"Missing required debug report section: {section}")
        raw_payload = _load_section(section, source_path)
        normalized = _normalize_section(section, raw_payload)
        sections[section] = redact_value(normalized)
        source_manifest.append(_source_entry(section, source_path, project_context))

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "ok": False,
        "debug_report_id": report_id,
        "created_at_utc": _now_utc(),
        "privacy": {
            "local_only": True,
            "uploaded": False,
            "redacted": True,
            "redaction_marker": REDACTED_SECRET,
        },
        "environment": _environment(),
        "project": project_context["summary"],
        "source_manifest": source_manifest,
        "sections": sections,
        "section_digests": _section_digests(sections),
        "fresh_checkout_contract": {
            "load_contract": "self_contained_json_no_original_project_required",
            "required_sections": list(REQUIRED_SECTIONS),
            "validator_command": "python tools/export_debug_report.py --validate --input <debug_report.json> --fresh-checkout <empty-checkout> --json",
        },
        "reproduction_commands": _reproduction_commands(project_context, output, artifact_root),
        "artifact_manifest": {},
        "redaction": {"ok": False, "pending": True},
    }
    validation = validate_debug_report_payload(payload)
    payload["validation"] = validation
    payload["ok"] = bool(validation.get("ok"))

    artifact_manifest = _write_artifacts(payload, artifact_root) if artifact_root else {}
    payload["artifact_manifest"] = artifact_manifest
    _write_json(output, payload)
    payload["redaction"] = _redaction_report([output, artifact_root] if artifact_root else [output])
    payload["ok"] = bool(payload["ok"] and payload["redaction"].get("ok"))
    _write_json(output, payload)

    if artifact_root:
        payload["artifact_manifest"] = _write_artifacts(payload, artifact_root)
        _write_json(output, payload)
        payload["redaction"] = _redaction_report([output, artifact_root])
        payload["ok"] = bool(validation.get("ok") and payload["redaction"].get("ok"))
        _write_json(output, payload)

    return payload


def load_debug_report(path: Path) -> dict[str, Any]:
    """Load a debug report JSON document from disk."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DebugReportError(f"Debug report does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise DebugReportError(f"Debug report is not valid JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise DebugReportError("Debug report root must be an object.")
    return payload


def validate_debug_report_payload(payload: dict[str, Any], fresh_checkout: Path | None = None) -> dict[str, Any]:
    """Validate that a report can be loaded without the original project."""

    issues: list[str] = []
    section_results: dict[str, dict[str, Any]] = {}

    if payload.get("schema") != SCHEMA:
        issues.append(f"schema must be {SCHEMA}")

    sections = payload.get("sections")
    if not isinstance(sections, dict):
        issues.append("sections must be an object")
        sections = {}

    for section in REQUIRED_SECTIONS:
        section_payload = sections.get(section) if isinstance(sections, dict) else None
        result = _validate_section(section, section_payload)
        section_results[section] = result
        if not result["ok"]:
            issues.extend(f"{section}: {issue}" for issue in result["issues"])

    source_manifest = payload.get("source_manifest")
    if not isinstance(source_manifest, list):
        issues.append("source_manifest must be a list")
        source_sections: set[str] = set()
    else:
        source_sections = {
            str(item.get("section") or "")
            for item in source_manifest
            if isinstance(item, dict) and item.get("section")
        }
    for section in REQUIRED_SECTIONS:
        if section not in source_sections:
            issues.append(f"source_manifest missing section {section}")

    section_digests = payload.get("section_digests")
    if not isinstance(section_digests, dict):
        issues.append("section_digests must be an object")
    else:
        expected = _section_digests(sections if isinstance(sections, dict) else {})
        for section in REQUIRED_SECTIONS:
            digest = section_digests.get(section)
            if not _is_sha256(str(digest or "")):
                issues.append(f"section_digests.{section} is not a SHA-256 digest")
            elif expected.get(section) and digest != expected[section]:
                issues.append(f"section_digests.{section} does not match embedded section payload")

    reproduction = payload.get("reproduction_commands")
    command_ids = _command_ids(reproduction)
    required_command_ids = {"export_debug_report", "validate_fresh_checkout_debug_report"}
    if not required_command_ids.issubset(command_ids):
        issues.append("reproduction_commands missing export or fresh-checkout validation command")

    fresh_checkout_summary: dict[str, Any] = {
        "enabled": fresh_checkout is not None,
        "path": str(fresh_checkout.resolve()) if fresh_checkout else "",
        "loaded_without_original_project": fresh_checkout is not None,
    }
    if fresh_checkout is not None:
        fresh_checkout.mkdir(parents=True, exist_ok=True)
        summary = {
            "schema": "xace.exportable_debug_report.fresh_checkout_load.v1",
            "loaded_at_utc": _now_utc(),
            "debug_report_id": str(payload.get("debug_report_id") or ""),
            "report_schema": payload.get("schema"),
            "required_sections_loaded": {
                section: bool(section_results.get(section, {}).get("ok"))
                for section in REQUIRED_SECTIONS
            },
            "section_digests": {
                section: _section_digests(sections).get(section)
                for section in REQUIRED_SECTIONS
                if isinstance(sections, dict)
            },
            "source_project_available": False,
            "load_contract": "report_json_only",
        }
        summary_path = fresh_checkout / "loaded_debug_report_summary.json"
        _write_json(summary_path, summary)
        fresh_checkout_summary.update(
            {
                "summary_path": str(summary_path),
                "summary_sha256": _file_sha256(summary_path),
            }
        )

    ok = not issues
    return {
        "schema": VALIDATION_SCHEMA,
        "ok": ok,
        "required_sections": list(REQUIRED_SECTIONS),
        "section_results": section_results,
        "fresh_checkout": fresh_checkout_summary,
        "issues": issues,
    }


def _project_context(project: Path | None) -> dict[str, Any]:
    if project is None:
        return {
            "project_dir": None,
            "manifest_path": None,
            "manifest": None,
            "cgs_path": None,
            "cgs_hash": "",
            "summary": {
                "available": False,
                "reason": "No --project path supplied; all section paths must be explicit.",
            },
        }

    project_dir = project.resolve()
    manifest_path = project_dir / MANIFEST_FILENAME
    manifest_payload: dict[str, Any] | None = None
    cgs_path: Path | None = None
    errors: list[str] = []

    if load_manifest is not None:
        try:
            manifest = load_manifest(project_dir)
            manifest_payload = manifest.to_dict()
            cgs_path = (project_dir / manifest.cgs_path).resolve()
        except Exception as exc:
            errors.append(redact_text(exc))

    if manifest_payload is None and manifest_path.exists():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                manifest_payload = loaded
                cgs_path = (project_dir / str(loaded.get("cgs_path") or "game.cgs.json")).resolve()
        except Exception as exc:
            errors.append(redact_text(exc))

    if cgs_path is None:
        cgs_path = (project_dir / "game.cgs.json").resolve()

    cgs_hash = _file_sha256(cgs_path) if cgs_path.exists() else ""
    return {
        "project_dir": project_dir,
        "manifest_path": manifest_path if manifest_path.exists() else None,
        "manifest": manifest_payload,
        "cgs_path": cgs_path if cgs_path.exists() else None,
        "cgs_hash": cgs_hash,
        "summary": {
            "available": project_dir.exists(),
            "project_dir": str(project_dir),
            "manifest_available": manifest_path.exists(),
            "engine_type": str((manifest_payload or {}).get("engine_type") or ""),
            "project_id": str((manifest_payload or {}).get("project_id") or ""),
            "cgs_path": str(cgs_path),
            "cgs_sha256": cgs_hash,
            "errors": errors,
        },
    }


def _resolve_sources(project_context: dict[str, Any], explicit_paths: dict[str, Path | None]) -> dict[str, Path | None]:
    project_dir = project_context.get("project_dir")
    project_path = project_dir if isinstance(project_dir, Path) else None
    cgs_hash = str(project_context.get("cgs_hash") or "")
    defaults: dict[str, list[Path]] = {}
    if project_path:
        defaults = {
            "debugger_state": [
                project_path / ".xace" / "debugger" / "debugger_state.json",
                project_path / ".xace" / "debugger" / "state.json",
            ],
            "replay_inputs": [
                project_path / ".xace" / "replay" / "replay_inputs.json",
                project_path / ".xace" / "inputs" / "replay_inputs.json",
                project_path / ".xace" / "proof" / "replay" / "input_log.json",
            ],
            "hash_logs": [
                project_path / ".xace" / "runtime" / "hash_log.json",
                project_path / ".xace" / "proof" / "runtime" / "hash_log.json",
                project_path / ".xace" / "logs" / "hash_log.json",
            ],
            "sgc_plan": [
                project_path / ".xace" / "execution_plans" / f"{cgs_hash}.plan.json",
            ],
            "mutation_log": [
                project_path / ".xace" / "audit" / "mutations.jsonl",
                project_path / ".xace" / "audit" / "prompt_history_events.jsonl",
            ],
            "adapter_feedback": [
                project_path / ".xace" / "adapter_feedback.jsonl",
                project_path / ".xace" / "logs" / "adapter_feedback.jsonl",
                project_path / ".xace" / "audit" / "adapter_feedback.jsonl",
            ],
        }
        plan_dir = project_path / ".xace" / "execution_plans"
        if plan_dir.exists():
            defaults.setdefault("sgc_plan", []).extend(sorted(plan_dir.glob("*.plan.json")))

    resolved: dict[str, Path | None] = {}
    for section in REQUIRED_SECTIONS:
        explicit = explicit_paths.get(section)
        if explicit:
            resolved[section] = explicit.resolve()
            continue
        resolved[section] = next((path.resolve() for path in defaults.get(section, []) if path.exists()), None)
    return resolved


def _load_section(section: str, source_path: Path) -> Any:
    if section in JSONL_SECTIONS or source_path.suffix.lower() == ".jsonl":
        records: list[Any] = []
        for line_no, line in enumerate(source_path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            if len(records) >= MAX_JSONL_RECORDS:
                records.append(
                    {
                        "schema": "xace.debug_report.truncation_notice.v1",
                        "line": line_no,
                        "reason": f"JSONL record cap {MAX_JSONL_RECORDS} reached.",
                    }
                )
                break
            try:
                records.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                records.append(
                    {
                        "schema": "xace.debug_report.jsonl_parse_error.v1",
                        "line": line_no,
                        "error": redact_text(exc),
                        "raw": stripped[:512],
                    }
                )
        return {"records": records}
    try:
        return json.loads(source_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DebugReportError(f"{section} is not valid JSON: {source_path}: {exc}") from exc


def _normalize_section(section: str, payload: Any) -> dict[str, Any]:
    if section == "debugger_state":
        if not isinstance(payload, dict):
            raise DebugReportError("debugger_state must be a JSON object")
        normalized = dict(payload)
        normalized.setdefault("schema", SECTION_SCHEMAS[section])
        return normalized

    if section == "replay_inputs":
        if isinstance(payload, list):
            return {"schema": SECTION_SCHEMAS[section], "records": payload}
        if isinstance(payload, dict):
            normalized = dict(payload)
            normalized.setdefault("schema", SECTION_SCHEMAS[section])
            return normalized
        raise DebugReportError("replay_inputs must be a JSON object or array")

    if section == "hash_logs":
        if isinstance(payload, list):
            return {"schema": SECTION_SCHEMAS[section], "records": payload}
        if isinstance(payload, dict):
            normalized = dict(payload)
            normalized.setdefault("schema", SECTION_SCHEMAS[section])
            if "records" not in normalized and isinstance(normalized.get("hash_log"), list):
                normalized["records"] = normalized["hash_log"]
            return normalized
        raise DebugReportError("hash_logs must be a JSON object or array")

    if section == "sgc_plan":
        if not isinstance(payload, dict):
            raise DebugReportError("sgc_plan must be a JSON object")
        return dict(payload)

    if section in {"mutation_log", "adapter_feedback"}:
        if isinstance(payload, list):
            return {"schema": SECTION_SCHEMAS[section], "records": payload}
        if isinstance(payload, dict):
            normalized = dict(payload)
            normalized.setdefault("schema", SECTION_SCHEMAS[section])
            if "records" not in normalized:
                normalized["records"] = []
            return normalized
    raise DebugReportError(f"unsupported debug report section: {section}")


def _validate_section(section: str, payload: Any) -> dict[str, Any]:
    issues: list[str] = []
    if not isinstance(payload, dict):
        return {"ok": False, "issues": ["section payload must be an object"], "record_count": 0}

    record_count = 0
    if section == "debugger_state":
        tick_fields = ("selected_tick", "current_tick", "tick")
        if not any(isinstance(payload.get(field), int) for field in tick_fields):
            issues.append("missing integer selected/current tick")
        if not any(payload.get(field) for field in ("selected_world_hash", "world_hash", "selected_snapshot_key", "timeline_cursor")):
            issues.append("missing selected hash, snapshot key, or timeline cursor")
        record_count = len(payload.get("hash_timeline") or []) if isinstance(payload.get("hash_timeline"), list) else 1

    elif section == "replay_inputs":
        records = _records_from(payload, "records", "inputs", "packets", "input_log")
        record_count = len(records)
        if not records:
            issues.append("missing replay input records")
        elif not all(isinstance(record, dict) for record in records):
            issues.append("replay input records must be objects")

    elif section == "hash_logs":
        records = _records_from(payload, "records", "hash_log", "hashes")
        record_count = len(records)
        if not records:
            issues.append("missing hash log records")
        elif not any(
            isinstance(record, dict)
            and isinstance(record.get("tick"), int)
            and isinstance(record.get("world_hash") or record.get("hash"), str)
            for record in records
        ):
            issues.append("hash log records must include integer tick and hash/world_hash")

    elif section == "sgc_plan":
        if not any(payload.get(field) for field in ("plan_hash", "compiled_from_cgs_hash", "cgs_hash", "proof_bundle")):
            issues.append("SGC plan missing plan_hash, compiled_from_cgs_hash, cgs_hash, or proof_bundle")
        if payload.get("plan_hash") and not _is_sha256(str(payload.get("plan_hash"))):
            issues.append("SGC plan_hash is not a SHA-256 digest")
        record_count = len(payload.get("phases") or []) if isinstance(payload.get("phases"), list) else 1

    elif section in {"mutation_log", "adapter_feedback"}:
        records = _records_from(payload, "records", "events", "feedback")
        record_count = len(records)
        if not records:
            issues.append(f"missing {section} records")
        elif not all(isinstance(record, dict) for record in records):
            issues.append(f"{section} records must be objects")

    return {"ok": not issues, "issues": issues, "record_count": record_count}


def _records_from(payload: dict[str, Any], *keys: str) -> list[Any]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _source_entry(section: str, source_path: Path, project_context: dict[str, Any]) -> dict[str, Any]:
    return {
        "section": section,
        "source_path": _display_path(source_path, project_context),
        "sha256": _file_sha256(source_path),
        "bytes": source_path.stat().st_size,
        "loader": "jsonl" if section in JSONL_SECTIONS or source_path.suffix.lower() == ".jsonl" else "json",
        "embedded": True,
    }


def _write_artifacts(payload: dict[str, Any], artifact_root: Path | None) -> dict[str, Any]:
    if artifact_root is None:
        return {}
    files: list[dict[str, Any]] = []
    sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
    section_root = artifact_root / "sections"
    section_root.mkdir(parents=True, exist_ok=True)
    for section in REQUIRED_SECTIONS:
        path = section_root / SECTION_FILENAMES[section]
        _write_json(path, sections.get(section, {}))
        files.append(
            {
                "role": section,
                "path": str(path),
                "sha256": _file_sha256(path),
                "bytes": path.stat().st_size,
            }
        )
    manifest_path = artifact_root / "debug_report_artifact_manifest.json"
    manifest = {
        "schema": ARTIFACT_MANIFEST_SCHEMA,
        "debug_report_id": str(payload.get("debug_report_id") or ""),
        "report_schema": payload.get("schema"),
        "required_sections": list(REQUIRED_SECTIONS),
        "files": files,
    }
    _write_json(manifest_path, manifest)
    return {
        "schema": ARTIFACT_MANIFEST_SCHEMA,
        "path": str(manifest_path),
        "sha256": _file_sha256(manifest_path),
        "files": files,
    }


def _reproduction_commands(project_context: dict[str, Any], output: Path, artifact_root: Path | None) -> dict[str, Any]:
    project_dir = project_context.get("project_dir")
    export_command = ["python", "tools/export_debug_report.py"]
    if isinstance(project_dir, Path):
        export_command.extend(["--project", str(project_dir)])
    export_command.extend(["--output", str(output)])
    if artifact_root:
        export_command.extend(["--artifact-dir", str(artifact_root)])
    export_command.extend(["--overwrite", "--json"])
    return {
        "schema": "xace.exportable_debug_report.reproduction_commands.v1",
        "commands": [
            {
                "id": "export_debug_report",
                "description": "Recreate this local-only redacted debug report from the project evidence files.",
                "command": export_command,
            },
            {
                "id": "validate_fresh_checkout_debug_report",
                "description": "Load the exported report without the original project and write a fresh-checkout summary.",
                "command": [
                    "python",
                    "tools/export_debug_report.py",
                    "--validate",
                    "--input",
                    str(output),
                    "--fresh-checkout",
                    "<fresh-empty-checkout>",
                    "--json",
                ],
            },
        ],
    }


def _environment() -> dict[str, Any]:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "cwd": str(Path.cwd()),
        "repo_root": str(REPO_ROOT),
    }


def _section_digests(sections: dict[str, Any]) -> dict[str, str]:
    return {
        section: _sha256_json(sections[section])
        for section in REQUIRED_SECTIONS
        if section in sections
    }


def _command_ids(reproduction: Any) -> set[str]:
    if not isinstance(reproduction, dict):
        return set()
    commands = reproduction.get("commands")
    if not isinstance(commands, list):
        return set()
    return {
        str(item.get("id") or "")
        for item in commands
        if isinstance(item, dict) and item.get("id")
    }


def _redaction_report(paths: Iterable[Path | None]) -> dict[str, Any]:
    existing = [path for path in paths if isinstance(path, Path) and path.exists()]
    findings = scan_paths(existing, repo_root=REPO_ROOT) if existing else []
    return {
        "ok": not findings,
        "scanner": "tools/security_secret_scan.py",
        "finding_count": len(findings),
        "findings": [
            {
                "path": finding.path,
                "line": finding.line,
                "column": finding.column,
                "kind": finding.kind,
                "preview": finding.preview,
            }
            for finding in findings[:20]
        ],
    }


def _display_path(path: Path, project_context: dict[str, Any]) -> str:
    roots = [REPO_ROOT]
    project_dir = project_context.get("project_dir")
    if isinstance(project_dir, Path):
        roots.insert(0, project_dir)
    for root in roots:
        try:
            return str(path.resolve().relative_to(root.resolve())).replace(os.sep, "/")
        except ValueError:
            continue
    return str(path)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(payload: Any) -> str:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == HASH_HEX_LENGTH and all(char in "0123456789abcdefABCDEF" for char in value)


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export or validate a self-contained XACE debug report.")
    parser.add_argument("--project", default="", help="XACE project directory containing .xace debug evidence.")
    parser.add_argument("--output", default="target-codex-debug-report/debug_report.json", help="Output debug report JSON path.")
    parser.add_argument("--artifact-dir", default="", help="Optional directory for per-section exported artifacts.")
    parser.add_argument("--report-id", default="xace-debug-report", help="Stable report identifier.")
    parser.add_argument("--debugger-state", default="", help="Explicit debugger state JSON path.")
    parser.add_argument("--replay-inputs", default="", help="Explicit replay input JSON path.")
    parser.add_argument("--hash-log", default="", help="Explicit runtime hash log JSON path.")
    parser.add_argument("--sgc-plan", default="", help="Explicit SGC plan JSON path.")
    parser.add_argument("--mutation-log", default="", help="Explicit mutation log JSON/JSONL path.")
    parser.add_argument("--adapter-feedback", default="", help="Explicit adapter feedback JSON/JSONL path.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite the report file if it exists.")
    parser.add_argument("--validate", action="store_true", help="Validate an existing exported debug report.")
    parser.add_argument("--input", default="", help="Debug report JSON to validate.")
    parser.add_argument("--fresh-checkout", default="", help="Directory used to prove report-only loading.")
    parser.add_argument("--json", action="store_true", help="Emit JSON to stdout.")
    args = parser.parse_args(argv)

    try:
        if args.validate:
            input_path = Path(args.input or args.output).resolve()
            payload = load_debug_report(input_path)
            fresh_checkout = Path(args.fresh_checkout).resolve() if args.fresh_checkout else None
            validation = validate_debug_report_payload(payload, fresh_checkout=fresh_checkout)
            if args.json:
                print(json.dumps(validation, indent=2, sort_keys=True))
            else:
                status = "PASS" if validation["ok"] else "FAIL"
                print(f"{status}: validated {input_path}")
            return 0 if validation["ok"] else 1

        report = create_debug_report(
            project=Path(args.project) if args.project else None,
            output=Path(args.output),
            artifact_dir=Path(args.artifact_dir) if args.artifact_dir else None,
            report_id=args.report_id,
            debugger_state=Path(args.debugger_state) if args.debugger_state else None,
            replay_inputs=Path(args.replay_inputs) if args.replay_inputs else None,
            hash_log=Path(args.hash_log) if args.hash_log else None,
            sgc_plan=Path(args.sgc_plan) if args.sgc_plan else None,
            mutation_log=Path(args.mutation_log) if args.mutation_log else None,
            adapter_feedback=Path(args.adapter_feedback) if args.adapter_feedback else None,
            overwrite=args.overwrite,
        )
    except DebugReportError as exc:
        error = {"ok": False, "schema": "xace.exportable_debug_report.error.v1", "error": redact_text(exc)}
        if args.json:
            print(json.dumps(error, indent=2, sort_keys=True))
        else:
            print(f"FAIL: {error['error']}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        status = "PASS" if report["ok"] else "FAIL"
        print(f"{status}: wrote {Path(args.output).resolve()}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
