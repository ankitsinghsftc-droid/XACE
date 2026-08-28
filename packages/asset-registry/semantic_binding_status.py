"""
semantic_binding_status.py - per-engine semantic binding readiness reports.

This is the X10-055 status layer on top of the stricter X10-053 asset
preflight rules. It tracks semantic playback bindings per target engine before
runtime/handoff launch and distinguishes five creator-visible states:
resolved, unresolved, unsupported, missing, and fallback.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from asset_reference_preflight import (  # noqa: E402
    ENGINE_SUPPORTED_TYPES,
    FALLBACK_FIELDS,
    HASH_FIELDS,
    HEX_SHA256_RE,
    PATH_FIELDS,
    PLAYBACK_EXPECTED_TYPES,
    STATUS_ALIASES,
    TYPE_ALIASES,
    _allowed_extensions,
    _documented_fallback,
    _resolve_asset_path,
    _sha256_file,
    _string_value,
)


SEMANTIC_BINDING_STATUS_REPORT_SCHEMA = "xace.semantic_binding_status_report.v1"
ADAPTER_STATUS_REPORT_SCHEMA = "xace.adapter.semantic_binding_status_report.v1"
SEMANTIC_BINDING_STATUSES = ("resolved", "unresolved", "unsupported", "missing", "fallback")
DEFAULT_ENGINES = ("godot", "unity", "unreal")


@dataclass(frozen=True)
class SemanticBindingEngineStatusRecord:
    """One binding's launch readiness for one engine."""

    binding_id: str
    event_name: str
    playback_kind: str
    engine: str
    status: str
    asset_id: str
    asset_type: str
    asset_status: str
    reason: str
    issue_codes: tuple[str, ...] = ()
    resource_path: str = ""
    fallback: Any | None = None
    blocks_runtime: bool = True
    blocks_handoff: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "event_name": self.event_name,
            "playback_kind": self.playback_kind,
            "engine": self.engine,
            "status": self.status,
            "asset_id": self.asset_id,
            "asset_type": self.asset_type,
            "asset_status": self.asset_status,
            "reason": self.reason,
            "issue_codes": list(self.issue_codes),
            "resource_path": self.resource_path,
            "fallback": self.fallback,
            "blocks_runtime": self.blocks_runtime,
            "blocks_handoff": self.blocks_handoff,
        }


@dataclass
class SemanticBindingStatusReport:
    """Deterministic semantic-binding status report for runtime/handoff gates."""

    cgs_hash: str
    engines: tuple[str, ...]
    records: list[SemanticBindingEngineStatusRecord] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(record.blocks_runtime or record.blocks_handoff for record in self.records)

    @property
    def ok(self) -> bool:
        return not self.blocked

    def count_by_status(self) -> dict[str, int]:
        counts = {status: 0 for status in SEMANTIC_BINDING_STATUSES}
        for record in self.records:
            counts[record.status] = counts.get(record.status, 0) + 1
        return counts

    def count_by_engine(self) -> dict[str, dict[str, int]]:
        counts = {
            engine: {status: 0 for status in SEMANTIC_BINDING_STATUSES}
            for engine in self.engines
        }
        for record in self.records:
            counts.setdefault(record.engine, {status: 0 for status in SEMANTIC_BINDING_STATUSES})
            counts[record.engine][record.status] = counts[record.engine].get(record.status, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SEMANTIC_BINDING_STATUS_REPORT_SCHEMA,
            "ok": self.ok,
            "blocked": self.blocked,
            "cgs_hash": self.cgs_hash,
            "engines": list(self.engines),
            "statuses": list(SEMANTIC_BINDING_STATUSES),
            "record_count": len(self.records),
            "count_by_status": self.count_by_status(),
            "count_by_engine": self.count_by_engine(),
            "records": [record.to_dict() for record in self.records],
        }


def evaluate_semantic_binding_status(
    cgs: Mapping[str, Any],
    *,
    project_root: str | Path,
    engines: Iterable[str] = DEFAULT_ENGINES,
    asset_root: str | Path | None = None,
) -> SemanticBindingStatusReport:
    """Evaluate every semantic binding for every requested engine."""

    selected_engines = tuple(_normalize_engine(engine) for engine in engines)
    project_base = Path(project_root).resolve()
    asset_base = Path(asset_root).resolve() if asset_root is not None else None
    manifest_by_id = _asset_manifest_by_id(cgs)
    report = SemanticBindingStatusReport(
        cgs_hash=str((cgs.get("metadata") or {}).get("cgs_hash", "") or ""),
        engines=selected_engines,
    )
    for index, binding in enumerate(_semantic_bindings(cgs)):
        for engine in selected_engines:
            report.records.append(
                _evaluate_binding_for_engine(
                    binding,
                    index=index,
                    engine=engine,
                    manifest_by_id=manifest_by_id,
                    project_root=project_base,
                    asset_root=asset_base,
                )
            )
    report.records.sort(key=lambda item: (item.engine, item.binding_id, item.status))
    return report


def build_adapter_status_reports(report: SemanticBindingStatusReport) -> dict[str, dict[str, Any]]:
    """Return one adapter-facing status report payload per engine."""

    adapter_reports: dict[str, dict[str, Any]] = {}
    for engine in report.engines:
        records = [record for record in report.records if record.engine == engine]
        adapter_reports[engine] = {
            "schema": ADAPTER_STATUS_REPORT_SCHEMA,
            "engine": engine,
            "cgs_hash": report.cgs_hash,
            "statuses": list(SEMANTIC_BINDING_STATUSES),
            "record_count": len(records),
            "blocked": any(record.blocks_runtime or record.blocks_handoff for record in records),
            "records": [record.to_dict() for record in records],
        }
    return adapter_reports


def _evaluate_binding_for_engine(
    binding: Mapping[str, Any],
    *,
    index: int,
    engine: str,
    manifest_by_id: Mapping[str, Mapping[str, Any]],
    project_root: Path,
    asset_root: Path | None,
) -> SemanticBindingEngineStatusRecord:
    binding_id = _required_text(binding.get("binding_id")) or f"semantic_bindings.bindings[{index}]"
    event_name = _required_text(binding.get("event_name"))
    playback_kind = _required_text(binding.get("playback_kind"))
    parameters = binding.get("parameters") if isinstance(binding.get("parameters"), Mapping) else {}
    target_engines = _target_engines(parameters)
    asset = _merged_asset(binding, manifest_by_id)
    asset_id = _required_text(asset.get("id") or asset.get("asset_id"))
    asset_type_raw = _required_text(asset.get("asset_type") or asset.get("type"))
    asset_status_raw = _required_text(asset.get("status"))
    fallback = _documented_fallback(asset) or _documented_fallback(binding) or _documented_fallback(parameters)
    resource_path = _string_value(asset, PATH_FIELDS) or ""

    def record(status: str, reason: str, *issue_codes: str, blocks: bool | None = None) -> SemanticBindingEngineStatusRecord:
        if blocks is None:
            blocks = status not in {"resolved", "fallback"}
        return SemanticBindingEngineStatusRecord(
            binding_id=binding_id,
            event_name=event_name,
            playback_kind=playback_kind,
            engine=engine,
            status=status,
            asset_id=asset_id,
            asset_type=asset_type_raw,
            asset_status=asset_status_raw,
            reason=reason,
            issue_codes=tuple(issue_codes),
            resource_path=resource_path,
            fallback=fallback,
            blocks_runtime=blocks,
            blocks_handoff=blocks,
        )

    def fallback_or(status: str, reason: str, *issue_codes: str) -> SemanticBindingEngineStatusRecord:
        if fallback is not None:
            return record("fallback", f"{reason} Documented fallback is present.", "DOCUMENTED_FALLBACK_USED", *issue_codes, blocks=False)
        return record(status, reason, *issue_codes)

    if engine not in target_engines:
        return record("unsupported", f"{engine} is not selected in xace_engine_targets.", "ENGINE_NOT_TARGETED")

    if not asset_id:
        return fallback_or("unresolved", "Semantic binding has no asset id.", "BINDING_ASSET_ID_MISSING")

    expected_types = PLAYBACK_EXPECTED_TYPES.get(playback_kind)
    if not expected_types:
        return record("unsupported", f"Playback kind {playback_kind!r} is not supported.", "PLAYBACK_KIND_UNSUPPORTED")

    canonical_type = TYPE_ALIASES.get(asset_type_raw)
    if canonical_type is None:
        return record("unsupported", f"Asset type {asset_type_raw!r} is not supported.", "INVALID_ASSET_TYPE")

    canonical_status = STATUS_ALIASES.get(asset_status_raw)
    if canonical_status is None:
        return record("unresolved", f"Asset status {asset_status_raw!r} is not recognized.", "INVALID_ASSET_STATUS")

    if canonical_type not in expected_types:
        return fallback_or(
            "unsupported",
            f"{playback_kind} playback cannot use {canonical_type}.",
            "ASSET_TYPE_MISMATCH",
        )

    supported_types = ENGINE_SUPPORTED_TYPES.get(engine)
    if supported_types is None:
        return record("unsupported", f"Unknown target engine {engine!r}.", "UNKNOWN_ENGINE")
    if canonical_type not in supported_types:
        return fallback_or(
            "unsupported",
            f"{engine} does not support {canonical_type} semantic playback assets.",
            "ASSET_ENGINE_UNSUPPORTED_TYPE",
        )

    if canonical_status == "UNRESOLVED":
        return fallback_or(
            "unresolved",
            "Asset reference has not been resolved to an engine-loadable asset.",
            "UNRESOLVED_ASSET_REF",
        )
    if canonical_status != "LINKED":
        return fallback_or(
            "missing",
            f"Asset status {canonical_status} is not engine-loadable before launch.",
            "ASSET_STATUS_NOT_LINKED",
        )

    hash_value = _string_value(asset, HASH_FIELDS)
    if not hash_value:
        return fallback_or("missing", "Linked asset has no SHA-256 content hash.", "ASSET_HASH_MISSING")
    if not HEX_SHA256_RE.match(hash_value):
        return record("missing", "Linked asset hash is not a valid SHA-256 digest.", "ASSET_HASH_INVALID")

    if not resource_path:
        return fallback_or("missing", "Linked asset has no local resource path.", "ASSET_PATH_MISSING")

    resolved_path = _resolve_asset_path(resource_path, project_root=project_root, asset_root=asset_root)
    if resolved_path is None:
        return fallback_or("missing", f"Asset path {resource_path!r} is not locally verifiable.", "ASSET_PATH_NOT_LOCAL")

    extension = resolved_path.suffix.lower()
    allowed_extensions = _allowed_extensions(engine, canonical_type)
    if extension and allowed_extensions and extension not in allowed_extensions:
        return fallback_or(
            "unsupported",
            f"{engine} does not support extension {extension!r} for {canonical_type}.",
            "ASSET_ENGINE_UNSUPPORTED_EXTENSION",
        )

    if not resolved_path.exists() or not resolved_path.is_file():
        return fallback_or("missing", f"Linked asset file is missing: {resolved_path}", "MISSING_ASSET_FILE")

    actual_hash = _sha256_file(resolved_path)
    if actual_hash.lower() != hash_value.lower():
        return record("missing", "Linked asset content hash does not match file bytes.", "ASSET_HASH_MISMATCH")

    return record("resolved", "Asset is linked, typed, hashed, local, and supported for this engine.", blocks=False)


def _asset_manifest_by_id(cgs: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    manifest: dict[str, Mapping[str, Any]] = {}
    for item in _asset_container_items(cgs.get("assets")):
        asset_id = _required_text(item.get("id") or item.get("asset_id"))
        if asset_id:
            manifest[asset_id] = item
    metadata = cgs.get("metadata")
    if isinstance(metadata, Mapping):
        for item in _asset_container_items(metadata.get("assets")):
            asset_id = _required_text(item.get("id") or item.get("asset_id"))
            if asset_id:
                manifest[asset_id] = item
    return manifest


def _asset_container_items(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    if isinstance(value, Mapping) and isinstance(value.get("items"), list):
        return [item for item in value["items"] if isinstance(item, Mapping)]
    return []


def _semantic_bindings(cgs: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    table = cgs.get("semantic_bindings")
    if not isinstance(table, Mapping) or not isinstance(table.get("bindings"), list):
        return []
    return [item for item in table["bindings"] if isinstance(item, Mapping)]


def _merged_asset(binding: Mapping[str, Any], manifest_by_id: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    direct = binding.get("asset") if isinstance(binding.get("asset"), Mapping) else {}
    asset_id = _required_text(direct.get("id") or direct.get("asset_id"))
    merged: dict[str, Any] = dict(manifest_by_id.get(asset_id, {}))
    merged.update(dict(direct))
    parameters = binding.get("parameters") if isinstance(binding.get("parameters"), Mapping) else {}
    for key in PATH_FIELDS:
        if not _required_text(merged.get(key)) and _required_text(parameters.get(key)):
            merged[key] = _required_text(parameters.get(key))
    for key in HASH_FIELDS:
        if not _required_text(merged.get(key)) and _required_text(parameters.get(key)):
            merged[key] = _required_text(parameters.get(key))
    for key in FALLBACK_FIELDS:
        if key not in merged and key in parameters:
            merged[key] = parameters[key]
    return merged


def _target_engines(parameters: Mapping[str, Any]) -> set[str]:
    raw = _required_text(parameters.get("xace_engine_targets"))
    if not raw:
        return set(DEFAULT_ENGINES)
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _normalize_engine(value: str) -> str:
    return str(value).strip().lower().replace("-", "_")


def _required_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
