"""
asset_import_workflow.py - deterministic asset scan/import/repair workflow.

This layer turns user-selected files or folders into AssetManifest entries.
It stays engine-neutral: Godot, Unity, and Unreal adapters can resolve the
registered paths later, but import policy and asset IDs stay shared.
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from asset_linker import AssetLinker
from asset_manifest import AssetManifest
from asset_naming_policy import AssetNamingPolicy
from asset_reference import AssetReference
from asset_status_enum import AssetStatus
from asset_type_enum import AssetType
from placeholder_registry import PlaceholderRegistry


class AssetCopyPolicy(str, Enum):
    """How imported files are stored in a XACE project."""

    LINK_IN_PLACE = "LINK_IN_PLACE"
    COPY_TO_PROJECT = "COPY_TO_PROJECT"


@dataclass(frozen=True)
class ScannedAsset:
    """One supported file discovered during a deterministic folder scan."""

    source_path: str
    relative_path: str
    asset_type: AssetType
    sha256: str
    size_bytes: int
    suggested_asset_id: str


@dataclass(frozen=True)
class SkippedAsset:
    """One scanned file that XACE does not currently know how to import."""

    source_path: str
    relative_path: str
    reason: str


@dataclass(frozen=True)
class ImportPlan:
    """Preview of what an import will do before the manifest is mutated."""

    assets: list[ScannedAsset]
    skipped: list[SkippedAsset]
    copy_policy: AssetCopyPolicy


@dataclass(frozen=True)
class ImportedAsset:
    """One asset registered and linked by an import operation."""

    asset_id: str
    asset_type: AssetType
    source_path: str
    resolved_path: str
    sha256: str


@dataclass(frozen=True)
class ImportResult:
    """Result of applying an import plan."""

    imported: list[ImportedAsset] = field(default_factory=list)
    skipped: list[SkippedAsset] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def imported_count(self) -> int:
        return len(self.imported)


@dataclass(frozen=True)
class RepairSuggestion:
    """Candidate replacement path for a missing asset reference."""

    asset_id: str
    asset_type: AssetType
    candidate_path: str
    confidence: float
    reason: str


class AssetImportWorkflow:
    """
    Scans files, creates deterministic asset IDs, links them in the manifest,
    and suggests repairs for missing links.
    """

    def __init__(
        self,
        manifest: AssetManifest,
        placeholder_registry: Optional[PlaceholderRegistry] = None,
    ) -> None:
        self._manifest = manifest
        self._placeholder_registry = placeholder_registry or PlaceholderRegistry()
        self._linker = AssetLinker(self._manifest, self._placeholder_registry)

    def scan_folder(
        self,
        folder: str | Path,
        copy_policy: AssetCopyPolicy = AssetCopyPolicy.LINK_IN_PLACE,
        entity_type: str = "asset",
    ) -> ImportPlan:
        """
        Scans a folder recursively and returns a deterministic import preview.

        Supported files are sorted by relative path. Unsupported files are
        reported in skipped so the builder can explain them clearly.
        """
        root = Path(folder).resolve()
        if not root.exists() or not root.is_dir():
            raise ValueError(f"Asset import folder does not exist: {root}")

        assets: list[ScannedAsset] = []
        skipped: list[SkippedAsset] = []

        for path in sorted((p for p in root.rglob("*") if p.is_file()), key=_sort_key):
            relative_path = path.relative_to(root).as_posix()
            asset_type = infer_asset_type(path)
            if asset_type is None:
                skipped.append(
                    SkippedAsset(
                        source_path=str(path),
                        relative_path=relative_path,
                        reason=f"Unsupported extension '{path.suffix.lower()}'",
                    )
                )
                continue

            digest = sha256_file(path)
            assets.append(
                ScannedAsset(
                    source_path=str(path),
                    relative_path=relative_path,
                    asset_type=asset_type,
                    sha256=digest,
                    size_bytes=path.stat().st_size,
                    suggested_asset_id=AssetNamingPolicy.generate(
                        entity_type,
                        _entity_name_from_path(path),
                        asset_type,
                    ),
                )
            )

        return ImportPlan(assets=assets, skipped=skipped, copy_policy=copy_policy)

    def import_folder(
        self,
        folder: str | Path,
        copy_policy: AssetCopyPolicy = AssetCopyPolicy.LINK_IN_PLACE,
        project_asset_root: str | Path | None = None,
        entity_type: str = "asset",
    ) -> ImportResult:
        """
        Scans a folder and links every supported asset into the manifest.

        COPY_TO_PROJECT requires project_asset_root. LINK_IN_PLACE stores the
        original file path as the resolved path.
        """
        plan = self.scan_folder(folder, copy_policy=copy_policy, entity_type=entity_type)
        return self.apply_plan(plan, project_asset_root=project_asset_root)

    def apply_plan(
        self,
        plan: ImportPlan,
        project_asset_root: str | Path | None = None,
    ) -> ImportResult:
        imported: list[ImportedAsset] = []
        warnings: list[str] = []

        if plan.copy_policy == AssetCopyPolicy.COPY_TO_PROJECT and project_asset_root is None:
            raise ValueError("COPY_TO_PROJECT requires project_asset_root")

        for scanned in plan.assets:
            asset_id = self._next_available_asset_id(scanned.suggested_asset_id)
            self._manifest.register(
                AssetReference.make_placeholder(asset_id, scanned.asset_type)
            )
            self._placeholder_registry.track(asset_id, scanned.asset_type)

            resolved_path = scanned.source_path
            if plan.copy_policy == AssetCopyPolicy.COPY_TO_PROJECT:
                resolved_path = str(
                    self._copy_to_project(scanned, Path(project_asset_root).resolve())
                )

            link_result = self._linker.link(asset_id, resolved_path, source="import")
            if not link_result.success:
                warnings.append(f"{asset_id}: {link_result.error}")
                continue
            if link_result.extension_warning:
                warnings.append(f"{asset_id}: {link_result.extension_warning}")

            imported.append(
                ImportedAsset(
                    asset_id=asset_id,
                    asset_type=scanned.asset_type,
                    source_path=scanned.source_path,
                    resolved_path=resolved_path,
                    sha256=scanned.sha256,
                )
            )

        return ImportResult(imported=imported, skipped=plan.skipped, warnings=warnings)

    def suggest_repairs(
        self,
        search_root: str | Path,
        limit_per_asset: int = 3,
    ) -> list[RepairSuggestion]:
        """Suggests same-type file candidates for MISSING manifest entries."""
        root = Path(search_root).resolve()
        if not root.exists() or not root.is_dir():
            raise ValueError(f"Asset repair search folder does not exist: {root}")

        candidates = [
            path
            for path in sorted((p for p in root.rglob("*") if p.is_file()), key=_sort_key)
            if infer_asset_type(path) is not None
        ]

        suggestions: list[RepairSuggestion] = []
        for missing in self._manifest.get_by_status(AssetStatus.MISSING):
            ranked: list[RepairSuggestion] = []
            for candidate in candidates:
                if infer_asset_type(candidate) != missing.asset_type:
                    continue
                confidence = _repair_confidence(missing.asset_id, candidate)
                if confidence <= 0.0:
                    continue
                ranked.append(
                    RepairSuggestion(
                        asset_id=missing.asset_id,
                        asset_type=missing.asset_type,
                        candidate_path=str(candidate),
                        confidence=confidence,
                        reason="same asset type with matching name tokens",
                    )
                )
            ranked.sort(key=lambda item: (-item.confidence, item.candidate_path))
            suggestions.extend(ranked[:limit_per_asset])

        return suggestions

    def _next_available_asset_id(self, suggested_asset_id: str) -> str:
        if not self._manifest.contains(suggested_asset_id):
            return suggested_asset_id

        parsed = AssetNamingPolicy.parse(suggested_asset_id)
        if parsed is None:
            raise ValueError(f"Cannot version non-canonical asset_id: {suggested_asset_id}")

        entity_type, entity_name, asset_type, version = parsed
        while True:
            version += 1
            candidate = AssetNamingPolicy.generate(
                entity_type,
                entity_name,
                asset_type,
                version,
            )
            if not self._manifest.contains(candidate):
                return candidate

    def _copy_to_project(self, scanned: ScannedAsset, asset_root: Path) -> Path:
        source = Path(scanned.source_path)
        type_dir = asset_root / scanned.asset_type.value.lower()
        type_dir.mkdir(parents=True, exist_ok=True)

        target = type_dir / source.name
        if target.exists() and sha256_file(target) != scanned.sha256:
            target = type_dir / f"{source.stem}_{scanned.sha256[:8]}{source.suffix}"

        shutil.copy2(source, target)
        return target


def infer_asset_type(path: str | Path) -> Optional[AssetType]:
    """Infers an AssetType from extension plus conservative filename hints."""
    p = Path(path)
    ext = p.suffix.lower()
    stem = p.stem.lower()
    parts = set(stem.replace("-", "_").split("_"))

    if ext in {".fbx", ".obj", ".gltf", ".glb", ".mesh"}:
        if {"anim", "animation", "clip", "walk", "run", "idle"} & parts:
            return AssetType.ANIMATION_CLIP
        return AssetType.MESH
    if ext in {".png", ".jpg", ".jpeg", ".tga", ".exr", ".bmp", ".dds"}:
        if {"sprite", "icon", "ui", "button"} & parts:
            return AssetType.SPRITE
        return AssetType.TEXTURE
    if ext in {".mat", ".material"}:
        return AssetType.MATERIAL
    if ext == ".controller":
        return AssetType.ANIMATION_CONTROLLER
    if ext in {".anim", ".res"}:
        return AssetType.ANIMATION_CLIP
    if ext in {".wav", ".ogg", ".mp3", ".aiff", ".flac"}:
        if {"music", "theme", "bgm", "loop"} & parts:
            return AssetType.AUDIO_MUSIC
        return AssetType.AUDIO_CLIP
    if ext == ".sprite":
        return AssetType.SPRITE
    if ext in {".niagara", ".vfx"}:
        return AssetType.PARTICLE
    if ext in {".prefab", ".tscn", ".scn"}:
        return AssetType.PREFAB
    if ext == ".uasset":
        return _infer_uasset_type(parts)
    if ext == ".tres":
        return _infer_tres_type(parts)
    if ext in {".ttf", ".otf", ".fnt", ".asset"}:
        return AssetType.FONT
    return None


def sha256_file(path: str | Path) -> str:
    """Returns a lowercase SHA-256 digest for a file."""
    hasher = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _infer_uasset_type(parts: set[str]) -> AssetType:
    if {"anim", "animation", "clip", "sequence"} & parts:
        return AssetType.ANIMATION_CLIP
    if {"controller", "animblueprint", "blueprint"} & parts:
        return AssetType.ANIMATION_CONTROLLER
    if {"material", "mat"} & parts:
        return AssetType.MATERIAL
    if {"particle", "vfx", "niagara"} & parts:
        return AssetType.PARTICLE
    if {"prefab", "blueprint", "actor"} & parts:
        return AssetType.PREFAB
    return AssetType.MESH


def _infer_tres_type(parts: set[str]) -> Optional[AssetType]:
    if {"anim", "animation", "clip"} & parts:
        return AssetType.ANIMATION_CLIP
    if {"controller", "tree", "state"} & parts:
        return AssetType.ANIMATION_CONTROLLER
    if {"particle", "vfx"} & parts:
        return AssetType.PARTICLE
    if {"material", "mat"} & parts:
        return AssetType.MATERIAL
    return None


def _entity_name_from_path(path: Path) -> str:
    return path.stem or "asset"


def _sort_key(path: Path) -> str:
    return path.as_posix().lower()


def _repair_confidence(asset_id: str, candidate: Path) -> float:
    parsed = AssetNamingPolicy.parse(asset_id)
    id_tokens = set(asset_id.replace("-", "_").split("_"))
    if parsed is not None:
        _, entity_name, _, _ = parsed
        id_tokens.update(entity_name.split("_"))

    ignored = {
        "asset", "mesh", "tex", "mat", "anim", "clip", "sfx", "music",
        "sprite", "vfx", "prefab", "font", "v1", "v2", "v3",
    }
    id_tokens = {token for token in id_tokens if token and token not in ignored}
    file_tokens = set(candidate.stem.lower().replace("-", "_").split("_"))

    if not id_tokens or not file_tokens:
        return 0.0

    overlap = id_tokens & file_tokens
    if not overlap:
        return 0.0

    return min(1.0, 0.45 + (len(overlap) / max(len(id_tokens), 1)) * 0.55)
