"""
project_manifest.py - XACE project manifest contract.

The manifest is the creator-facing project boundary. It records which engine
the project targets, where the CGS lives, where assets live, adapter settings,
save slots, and model/provider preferences. It does not contain gameplay
state; gameplay remains in game.cgs.json.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


MANIFEST_FILENAME = "xace.project.json"
PROJECT_SCHEMA_VERSION = "0.1.0"
SUPPORTED_ENGINES = ("godot", "unity", "unreal", "headless")


class ProjectManifestError(ValueError):
    """Raised when a project manifest is missing or invalid."""


@dataclass
class XaceProjectManifest:
    """Serializable manifest for one XACE creator project."""

    project_id: str
    name: str
    engine_type: str
    template_id: str
    schema_version: str = PROJECT_SCHEMA_VERSION
    cgs_path: str = "game.cgs.json"
    asset_root: str = "assets"
    adapter_config: dict[str, Any] = field(default_factory=dict)
    save_slots: list[dict[str, Any]] = field(default_factory=list)
    model_provider_config: dict[str, Any] = field(default_factory=dict)
    created_at_utc: str = ""
    updated_at_utc: str = ""

    def validate(self) -> None:
        if not self.project_id.strip():
            raise ProjectManifestError("project_id must not be empty")
        if not self.name.strip():
            raise ProjectManifestError("name must not be empty")
        if self.engine_type not in SUPPORTED_ENGINES:
            raise ProjectManifestError(
                f"engine_type must be one of {list(SUPPORTED_ENGINES)}, "
                f"got {self.engine_type!r}"
            )
        if not self.template_id.strip():
            raise ProjectManifestError("template_id must not be empty")
        if not self.cgs_path.strip():
            raise ProjectManifestError("cgs_path must not be empty")
        if Path(self.cgs_path).is_absolute():
            raise ProjectManifestError("cgs_path must be project-relative")
        if not self.asset_root.strip():
            raise ProjectManifestError("asset_root must not be empty")
        if Path(self.asset_root).is_absolute():
            raise ProjectManifestError("asset_root must be project-relative")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "name": self.name,
            "engine_type": self.engine_type,
            "template_id": self.template_id,
            "cgs_path": self.cgs_path,
            "asset_root": self.asset_root,
            "adapter_config": self.adapter_config,
            "save_slots": self.save_slots,
            "model_provider_config": self.model_provider_config,
            "created_at_utc": self.created_at_utc,
            "updated_at_utc": self.updated_at_utc,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "XaceProjectManifest":
        manifest = cls(
            schema_version=str(data.get("schema_version", PROJECT_SCHEMA_VERSION)),
            project_id=str(data.get("project_id", "")),
            name=str(data.get("name", "")),
            engine_type=str(data.get("engine_type", "")),
            template_id=str(data.get("template_id", "")),
            cgs_path=str(data.get("cgs_path", "game.cgs.json")),
            asset_root=str(data.get("asset_root", "assets")),
            adapter_config=dict(data.get("adapter_config", {}) or {}),
            save_slots=list(data.get("save_slots", []) or []),
            model_provider_config=dict(data.get("model_provider_config", {}) or {}),
            created_at_utc=str(data.get("created_at_utc", "")),
            updated_at_utc=str(data.get("updated_at_utc", "")),
        )
        manifest.validate()
        return manifest


def default_adapter_config(engine_type: str) -> dict[str, Any]:
    engine = engine_type.lower()
    if engine not in SUPPORTED_ENGINES:
        raise ProjectManifestError(f"Unsupported engine type: {engine_type}")
    return {
        "engine_type": engine,
        "runtime_host": "127.0.0.1",
        "runtime_port": 7777,
        "control_port": 7778,
        "adapter_package": f"adapters/{engine}" if engine != "headless" else "",
        "capabilities": default_engine_capabilities(engine),
    }


def default_engine_capabilities(engine_type: str) -> dict[str, bool]:
    return {
        "live_entities": engine_type in {"godot", "unity", "unreal"},
        "input_bridge": engine_type in {"godot", "unity", "unreal"},
        "asset_resolver": engine_type in {"godot", "unity", "unreal"},
        "animation_playback": False,
        "audio_playback": False,
        "vfx_playback": False,
        "bidirectional_editing": False,
    }


def default_save_slots() -> list[dict[str, Any]]:
    return [
        {
            "slot_id": "slot_autosave",
            "label": "Autosave",
            "kind": "autosave",
            "enabled": True,
        },
        {
            "slot_id": "slot_manual_1",
            "label": "Manual Save 1",
            "kind": "manual",
            "enabled": True,
        },
    ]


def default_model_provider_config() -> dict[str, Any]:
    return {
        "provider": "auto",
        "model": "auto",
        "model_resolution": "explicit_or_provider_discovered",
        "allow_local_fallback": False,
        "store_api_keys_in_project": False,
    }


def save_manifest(project_dir: str | Path, manifest: XaceProjectManifest) -> Path:
    manifest.validate()
    path = Path(project_dir).resolve() / MANIFEST_FILENAME
    _atomic_write_text(
        path,
        json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n",
    )
    return path


def load_manifest(project_dir: str | Path) -> XaceProjectManifest:
    path = Path(project_dir).resolve() / MANIFEST_FILENAME
    recover_manifest(project_dir)
    if not path.exists():
        raise ProjectManifestError(f"Project manifest not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProjectManifestError(f"Project manifest is invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ProjectManifestError("Project manifest must be a JSON object")
    return XaceProjectManifest.from_dict(data)


def recover_manifest(project_dir: str | Path) -> dict[str, Any]:
    root = Path(project_dir).resolve()
    path = root / MANIFEST_FILENAME
    backup = _backup_path(path)
    removed_temps = 0
    restored = False
    for temp_path in root.glob(f".xace_tmp_{MANIFEST_FILENAME}*"):
        try:
            temp_path.unlink()
            removed_temps += 1
        except OSError:
            pass
    if _manifest_file_is_valid(path):
        return {"temp_files_removed": removed_temps, "restored": restored}
    if _manifest_file_is_valid(backup):
        _atomic_replace_from_existing(path, backup)
        restored = True
    return {"temp_files_removed": removed_temps, "restored": restored}


def atomic_write_json_file(path: Path, data: dict[str, Any], *, sort_keys: bool = True) -> None:
    _atomic_write_text(
        path,
        json.dumps(data, indent=2, sort_keys=sort_keys) + "\n",
    )


def atomic_write_text_file(path: Path, text: str) -> None:
    _atomic_write_text(path, text)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = _backup_path(path)
    if path.exists():
        _atomic_replace_from_existing(backup, path)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".xace_tmp_{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _atomic_replace_from_existing(target: Path, source: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    data = source.read_bytes()
    fd, temp_name = tempfile.mkstemp(
        prefix=f".xace_tmp_{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _backup_path(path: Path) -> Path:
    return path.with_name(f".xace_bak_{path.name}")


def _manifest_file_is_valid(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return False
        XaceProjectManifest.from_dict(data)
        return True
    except (json.JSONDecodeError, OSError, ProjectManifestError, TypeError):
        return False
