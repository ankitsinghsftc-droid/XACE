"""
asset_reference_preflight.py - strict asset gate for runtime/save/package handoff.

The older AssetValidator intentionally keeps CGS commit permissive: PLACEHOLDER
and MISSING assets can be committed so creators can build gameplay before art is
final. This module is the stricter Phase 7 launch/handoff gate. It validates
asset references, statuses, hashes, local files, semantic binding type matches,
and per-engine support before runtime start, save, or adapter package handoff.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional


ASSET_PREFLIGHT_REPORT_SCHEMA = "xace.asset_reference_preflight_report.v1"

HASH_FIELDS = ("sha256", "content_hash", "asset_hash", "hash")
PATH_FIELDS = ("resolved_path", "source_path", "path", "asset_path", "resource_path")
FALLBACK_FIELDS = (
    "fallback",
    "fallback_asset",
    "fallback_asset_id",
    "fallback_policy",
    "placeholder_fallback",
)


class AssetPreflightPhase(str, Enum):
    """Production boundary where asset references must be safe to use."""

    RUNTIME = "runtime"
    SAVE = "save"
    ADAPTER_PACKAGE_HANDOFF = "adapter_package_handoff"

    @classmethod
    def from_value(cls, value: str | "AssetPreflightPhase") -> "AssetPreflightPhase":
        if isinstance(value, cls):
            return value
        normalized = str(value).strip().lower().replace("-", "_")
        aliases = {
            "export": cls.ADAPTER_PACKAGE_HANDOFF,
            "adapter_handoff": cls.ADAPTER_PACKAGE_HANDOFF,
            "package_handoff": cls.ADAPTER_PACKAGE_HANDOFF,
            "adapter_package": cls.ADAPTER_PACKAGE_HANDOFF,
        }
        if normalized in aliases:
            return aliases[normalized]
        for phase in cls:
            if phase.value == normalized:
                return phase
        raise ValueError(
            f"unknown asset preflight phase '{value}'. "
            f"Expected one of: {', '.join(p.value for p in cls)}"
        )


class AssetPreflightSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class AssetPreflightIssue:
    """One asset-reference preflight finding."""

    phase: AssetPreflightPhase
    severity: AssetPreflightSeverity
    code: str
    asset_id: str
    message: str
    path: str
    engine: str | None = None
    expected_type: str | None = None
    actual_type: str | None = None
    expected_hash: str | None = None
    actual_hash: str | None = None
    fallback: Any | None = None

    @property
    def blocks_handoff(self) -> bool:
        return self.severity == AssetPreflightSeverity.ERROR

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "severity": self.severity.value,
            "code": self.code,
            "asset_id": self.asset_id,
            "message": self.message,
            "path": self.path,
            "engine": self.engine,
            "expected_type": self.expected_type,
            "actual_type": self.actual_type,
            "expected_hash": self.expected_hash,
            "actual_hash": self.actual_hash,
            "fallback": self.fallback,
            "blocks_handoff": self.blocks_handoff,
        }


@dataclass
class AssetPreflightReport:
    """Deterministic result for one strict asset preflight pass."""

    phase: AssetPreflightPhase
    engine: str
    issues: list[AssetPreflightIssue] = field(default_factory=list)
    asset_refs_checked: int = 0
    asset_files_checked: int = 0
    asset_hashes_checked: int = 0
    fallbacks_documented: int = 0

    @property
    def blocked(self) -> bool:
        return any(issue.blocks_handoff for issue in self.issues)

    @property
    def ok(self) -> bool:
        return not self.blocked

    @property
    def error_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == AssetPreflightSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == AssetPreflightSeverity.WARNING)

    def add_issue(self, issue: AssetPreflightIssue) -> None:
        self.issues.append(issue)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": ASSET_PREFLIGHT_REPORT_SCHEMA,
            "ok": self.ok,
            "blocked": self.blocked,
            "phase": self.phase.value,
            "engine": self.engine,
            "asset_refs_checked": self.asset_refs_checked,
            "asset_files_checked": self.asset_files_checked,
            "asset_hashes_checked": self.asset_hashes_checked,
            "fallbacks_documented": self.fallbacks_documented,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "issues": [issue.to_dict() for issue in self.issues],
        }


TYPE_ALIASES: dict[str, str] = {
    "MESH": "MESH",
    "Mesh": "MESH",
    "TEXTURE": "TEXTURE",
    "Texture": "TEXTURE",
    "MATERIAL": "MATERIAL",
    "Material": "MATERIAL",
    "ANIMATION_CONTROLLER": "ANIMATION_CONTROLLER",
    "AnimationController": "ANIMATION_CONTROLLER",
    "ANIMATION_CLIP": "ANIMATION_CLIP",
    "AnimationClip": "ANIMATION_CLIP",
    "AUDIO_CLIP": "AUDIO_CLIP",
    "AudioClip": "AUDIO_CLIP",
    "AUDIO_MUSIC": "AUDIO_MUSIC",
    "AudioMusic": "AUDIO_MUSIC",
    "SPRITE": "SPRITE",
    "Sprite": "SPRITE",
    "PARTICLE": "PARTICLE",
    "Particle": "PARTICLE",
    "PREFAB": "PREFAB",
    "Prefab": "PREFAB",
    "FONT": "FONT",
    "Font": "FONT",
}

STATUS_ALIASES: dict[str, str] = {
    "PLACEHOLDER": "PLACEHOLDER",
    "Placeholder": "PLACEHOLDER",
    "LINKED": "LINKED",
    "Linked": "LINKED",
    "MISSING": "MISSING",
    "Missing": "MISSING",
    "UNRESOLVED": "UNRESOLVED",
    "Unresolved": "UNRESOLVED",
}

PLAYBACK_EXPECTED_TYPES: dict[str, set[str]] = {
    "Animation": {"ANIMATION_CLIP", "ANIMATION_CONTROLLER"},
    "Audio": {"AUDIO_CLIP", "AUDIO_MUSIC"},
    "Vfx": {"PARTICLE"},
}

ENGINE_SUPPORTED_TYPES: dict[str, set[str]] = {
    "godot": {
        "MESH",
        "TEXTURE",
        "MATERIAL",
        "ANIMATION_CLIP",
        "AUDIO_CLIP",
        "AUDIO_MUSIC",
        "SPRITE",
        "PARTICLE",
        "PREFAB",
        "FONT",
    },
    "unity": set(TYPE_ALIASES.values()),
    "unreal": {
        "MESH",
        "TEXTURE",
        "MATERIAL",
        "ANIMATION_CONTROLLER",
        "ANIMATION_CLIP",
        "AUDIO_CLIP",
        "AUDIO_MUSIC",
        "SPRITE",
        "PARTICLE",
        "PREFAB",
        "FONT",
    },
}

COMMON_EXTENSIONS: dict[str, set[str]] = {
    "MESH": {".fbx", ".obj", ".gltf", ".glb", ".mesh"},
    "TEXTURE": {".png", ".jpg", ".jpeg", ".tga", ".exr", ".bmp", ".dds"},
    "MATERIAL": {".mat", ".material", ".uasset", ".tres", ".res"},
    "ANIMATION_CONTROLLER": {".controller", ".anim", ".uasset", ".tres", ".res"},
    "ANIMATION_CLIP": {".anim", ".fbx", ".glb", ".gltf", ".uasset", ".res", ".tres"},
    "AUDIO_CLIP": {".wav", ".ogg", ".mp3", ".aiff", ".flac"},
    "AUDIO_MUSIC": {".wav", ".ogg", ".mp3", ".aiff", ".flac"},
    "SPRITE": {".png", ".jpg", ".jpeg", ".tga", ".sprite"},
    "PARTICLE": {".prefab", ".niagara", ".tscn", ".tres", ".vfx", ".uasset"},
    "PREFAB": {".prefab", ".uasset", ".tscn", ".scn"},
    "FONT": {".ttf", ".otf", ".fnt", ".asset"},
}

ENGINE_EXTENSION_OVERRIDES: dict[str, dict[str, set[str]]] = {
    "godot": {
        "ANIMATION_CONTROLLER": {".tres", ".res"},
        "MATERIAL": {".material", ".tres", ".res"},
        "PARTICLE": {".tscn", ".tres"},
        "PREFAB": {".tscn", ".scn"},
    },
    "unity": {
        "MATERIAL": {".mat"},
        "ANIMATION_CONTROLLER": {".controller"},
        "PARTICLE": {".prefab", ".vfx"},
        "PREFAB": {".prefab"},
    },
    "unreal": {
        "MATERIAL": {".uasset"},
        "ANIMATION_CONTROLLER": {".uasset"},
        "ANIMATION_CLIP": {".uasset", ".fbx"},
        "PARTICLE": {".uasset", ".niagara"},
        "PREFAB": {".uasset", ".umap"},
    },
}

HEX_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
ASSET_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")


def validate_before_runtime(
    cgs: Mapping[str, Any],
    *,
    project_root: str | Path,
    engine: str,
    asset_root: str | Path | None = None,
) -> AssetPreflightReport:
    return validate_asset_preflight(
        cgs,
        phase=AssetPreflightPhase.RUNTIME,
        project_root=project_root,
        engine=engine,
        asset_root=asset_root,
    )


def validate_before_adapter_package_handoff(
    cgs: Mapping[str, Any],
    *,
    project_root: str | Path,
    engine: str,
    asset_root: str | Path | None = None,
) -> AssetPreflightReport:
    return validate_asset_preflight(
        cgs,
        phase=AssetPreflightPhase.ADAPTER_PACKAGE_HANDOFF,
        project_root=project_root,
        engine=engine,
        asset_root=asset_root,
    )


def validate_before_save(
    cgs: Mapping[str, Any],
    *,
    project_root: str | Path,
    engine: str,
    asset_root: str | Path | None = None,
) -> AssetPreflightReport:
    return validate_asset_preflight(
        cgs,
        phase=AssetPreflightPhase.SAVE,
        project_root=project_root,
        engine=engine,
        asset_root=asset_root,
    )


def validate_before_adapter_handoff(
    cgs: Mapping[str, Any],
    *,
    project_root: str | Path,
    engine: str,
    asset_root: str | Path | None = None,
) -> AssetPreflightReport:
    return validate_before_adapter_package_handoff(
        cgs,
        project_root=project_root,
        engine=engine,
        asset_root=asset_root,
    )


def validate_asset_preflight(
    cgs: Mapping[str, Any],
    *,
    phase: str | AssetPreflightPhase,
    project_root: str | Path,
    engine: str,
    asset_root: str | Path | None = None,
) -> AssetPreflightReport:
    """Validates all discovered asset refs for one production handoff phase."""

    selected_phase = AssetPreflightPhase.from_value(phase)
    selected_engine = _normalize_engine(engine)
    project_base = Path(project_root).resolve()
    asset_base = Path(asset_root).resolve() if asset_root is not None else None

    report = AssetPreflightReport(phase=selected_phase, engine=selected_engine)

    entries = list(_collect_asset_entries(cgs))
    for entry_path, entry, expected_types in entries:
        _validate_asset_entry(
            entry,
            path=entry_path,
            expected_types=expected_types,
            report=report,
            project_root=project_base,
            asset_root=asset_base,
        )

    return report


def validate_all_asset_handoffs(
    cgs: Mapping[str, Any],
    *,
    project_root: str | Path,
    engines: Iterable[str] = ("godot", "unity", "unreal"),
    phases: Iterable[str | AssetPreflightPhase] = tuple(AssetPreflightPhase),
    asset_root: str | Path | None = None,
) -> list[AssetPreflightReport]:
    """Runs the strict validator across several engines/phases."""

    reports: list[AssetPreflightReport] = []
    for phase in phases:
        for engine in engines:
            reports.append(
                validate_asset_preflight(
                    cgs,
                    phase=phase,
                    project_root=project_root,
                    engine=engine,
                    asset_root=asset_root,
                )
            )
    return reports


def _validate_asset_entry(
    entry: Mapping[str, Any],
    *,
    path: str,
    expected_types: set[str] | None,
    report: AssetPreflightReport,
    project_root: Path,
    asset_root: Path | None,
) -> None:
    report.asset_refs_checked += 1

    asset_id = _string_value(entry, ("id", "asset_id"))
    asset_type_raw = _string_value(entry, ("asset_type", "type"))
    status_raw = _string_value(entry, ("status",))
    fallback = _documented_fallback(entry)

    if not asset_id:
        _error(report, "MISSING_ASSET_ID", "<missing>", path, "Asset reference has no id/asset_id.")
    elif not ASSET_ID_RE.match(asset_id):
        _error(
            report,
            "MALFORMED_ASSET_ID",
            asset_id,
            path,
            "Asset id contains characters outside the portable asset-reference set.",
        )

    canonical_type = _canonical_type(asset_type_raw)
    if canonical_type is None:
        _error(
            report,
            "INVALID_ASSET_TYPE",
            asset_id or "<missing>",
            path,
            f"Asset type '{asset_type_raw}' is not in the XACE asset type enum.",
            actual_type=asset_type_raw,
        )
        return

    canonical_status = _canonical_status(status_raw)
    if canonical_status is None:
        _error(
            report,
            "INVALID_ASSET_STATUS",
            asset_id or "<missing>",
            path,
            f"Asset status '{status_raw}' is not in the XACE asset status enum.",
            actual_type=status_raw,
        )
        return

    if expected_types and canonical_type not in expected_types:
        _error(
            report,
            "ASSET_TYPE_MISMATCH",
            asset_id or "<missing>",
            path,
            "Semantic binding playback kind rejects this asset type.",
            expected_type="|".join(sorted(expected_types)),
            actual_type=canonical_type,
        )

    supported = ENGINE_SUPPORTED_TYPES.get(report.engine)
    if supported is None:
        _error(
            report,
            "UNKNOWN_ENGINE",
            asset_id or "<missing>",
            path,
            f"Unknown engine '{report.engine}' for asset handoff validation.",
            actual_type=report.engine,
        )
        return
    if canonical_type not in supported:
        _fallback_or_error(
            report,
            code="ASSET_ENGINE_UNSUPPORTED_TYPE",
            asset_id=asset_id or "<missing>",
            path=path,
            message=f"{report.engine} handoff does not support {canonical_type} assets yet.",
            fallback=fallback,
            expected_type="|".join(sorted(supported)),
            actual_type=canonical_type,
        )

    if canonical_status == "UNRESOLVED":
        _fallback_or_error(
            report,
            code="UNRESOLVED_ASSET_REF",
            asset_id=asset_id or "<missing>",
            path=path,
            message="Unresolved asset reference cannot cross a runtime/save/adapter-package handoff boundary.",
            fallback=fallback,
        )
        return

    if canonical_status != "LINKED":
        _fallback_or_error(
            report,
            code="ASSET_STATUS_NOT_LINKED",
            asset_id=asset_id or "<missing>",
            path=path,
            message=f"Asset status {canonical_status} is not loadable without a documented fallback.",
            fallback=fallback,
        )
        return

    hash_value = _string_value(entry, HASH_FIELDS)
    if not hash_value:
        _fallback_or_error(
            report,
            code="ASSET_HASH_MISSING",
            asset_id=asset_id or "<missing>",
            path=path,
            message="Linked asset reference must include a SHA-256 content hash.",
            fallback=fallback,
        )
    elif not HEX_SHA256_RE.match(hash_value):
        _error(
            report,
            "ASSET_HASH_INVALID",
            asset_id or "<missing>",
            path,
            "Asset hash must be a 64-character hexadecimal SHA-256 digest.",
            expected_hash="<sha256-hex>",
            actual_hash=hash_value,
        )

    raw_path = _string_value(entry, PATH_FIELDS)
    if not raw_path:
        _fallback_or_error(
            report,
            code="ASSET_PATH_MISSING",
            asset_id=asset_id or "<missing>",
            path=path,
            message="Linked asset reference must include a local path before handoff.",
            fallback=fallback,
        )
        return

    resolved_path = _resolve_asset_path(raw_path, project_root=project_root, asset_root=asset_root)
    if resolved_path is None:
        _fallback_or_error(
            report,
            code="ASSET_PATH_NOT_LOCAL",
            asset_id=asset_id or "<missing>",
            path=path,
            message=f"Asset path '{raw_path}' is not a local file path this preflight can verify.",
            fallback=fallback,
        )
        return

    ext = resolved_path.suffix.lower()
    allowed_extensions = _allowed_extensions(report.engine, canonical_type)
    if ext and allowed_extensions and ext not in allowed_extensions:
        _fallback_or_error(
            report,
            code="ASSET_ENGINE_UNSUPPORTED_EXTENSION",
            asset_id=asset_id or "<missing>",
            path=path,
            message=(
                f"{report.engine} does not support extension '{ext}' for "
                f"{canonical_type}; expected one of {sorted(allowed_extensions)}."
            ),
            fallback=fallback,
            expected_type="|".join(sorted(allowed_extensions)),
            actual_type=ext,
        )

    report.asset_files_checked += 1
    if not resolved_path.exists() or not resolved_path.is_file():
        _fallback_or_error(
            report,
            code="MISSING_ASSET_FILE",
            asset_id=asset_id or "<missing>",
            path=path,
            message=f"Linked asset file does not exist: {resolved_path}",
            fallback=fallback,
        )
        return

    if hash_value and HEX_SHA256_RE.match(hash_value):
        report.asset_hashes_checked += 1
        actual_hash = _sha256_file(resolved_path)
        if actual_hash.lower() != hash_value.lower():
            _error(
                report,
                "ASSET_HASH_MISMATCH",
                asset_id or "<missing>",
                path,
                f"Linked asset content hash does not match file bytes at {resolved_path}.",
                expected_hash=hash_value.lower(),
                actual_hash=actual_hash,
            )


def _collect_asset_entries(cgs: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any], set[str] | None]]:
    entries: list[tuple[str, Mapping[str, Any], set[str] | None]] = []
    seen: set[int] = set()

    def add(path: str, value: Any, expected: set[str] | None = None) -> None:
        if not isinstance(value, Mapping):
            return
        if id(value) in seen:
            return
        seen.add(id(value))
        entries.append((path, value, expected))

    _collect_from_asset_container(cgs.get("assets"), "assets", add)
    metadata = cgs.get("metadata")
    if isinstance(metadata, Mapping):
        _collect_from_asset_container(metadata.get("assets"), "metadata.assets", add)

    semantic_bindings = cgs.get("semantic_bindings")
    if isinstance(semantic_bindings, Mapping):
        bindings = semantic_bindings.get("bindings")
        if isinstance(bindings, list):
            for index, binding in enumerate(bindings):
                if not isinstance(binding, Mapping):
                    continue
                expected = PLAYBACK_EXPECTED_TYPES.get(str(binding.get("playback_kind", "")))
                add(f"semantic_bindings.bindings[{index}].asset", binding.get("asset"), expected)

    _walk_asset_refs(cgs, "$", add)
    return entries


def _collect_from_asset_container(value: Any, path: str, add: Any) -> None:
    if isinstance(value, list):
        for index, item in enumerate(value):
            add(f"{path}[{index}]", item)
        return
    if isinstance(value, Mapping):
        if _looks_like_asset_ref(value):
            add(path, value)
        items = value.get("items")
        if isinstance(items, list):
            for index, item in enumerate(items):
                add(f"{path}.items[{index}]", item)


def _walk_asset_refs(value: Any, path: str, add: Any) -> None:
    if isinstance(value, Mapping):
        if _looks_like_asset_ref(value):
            add(path, value)
        for key, child in value.items():
            if key in {"assets"}:
                continue
            _walk_asset_refs(child, f"{path}.{key}", add)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_asset_refs(child, f"{path}[{index}]", add)


def _looks_like_asset_ref(value: Mapping[str, Any]) -> bool:
    return (
        ("asset_type" in value or "type" in value)
        and ("status" in value)
        and ("id" in value or "asset_id" in value)
    )


def _string_value(value: Mapping[str, Any], keys: Iterable[str]) -> str | None:
    for key in keys:
        raw = value.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def _canonical_type(raw: str | None) -> str | None:
    if raw is None:
        return None
    return TYPE_ALIASES.get(raw.strip())


def _canonical_status(raw: str | None) -> str | None:
    if raw is None:
        return None
    return STATUS_ALIASES.get(raw.strip())


def _normalize_engine(engine: str) -> str:
    return str(engine).strip().lower().replace("-", "_")


def _documented_fallback(entry: Mapping[str, Any]) -> Any | None:
    for key in FALLBACK_FIELDS:
        value = entry.get(key)
        if value:
            return value
    if entry.get("allow_fallback") is True:
        return {"policy": "allow_fallback"}
    return None


def _resolve_asset_path(raw_path: str, *, project_root: Path, asset_root: Path | None) -> Path | None:
    value = raw_path.strip()
    lowered = value.lower()
    if "://" in value and not lowered.startswith(("file://", "res://")):
        return None
    if lowered.startswith("file://"):
        return Path(value[7:]).resolve()
    if lowered.startswith("res://"):
        return (project_root / value[6:]).resolve()

    candidate = Path(value)
    if candidate.is_absolute():
        return candidate.resolve()

    project_candidate = (project_root / candidate).resolve()
    if project_candidate.exists():
        return project_candidate
    if asset_root is not None:
        asset_candidate = (asset_root / candidate).resolve()
        if asset_candidate.exists():
            return asset_candidate
    return project_candidate


def _allowed_extensions(engine: str, asset_type: str) -> set[str]:
    engine_map = ENGINE_EXTENSION_OVERRIDES.get(engine, {})
    if asset_type in engine_map:
        return set(engine_map[asset_type])
    return set(COMMON_EXTENSIONS.get(asset_type, set()))


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _fallback_or_error(
    report: AssetPreflightReport,
    *,
    code: str,
    asset_id: str,
    path: str,
    message: str,
    fallback: Any | None,
    expected_type: str | None = None,
    actual_type: str | None = None,
) -> None:
    if fallback is not None:
        report.fallbacks_documented += 1
        report.add_issue(
            AssetPreflightIssue(
                phase=report.phase,
                severity=AssetPreflightSeverity.WARNING,
                code="DOCUMENTED_FALLBACK_USED",
                asset_id=asset_id,
                message=f"{message} Documented fallback allows handoff to continue.",
                path=path,
                engine=report.engine,
                expected_type=expected_type,
                actual_type=actual_type,
                fallback=fallback,
            )
        )
        return
    _error(
        report,
        code,
        asset_id,
        path,
        message,
        expected_type=expected_type,
        actual_type=actual_type,
    )


def _error(
    report: AssetPreflightReport,
    code: str,
    asset_id: str,
    path: str,
    message: str,
    *,
    expected_type: str | None = None,
    actual_type: str | None = None,
    expected_hash: str | None = None,
    actual_hash: str | None = None,
) -> None:
    report.add_issue(
        AssetPreflightIssue(
            phase=report.phase,
            severity=AssetPreflightSeverity.ERROR,
            code=code,
            asset_id=asset_id,
            message=message,
            path=path,
            engine=report.engine,
            expected_type=expected_type,
            actual_type=actual_type,
            expected_hash=expected_hash,
            actual_hash=actual_hash,
        )
    )
