"""
project_creator.py - create/open/import XACE creator projects.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engine_project_inventory import compact_import_inventory, scan_engine_project_inventory
from project_manifest import (
    MANIFEST_FILENAME,
    ProjectManifestError,
    XaceProjectManifest,
    default_adapter_config,
    default_model_provider_config,
    default_save_slots,
    atomic_write_json_file,
    atomic_write_text_file,
    load_manifest,
    save_manifest,
)
from project_templates import canonical_template_id, get_template, make_template, slug_name


class ProjectCreationError(ValueError):
    """Raised when a project cannot be safely created."""


class ProjectImportValidationError(ProjectCreationError):
    """Raised when an existing engine project cannot be safely imported."""

    def __init__(self, report: dict[str, Any]):
        reason = str(report.get("reason") or "ENGINE_IMPORT_REFUSED")
        summary = str(report.get("summary") or "Engine project import was refused.")
        super().__init__(f"{reason}: {summary}")
        self.report = report


@dataclass(frozen=True)
class CreateProjectRequest:
    project_dir: str
    name: str
    engine_type: str = "godot"
    template_id: str = "blank_3d"
    force: bool = False


@dataclass(frozen=True)
class ProjectCreationResult:
    project_dir: str
    manifest_path: str
    cgs_path: str
    asset_root: str
    manifest: XaceProjectManifest
    cgs_hash: str
    engine_inventory: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "project_dir": self.project_dir,
            "manifest_path": self.manifest_path,
            "cgs_path": self.cgs_path,
            "asset_root": self.asset_root,
            "manifest": self.manifest.to_dict(),
            "cgs_hash": self.cgs_hash,
        }
        if self.engine_inventory is not None:
            data["engine_inventory"] = self.engine_inventory
        return data


@dataclass(frozen=True)
class OpenProjectResult:
    project_dir: str
    manifest: XaceProjectManifest
    cgs_path: str
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_dir": self.project_dir,
            "manifest": self.manifest.to_dict(),
            "cgs_path": self.cgs_path,
            "warnings": self.warnings,
        }


class ProjectCreator:
    """Creates, opens, and imports XACE project folders."""

    def create_project(self, request: CreateProjectRequest) -> ProjectCreationResult:
        project_dir = Path(request.project_dir).resolve()
        template_id = canonical_template_id(request.template_id)
        template = get_template(template_id)
        engine_type = request.engine_type.strip().lower()
        name = request.name.strip() or template.label

        self._ensure_writable_project_dir(project_dir, force=request.force)
        now = _utc_now()
        manifest = XaceProjectManifest(
            project_id=slug_name(name).lower(),
            name=name,
            engine_type=engine_type,
            template_id=template.template_id,
            cgs_path="game.cgs.json",
            asset_root="assets",
            adapter_config=default_adapter_config(engine_type),
            save_slots=default_save_slots(),
            model_provider_config=default_model_provider_config(),
            created_at_utc=now,
            updated_at_utc=now,
        )
        manifest.validate()

        cgs = make_template(template_id, name)
        cgs_path = project_dir / manifest.cgs_path
        asset_root = project_dir / manifest.asset_root
        xace_dir = project_dir / ".xace"

        project_dir.mkdir(parents=True, exist_ok=True)
        asset_root.mkdir(parents=True, exist_ok=True)
        (project_dir / "saves").mkdir(parents=True, exist_ok=True)
        (xace_dir / "snapshots").mkdir(parents=True, exist_ok=True)
        (xace_dir / "adapter").mkdir(parents=True, exist_ok=True)

        self._write_json(cgs_path, cgs, overwrite=request.force)
        manifest_path = save_manifest(project_dir, manifest)
        self._write_json(xace_dir / "adapter" / f"{engine_type}.json", manifest.adapter_config, overwrite=True)
        self._write_text(asset_root / ".gitkeep", "", overwrite=True)
        self._write_text(project_dir / "saves" / ".gitkeep", "", overwrite=True)

        return ProjectCreationResult(
            project_dir=str(project_dir),
            manifest_path=str(manifest_path),
            cgs_path=str(cgs_path),
            asset_root=str(asset_root),
            manifest=manifest,
            cgs_hash=str(cgs["metadata"]["cgs_hash"]),
        )

    def open_project(self, project_dir: str | Path) -> OpenProjectResult:
        root = Path(project_dir).resolve()
        warnings: list[str] = []
        try:
            manifest = load_manifest(root)
        except ProjectManifestError:
            cgs_path = root / "game.cgs.json"
            if not cgs_path.exists():
                raise
            warnings.append("Project has no xace.project.json; using legacy game.cgs.json defaults.")
            manifest = XaceProjectManifest(
                project_id=root.name.lower(),
                name=root.name,
                engine_type="godot",
                template_id="legacy",
            )

        cgs_path = root / manifest.cgs_path
        if not cgs_path.exists():
            warnings.append(f"CGS file is missing: {manifest.cgs_path}")

        return OpenProjectResult(
            project_dir=str(root),
            manifest=manifest,
            cgs_path=str(cgs_path),
            warnings=warnings,
        )

    def import_engine_project(
        self,
        engine_project_dir: str | Path,
        xace_project_dir: str | Path,
        *,
        name: str,
        engine_type: str,
        template_id: str = "blank_3d",
        force: bool = False,
    ) -> ProjectCreationResult:
        engine_root = Path(engine_project_dir).resolve()
        if not engine_root.exists() or not engine_root.is_dir():
            raise ProjectCreationError(f"Engine project folder not found: {engine_root}")
        engine_type_normalized = engine_type.strip().lower()
        inventory_report = scan_engine_project_inventory(
            engine_root,
            expected_engine_type=engine_type_normalized,
        )
        if not inventory_report.get("ok"):
            raise ProjectImportValidationError(inventory_report)
        result = self.create_project(CreateProjectRequest(
            project_dir=str(xace_project_dir),
            name=name,
            engine_type=engine_type_normalized,
            template_id=template_id,
            force=force,
        ))
        manifest = result.manifest
        manifest.adapter_config["engine_project_path"] = str(engine_root)
        manifest.adapter_config["engine_project_inventory"] = compact_import_inventory(inventory_report)
        save_manifest(result.project_dir, manifest)
        return ProjectCreationResult(
            project_dir=result.project_dir,
            manifest_path=result.manifest_path,
            cgs_path=result.cgs_path,
            asset_root=result.asset_root,
            manifest=manifest,
            cgs_hash=result.cgs_hash,
            engine_inventory=inventory_report,
        )

    def _ensure_writable_project_dir(self, project_dir: Path, *, force: bool) -> None:
        if not project_dir.exists():
            return
        if not project_dir.is_dir():
            raise ProjectCreationError(f"Project path is not a directory: {project_dir}")
        blocking = [
            name
            for name in (MANIFEST_FILENAME, "game.cgs.json")
            if (project_dir / name).exists()
        ]
        if blocking and not force:
            raise ProjectCreationError(
                f"Project directory already contains XACE files: {blocking}. Use force to overwrite starter files."
            )

    def _write_json(self, path: Path, data: dict[str, Any], *, overwrite: bool) -> None:
        if path.exists() and not overwrite:
            raise ProjectCreationError(f"{path} already exists. Use force to overwrite it.")
        atomic_write_json_file(path, data, sort_keys=False)

    def _write_text(self, path: Path, text: str, *, overwrite: bool) -> None:
        if path.exists() and not overwrite:
            return
        atomic_write_text_file(path, text)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
