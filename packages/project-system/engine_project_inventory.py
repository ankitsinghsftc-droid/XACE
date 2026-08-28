"""
engine_project_inventory.py - read-only engine project marker and reference inventory.

The scanner in this module is intentionally side-effect free. It detects the
selected folder's engine markers and inventories scenes, assets, scripts,
plugins, and input maps as references only. Import/wrap flows can then decide
whether to create XACE project files elsewhere, but the marker/inventory pass
must never create, copy, normalize, or repair engine-owned files.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


IMPORT_INVENTORY_REPORT_SCHEMA = "xace.import_marker_inventory.v1"
SUPPORTED_IMPORT_ENGINES = ("godot", "unity", "unreal")
INVENTORY_CATEGORIES = ("scenes", "assets", "scripts", "plugins", "input_maps")
REFERENCE_ONLY_MODE = "read_only_references_no_copy_no_modify"

_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".xace",
    "__pycache__",
    "Library",
    "Temp",
    "Logs",
    "obj",
    "bin",
    "Binaries",
    "Build",
    "DerivedDataCache",
    "Intermediate",
    "Saved",
    "node_modules",
}

_GODOT_SCENE_EXTENSIONS = {".tscn", ".scn"}
_GODOT_SCRIPT_EXTENSIONS = {".gd", ".cs"}
_GODOT_ASSET_EXTENSIONS = {
    ".anim",
    ".atlastex",
    ".bmp",
    ".curves",
    ".fbx",
    ".glb",
    ".gltf",
    ".import",
    ".jpg",
    ".jpeg",
    ".json",
    ".material",
    ".mesh",
    ".mp3",
    ".ogg",
    ".png",
    ".res",
    ".shader",
    ".svg",
    ".tres",
    ".wav",
    ".webp",
}

_UNITY_SCENE_EXTENSIONS = {".unity"}
_UNITY_SCRIPT_EXTENSIONS = {".cs"}
_UNITY_ASSET_EXTENSIONS = {
    ".anim",
    ".asset",
    ".controller",
    ".fbx",
    ".mat",
    ".mesh",
    ".mp3",
    ".ogg",
    ".physicmaterial",
    ".png",
    ".prefab",
    ".shader",
    ".spriteatlas",
    ".terrainlayer",
    ".wav",
}

_UNREAL_SCENE_EXTENSIONS = {".umap"}
_UNREAL_SCRIPT_EXTENSIONS = {".h", ".hpp", ".cpp", ".cc", ".cxx", ".cs"}
_UNREAL_ASSET_EXTENSIONS = {
    ".uasset",
    ".umaterial",
    ".uexp",
    ".ubulk",
    ".fbx",
    ".wav",
    ".ogg",
    ".png",
    ".jpg",
    ".jpeg",
    ".json",
}


@dataclass(frozen=True)
class EngineMarker:
    engine: str
    marker_type: str
    path: str
    confidence: str = "root-marker"

    def to_dict(self) -> dict[str, str]:
        return {
            "engine": self.engine,
            "marker_type": self.marker_type,
            "path": self.path,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class InventoryReference:
    category: str
    path: str
    engine: str
    reference_only: bool = True
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "category": self.category,
            "path": self.path,
            "engine": self.engine,
            "reference_only": self.reference_only,
        }
        if self.detail:
            data["detail"] = self.detail
        return data


def scan_engine_project_inventory(
    project_root: str | Path,
    *,
    expected_engine_type: str = "",
    max_items_per_category: int = 500,
) -> dict[str, Any]:
    """Return a read-only marker and reference inventory report for a project root."""
    root = Path(project_root).resolve()
    expected = str(expected_engine_type or "").strip().lower()
    generated_at = _utc_now()

    report = _base_report(root, expected_engine_type=expected, generated_at=generated_at)
    if not root.exists() or not root.is_dir():
        return _refusal(report, "ENGINE_PROJECT_FOLDER_NOT_FOUND", f"Engine project folder not found: {root}")

    markers = detect_engine_markers(root)
    engines = sorted({marker.engine for marker in markers})
    report["markers"] = [marker.to_dict() for marker in markers]
    report["detected_engines"] = engines

    if not engines:
        return _refusal(report, "ENGINE_MARKER_MISSING", "No supported Godot, Unity, or Unreal project marker was found at the selected root.")
    if len(engines) > 1:
        return _refusal(
            report,
            "AMBIGUOUS_ENGINE_MARKERS",
            "More than one supported engine marker was found at the selected root; choose the exact Godot, Unity, or Unreal project folder.",
        )
    if len([marker for marker in markers if marker.engine == "unreal" and marker.marker_type == "unreal.uproject"]) > 1:
        return _refusal(
            report,
            "AMBIGUOUS_UNREAL_PROJECT_MARKERS",
            "More than one Unreal .uproject marker was found at the selected root; choose the exact Unreal project folder.",
        )

    detected = engines[0]
    report["detected_engine_type"] = detected
    if expected and expected != detected:
        return _refusal(
            report,
            "ENGINE_MARKER_MISMATCH",
            f"Selected folder is detected as {detected}, not requested engine type {expected}.",
        )

    inventory = _inventory_for_engine(root, detected, max_items_per_category=max_items_per_category)
    report["inventory"] = inventory
    report["inventory_counts"] = {
        category: int(inventory[category]["count"]) for category in INVENTORY_CATEGORIES
    }
    report["ok"] = True
    report["refused"] = False
    report["reason"] = "OK"
    report["summary"] = (
        f"Detected {detected} project and inventoried "
        + ", ".join(f"{report['inventory_counts'][category]} {category}" for category in INVENTORY_CATEGORIES)
        + " as read-only references."
    )
    return report


def detect_engine_markers(project_root: str | Path) -> list[EngineMarker]:
    """Detect supported engine project markers at the selected root only."""
    root = Path(project_root).resolve()
    markers: list[EngineMarker] = []

    godot_project = root / "project.godot"
    if godot_project.is_file():
        markers.append(EngineMarker("godot", "godot.project", _rel(root, godot_project)))

    unity_assets = root / "Assets"
    unity_settings = root / "ProjectSettings"
    unity_version = unity_settings / "ProjectVersion.txt"
    if unity_assets.is_dir() and unity_settings.is_dir():
        markers.append(EngineMarker("unity", "unity.assets_projectsettings", "Assets + ProjectSettings"))
    if unity_version.is_file():
        markers.append(EngineMarker("unity", "unity.project_version", _rel(root, unity_version)))

    for uproject in sorted(root.glob("*.uproject"), key=lambda item: item.name.lower()):
        if uproject.is_file():
            markers.append(EngineMarker("unreal", "unreal.uproject", _rel(root, uproject)))

    return markers


def compact_import_inventory(report: dict[str, Any]) -> dict[str, Any]:
    """Return the manifest-safe reference subset of a full inventory report."""
    inventory = report.get("inventory", {})
    compact_inventory: dict[str, Any] = {}
    for category in INVENTORY_CATEGORIES:
        section = dict(inventory.get(category, {}) or {})
        compact_inventory[category] = {
            "count": int(section.get("count", 0)),
            "truncated": bool(section.get("truncated", False)),
            "references": list(section.get("references", []) or []),
        }
    return {
        "schema": IMPORT_INVENTORY_REPORT_SCHEMA,
        "detected_engine_type": str(report.get("detected_engine_type") or ""),
        "reference_mode": REFERENCE_ONLY_MODE,
        "reference_only": True,
        "markers": list(report.get("markers", []) or []),
        "inventory_counts": dict(report.get("inventory_counts", {}) or {}),
        "inventory": compact_inventory,
        "warnings": list(report.get("warnings", []) or []),
    }


def _base_report(root: Path, *, expected_engine_type: str, generated_at: str) -> dict[str, Any]:
    return {
        "schema": IMPORT_INVENTORY_REPORT_SCHEMA,
        "ok": False,
        "refused": True,
        "reason": "NOT_EVALUATED",
        "summary": "",
        "project_root": str(root),
        "expected_engine_type": expected_engine_type,
        "detected_engine_type": "",
        "detected_engines": [],
        "markers": [],
        "inventory": _empty_inventory(),
        "inventory_counts": {category: 0 for category in INVENTORY_CATEGORIES},
        "reference_mode": REFERENCE_ONLY_MODE,
        "reference_only": True,
        "generated_at_utc": generated_at,
        "warnings": [],
    }


def _refusal(report: dict[str, Any], reason: str, summary: str) -> dict[str, Any]:
    report["ok"] = False
    report["refused"] = True
    report["reason"] = reason
    report["summary"] = summary
    return report


def _empty_inventory() -> dict[str, Any]:
    return {
        category: {
            "count": 0,
            "truncated": False,
            "references": [],
        }
        for category in INVENTORY_CATEGORIES
    }


def _inventory_for_engine(root: Path, engine: str, *, max_items_per_category: int) -> dict[str, Any]:
    files = list(_iter_project_files(root))
    if engine == "godot":
        sections = {
            "scenes": _refs_by_extension(root, files, engine, "scenes", _GODOT_SCENE_EXTENSIONS, max_items_per_category),
            "assets": _refs_by_extension(
                root,
                files,
                engine,
                "assets",
                _GODOT_ASSET_EXTENSIONS - _GODOT_SCENE_EXTENSIONS - _GODOT_SCRIPT_EXTENSIONS,
                max_items_per_category,
            ),
            "scripts": _refs_by_extension(root, files, engine, "scripts", _GODOT_SCRIPT_EXTENSIONS, max_items_per_category),
            "plugins": _godot_plugin_refs(root, files, max_items_per_category),
            "input_maps": _godot_input_map_refs(root, max_items_per_category),
        }
        return sections

    if engine == "unity":
        return {
            "scenes": _refs_by_extension(root, files, engine, "scenes", _UNITY_SCENE_EXTENSIONS, max_items_per_category, under="Assets"),
            "assets": _refs_by_extension(
                root,
                files,
                engine,
                "assets",
                _UNITY_ASSET_EXTENSIONS - _UNITY_SCENE_EXTENSIONS - _UNITY_SCRIPT_EXTENSIONS,
                max_items_per_category,
                under="Assets",
            ),
            "scripts": _refs_by_extension(root, files, engine, "scripts", _UNITY_SCRIPT_EXTENSIONS, max_items_per_category, under="Assets"),
            "plugins": _unity_plugin_refs(root, files, max_items_per_category),
            "input_maps": _unity_input_refs(root, files, max_items_per_category),
        }

    if engine == "unreal":
        return {
            "scenes": _refs_by_extension(root, files, engine, "scenes", _UNREAL_SCENE_EXTENSIONS, max_items_per_category, under="Content"),
            "assets": _refs_by_extension(
                root,
                files,
                engine,
                "assets",
                _UNREAL_ASSET_EXTENSIONS - _UNREAL_SCENE_EXTENSIONS - _UNREAL_SCRIPT_EXTENSIONS,
                max_items_per_category,
                under="Content",
            ),
            "scripts": _unreal_script_refs(root, files, max_items_per_category),
            "plugins": _unreal_plugin_refs(root, files, max_items_per_category),
            "input_maps": _unreal_input_refs(root, files, max_items_per_category),
        }

    return _empty_inventory()


def _iter_project_files(root: Path) -> Iterable[Path]:
    for current, dir_names, file_names in os.walk(root, followlinks=False):
        dir_names[:] = [
            name
            for name in dir_names
            if name not in _SKIP_DIRS and not name.startswith(".xace_tmp_") and not name.startswith(".xace_bak_")
        ]
        current_path = Path(current)
        for file_name in sorted(file_names, key=str.lower):
            yield current_path / file_name


def _refs_by_extension(
    root: Path,
    files: Iterable[Path],
    engine: str,
    category: str,
    extensions: set[str],
    max_items: int,
    *,
    under: str = "",
) -> dict[str, Any]:
    refs: list[InventoryReference] = []
    prefix = f"{under}/" if under else ""
    for path in files:
        rel = _rel(root, path)
        if prefix and not rel.replace("\\", "/").startswith(prefix):
            continue
        if path.suffix.lower() not in extensions:
            continue
        refs.append(InventoryReference(category=category, path=rel, engine=engine))
    return _section(refs, max_items)


def _godot_plugin_refs(root: Path, files: Iterable[Path], max_items: int) -> dict[str, Any]:
    refs: list[InventoryReference] = []
    for path in files:
        rel = _rel(root, path).replace("\\", "/")
        if rel.startswith("addons/") and (path.name == "plugin.cfg" or path.suffix.lower() in {".gdextension", ".gdnlib"}):
            refs.append(InventoryReference("plugins", rel, "godot", detail="addon/plugin marker"))
    return _section(refs, max_items)


def _godot_input_map_refs(root: Path, max_items: int) -> dict[str, Any]:
    project_file = root / "project.godot"
    refs: list[InventoryReference] = []
    if not project_file.is_file():
        return _section(refs, max_items)
    in_input_section = False
    try:
        for raw_line in project_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if line.startswith("[") and line.endswith("]"):
                in_input_section = line == "[input]"
                continue
            if in_input_section and line and not line.startswith(";") and "=" in line:
                name = line.split("=", 1)[0].strip()
                if name:
                    refs.append(InventoryReference("input_maps", "project.godot", "godot", detail=f"input action: {name}"))
    except OSError:
        refs.append(InventoryReference("input_maps", "project.godot", "godot", detail="input section unreadable"))
    return _section(refs, max_items)


def _unity_plugin_refs(root: Path, files: Iterable[Path], max_items: int) -> dict[str, Any]:
    refs: list[InventoryReference] = []
    packages = root / "Packages" / "manifest.json"
    if packages.is_file():
        refs.append(InventoryReference("plugins", _rel(root, packages), "unity", detail="package manifest"))
    for path in files:
        rel = _rel(root, path).replace("\\", "/")
        if rel.startswith("Assets/Plugins/") and path.is_file():
            refs.append(InventoryReference("plugins", rel, "unity", detail="Assets/Plugins reference"))
    return _section(refs, max_items)


def _unity_input_refs(root: Path, files: Iterable[Path], max_items: int) -> dict[str, Any]:
    refs: list[InventoryReference] = []
    classic = root / "ProjectSettings" / "InputManager.asset"
    if classic.is_file():
        refs.append(InventoryReference("input_maps", _rel(root, classic), "unity", detail="classic input manager"))
    refs.extend(
        InventoryReference("input_maps", _rel(root, path), "unity", detail="input actions asset")
        for path in files
        if path.suffix.lower() == ".inputactions" and _rel(root, path).replace("\\", "/").startswith("Assets/")
    )
    return _section(refs, max_items)


def _unreal_script_refs(root: Path, files: Iterable[Path], max_items: int) -> dict[str, Any]:
    refs = [
        InventoryReference("scripts", _rel(root, path), "unreal")
        for path in files
        if path.suffix.lower() in _UNREAL_SCRIPT_EXTENSIONS
        and _rel(root, path).replace("\\", "/").startswith("Source/")
    ]
    return _section(refs, max_items)


def _unreal_plugin_refs(root: Path, files: Iterable[Path], max_items: int) -> dict[str, Any]:
    refs = [
        InventoryReference("plugins", _rel(root, path), "unreal", detail="plugin descriptor")
        for path in files
        if path.suffix.lower() == ".uplugin"
        and _rel(root, path).replace("\\", "/").startswith("Plugins/")
    ]
    return _section(refs, max_items)


def _unreal_input_refs(root: Path, files: Iterable[Path], max_items: int) -> dict[str, Any]:
    input_config_names = {
        "DefaultInput.ini",
        "DefaultEnhancedInput.ini",
    }
    refs = [
        InventoryReference("input_maps", _rel(root, path), "unreal", detail="input config")
        for path in files
        if path.name in input_config_names and _rel(root, path).replace("\\", "/").startswith("Config/")
    ]
    return _section(refs, max_items)


def _section(refs: list[InventoryReference], max_items: int) -> dict[str, Any]:
    refs_sorted = sorted(refs, key=lambda ref: (ref.path.lower(), ref.detail.lower()))
    limit = max(0, int(max_items))
    visible = refs_sorted[:limit] if limit else []
    return {
        "count": len(refs_sorted),
        "truncated": len(refs_sorted) > len(visible),
        "references": [ref.to_dict() for ref in visible],
    }


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
