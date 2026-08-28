"""
engine_migration_wizard.py - manual existing-project migration planning.

This module builds on the X10-057 read-only import inventory. It does not
convert engine-native projects automatically. Instead, it creates a deterministic
manual migration plan that maps discovered engine scenes, entity candidates, and
asset references into CGS-shaped starter modes, starter actors/components,
asset references, and semantic binding candidates. Every mapping carries a
reverse operation so a later manual apply can remove the proposed CGS records
without touching engine-owned files.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from engine_project_inventory import INVENTORY_CATEGORIES, scan_engine_project_inventory
from project_templates import (
    SCHEMA_VERSION,
    component,
    health_defaults,
    identity_defaults,
    input_defaults,
    slug_name,
    stable_cgs_hash,
    transform_defaults,
    velocity_defaults,
)


MANUAL_MIGRATION_PLAN_SCHEMA = "xace.manual_migration_plan.v1"
MANUAL_MIGRATION_DRAFT_SCHEMA = "xace.manual_migration_draft.v1"
MANUAL_WORK_REPORT_SCHEMA = "xace.manual_migration_work_report.v1"
MIGRATION_REFERENCE_MODE = "manual_mapping_reference_only_no_engine_mutation"

_PLAYBACK_BY_ASSET_TYPE = {
    "AnimationClip": ("Animation", "combat.attack_started", "attack"),
    "AudioClip": ("Audio", "combat.hit_confirmed", "play"),
    "Particle": ("Vfx", "combat.hit_confirmed", "spawn"),
}

_ASSET_TYPE_BY_EXTENSION = {
    ".anim": "AnimationClip",
    ".controller": "AnimationClip",
    ".wav": "AudioClip",
    ".ogg": "AudioClip",
    ".mp3": "AudioClip",
    ".tres": "Particle",
    ".res": "Particle",
    ".vfx": "Particle",
    ".prefab": "Prefab",
    ".tscn": "Prefab",
    ".uasset": "EngineAsset",
    ".umap": "Scene",
    ".unity": "Scene",
    ".png": "Texture",
    ".jpg": "Texture",
    ".jpeg": "Texture",
    ".webp": "Texture",
    ".svg": "Texture",
    ".glb": "Mesh",
    ".gltf": "Mesh",
    ".fbx": "Mesh",
}


def build_manual_migration_plan(
    engine_project_root: str | Path,
    *,
    expected_engine_type: str = "",
    base_cgs: dict[str, Any] | None = None,
    max_items_per_category: int = 500,
) -> dict[str, Any]:
    """Return a read-only manual migration plan for an existing engine project."""
    root = Path(engine_project_root).resolve()
    inventory = scan_engine_project_inventory(
        root,
        expected_engine_type=expected_engine_type,
        max_items_per_category=max_items_per_category,
    )
    report = {
        "schema": MANUAL_MIGRATION_PLAN_SCHEMA,
        "ok": False,
        "refused": True,
        "reason": "NOT_EVALUATED",
        "summary": "",
        "generated_at_utc": _utc_now(),
        "engine_project_root": str(root),
        "detected_engine_type": inventory.get("detected_engine_type", ""),
        "reference_mode": MIGRATION_REFERENCE_MODE,
        "reference_only": True,
        "inventory_report": inventory,
        "discovered_references": {
            "scenes": [],
            "entities": [],
            "assets": [],
        },
        "mappings": [],
        "manual_work_report": _empty_manual_work_report(root),
        "file_evidence": [],
        "draft_summary": {
            "scene_modes": 0,
            "starter_actors": 0,
            "starter_components": 0,
            "asset_references": 0,
            "semantic_binding_candidates": 0,
            "reversible_mappings": 0,
        },
    }
    if not inventory.get("ok"):
        report["reason"] = str(inventory.get("reason") or "INVENTORY_REFUSED")
        report["summary"] = str(inventory.get("summary") or "Inventory preflight refused the project root.")
        return report

    engine = str(inventory.get("detected_engine_type") or "")
    scene_refs = _references(inventory, "scenes")
    asset_refs = _references(inventory, "assets")
    entities = _discover_entity_candidates(root, engine, scene_refs)

    mappings: list[dict[str, Any]] = []
    scene_mode_by_path: dict[str, str] = {}
    for scene_ref in scene_refs:
        scene_path = str(scene_ref["path"])
        mode_id = _unique_id("mode_import", scene_path, [*scene_mode_by_path.values()])
        scene_mode_by_path[scene_path] = mode_id
        mappings.append(_scene_mapping(engine, root, scene_ref, mode_id))

    actor_ids: list[str] = []
    for index, entity in enumerate(entities):
        scene_path = str(entity.get("scene_path") or "")
        mode_id = scene_mode_by_path.get(scene_path) or _default_mode_id(base_cgs)
        mapping = _entity_mapping(engine, root, entity, mode_id, index, actor_ids)
        actor_ids.append(str(mapping.get("target", {}).get("actor_id") or ""))
        mappings.append(mapping)

    for asset_ref in asset_refs:
        mappings.append(_asset_mapping(engine, root, asset_ref))
        semantic = _semantic_binding_mapping(engine, root, asset_ref)
        if semantic is not None:
            mappings.append(semantic)

    manual_work_report = _manual_work_report(root, engine, inventory, mappings)
    file_evidence = _file_evidence_for_plan(root, inventory, mappings)
    report.update({
        "ok": True,
        "refused": False,
        "reason": "OK",
        "summary": (
            f"Built a manual {engine} migration plan with {len(scene_refs)} scene(s), "
            f"{len(entities)} entity candidate(s), {len(asset_refs)} asset reference(s), "
            f"and {len(mappings)} reversible mapping(s)."
        ),
        "discovered_references": {
            "scenes": scene_refs,
            "entities": entities,
            "assets": asset_refs,
        },
        "mappings": mappings,
        "manual_work_report": manual_work_report,
        "file_evidence": file_evidence,
        "draft_summary": _draft_summary(mappings),
    })
    return report


def materialize_manual_migration_draft(base_cgs: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """Create a CGS-shaped preview from a manual migration plan without persisting it."""
    if not plan.get("ok"):
        raise ValueError(f"manual migration plan is not usable: {plan.get('reason')}")
    draft = copy.deepcopy(base_cgs)
    draft.setdefault("metadata", {})
    draft["metadata"].setdefault("version", SCHEMA_VERSION)
    draft["metadata"].setdefault("schema_version", SCHEMA_VERSION)
    draft["metadata"]["manual_migration"] = {
        "schema": MANUAL_MIGRATION_DRAFT_SCHEMA,
        "plan_schema": plan.get("schema"),
        "engine_project_root": plan.get("engine_project_root"),
        "detected_engine_type": plan.get("detected_engine_type"),
        "reference_mode": MIGRATION_REFERENCE_MODE,
        "applied": False,
    }
    assets_existed = "assets" in draft
    semantic_bindings_existed = "semantic_bindings" in draft
    draft.setdefault("global_systems", [])
    draft.setdefault("modes", [])
    draft_assets = _asset_list(draft)
    draft_bindings = draft.setdefault("semantic_bindings", {}).setdefault("bindings", [])

    rollback = {
        "schema": "xace.manual_migration_rollback.v1",
        "reference_mode": MIGRATION_REFERENCE_MODE,
        "remove_modes": [],
        "remove_actors": [],
        "remove_assets": [],
        "remove_semantic_bindings": [],
        "remove_empty_assets_container": not assets_existed,
        "remove_empty_semantic_bindings_container": not semantic_bindings_existed,
        "restore_engine_action": "none_engine_files_not_modified",
    }

    for mapping in plan.get("mappings", []):
        mapping_type = mapping.get("mapping_type")
        target = mapping.get("target", {})
        if mapping_type == "engine_scene_to_cgs_mode":
            mode_id = str(target.get("mode_id") or "")
            if mode_id and not _mode_by_id(draft, mode_id):
                draft["modes"].append({
                    "id": mode_id,
                    "schema_version": draft["metadata"].get("schema_version", SCHEMA_VERSION),
                    "is_default": False,
                    "actors": [],
                    "systems": [],
                    "rules": [],
                    "migration_source": mapping.get("source", {}),
                })
                rollback["remove_modes"].append(mode_id)
        elif mapping_type == "engine_entity_to_cgs_starter_actor":
            mode_id = str(target.get("mode_id") or _default_mode_id(draft))
            mode = _mode_by_id(draft, mode_id)
            if mode is None:
                mode = {
                    "id": mode_id,
                    "schema_version": draft["metadata"].get("schema_version", SCHEMA_VERSION),
                    "is_default": False,
                    "actors": [],
                    "systems": [],
                    "rules": [],
                }
                draft["modes"].append(mode)
                rollback["remove_modes"].append(mode_id)
            actor = copy.deepcopy(target.get("actor") or {})
            if actor and not any(existing.get("id") == actor.get("id") for existing in mode.setdefault("actors", [])):
                mode["actors"].append(actor)
                rollback["remove_actors"].append({"mode_id": mode_id, "actor_id": actor.get("id")})
        elif mapping_type == "engine_asset_to_cgs_asset_reference":
            asset = copy.deepcopy(target.get("asset") or {})
            if asset and not any(existing.get("id") == asset.get("id") for existing in draft_assets):
                draft_assets.append(asset)
                rollback["remove_assets"].append(asset.get("id"))
        elif mapping_type == "engine_asset_to_semantic_binding_candidate":
            binding = copy.deepcopy(target.get("semantic_binding") or {})
            if binding and not any(existing.get("binding_id") == binding.get("binding_id") for existing in draft_bindings):
                draft_bindings.append(binding)
                rollback["remove_semantic_bindings"].append(binding.get("binding_id"))

    draft["metadata"]["manual_migration"]["rollback"] = rollback
    draft["metadata"]["cgs_hash"] = stable_cgs_hash(draft)
    return {
        "schema": MANUAL_MIGRATION_DRAFT_SCHEMA,
        "ok": True,
        "preview_only": True,
        "cgs": draft,
        "rollback": rollback,
        "summary": _draft_summary(plan.get("mappings", [])),
    }


def revert_manual_migration_draft(draft_cgs: dict[str, Any], rollback: dict[str, Any]) -> dict[str, Any]:
    """Remove records created by materialize_manual_migration_draft."""
    reverted = copy.deepcopy(draft_cgs)
    remove_modes = set(str(item) for item in rollback.get("remove_modes", []))
    remove_assets = set(str(item) for item in rollback.get("remove_assets", []))
    remove_bindings = set(str(item) for item in rollback.get("remove_semantic_bindings", []))
    remove_actors = {
        (str(item.get("mode_id") or ""), str(item.get("actor_id") or ""))
        for item in rollback.get("remove_actors", [])
        if isinstance(item, dict)
    }

    modes: list[dict[str, Any]] = []
    for mode in reverted.get("modes", []):
        mode_id = str(mode.get("id") or "")
        if mode_id in remove_modes:
            continue
        actors = [
            actor
            for actor in mode.get("actors", [])
            if (mode_id, str(actor.get("id") or "")) not in remove_actors
        ]
        mode["actors"] = actors
        modes.append(mode)
    reverted["modes"] = modes

    if "assets" in reverted:
        if isinstance(reverted["assets"], dict):
            reverted["assets"]["items"] = [
                asset
                for asset in reverted["assets"].get("items", [])
                if str(asset.get("id") or "") not in remove_assets
            ]
            if rollback.get("remove_empty_assets_container") and not reverted["assets"].get("items"):
                reverted.pop("assets", None)
        else:
            reverted["assets"] = [
                asset
                for asset in reverted.get("assets", [])
                if str(asset.get("id") or "") not in remove_assets
            ]
            if rollback.get("remove_empty_assets_container") and not reverted.get("assets"):
                reverted.pop("assets", None)

    bindings = reverted.get("semantic_bindings", {}).get("bindings", [])
    if bindings:
        reverted["semantic_bindings"]["bindings"] = [
            binding
            for binding in bindings
            if str(binding.get("binding_id") or "") not in remove_bindings
        ]
        if rollback.get("remove_empty_semantic_bindings_container") and not reverted["semantic_bindings"]["bindings"]:
            reverted.pop("semantic_bindings", None)

    reverted.get("metadata", {}).pop("manual_migration", None)
    reverted.setdefault("metadata", {})["cgs_hash"] = stable_cgs_hash(reverted)
    return reverted


def _scene_mapping(engine: str, root: Path, scene_ref: dict[str, Any], mode_id: str) -> dict[str, Any]:
    rel_path = str(scene_ref.get("path") or "")
    return {
        "mapping_id": f"map.scene.{mode_id}",
        "mapping_type": "engine_scene_to_cgs_mode",
        "manual_approval_required": True,
        "source": _source(root, engine, rel_path, reference_kind="scene"),
        "target": {
            "cgs_path": f"modes[id={mode_id}]",
            "mode_id": mode_id,
            "is_default": False,
            "record_kind": "starter_mode",
        },
        "reverse": _reverse(["mode"], rel_path),
    }


def _entity_mapping(
    engine: str,
    root: Path,
    entity: dict[str, Any],
    mode_id: str,
    index: int,
    existing_actor_ids: Iterable[str],
) -> dict[str, Any]:
    entity_name = str(entity.get("name") or f"Entity {index + 1}")
    actor_id = _unique_id("actor_import", f"{entity.get('scene_path', '')}_{entity_name}", existing_actor_ids)
    actor_type, control_type, components = _starter_actor_parts(entity_name, entity.get("entity_type", ""))
    actor = {
        "id": actor_id,
        "actor_type": actor_type,
        "control_type": control_type,
        "components": components,
        "migration_source": {
            "engine": engine,
            "scene_path": entity.get("scene_path", ""),
            "entity_name": entity_name,
            "entity_type": entity.get("entity_type", ""),
            "reference_only": True,
        },
    }
    return {
        "mapping_id": f"map.entity.{actor_id}",
        "mapping_type": "engine_entity_to_cgs_starter_actor",
        "manual_approval_required": True,
        "source": {
            **_source(root, engine, str(entity.get("scene_path") or ""), reference_kind="entity"),
            "entity_name": entity_name,
            "entity_type": entity.get("entity_type", ""),
            "line": entity.get("line", 0),
        },
        "target": {
            "cgs_path": f"modes[id={mode_id}].actors[id={actor_id}]",
            "mode_id": mode_id,
            "actor_id": actor_id,
            "actor": actor,
            "starter_components": [component_record["name"] for component_record in components],
        },
        "reverse": _reverse(["actor"], str(entity.get("scene_path") or "")),
    }


def _asset_mapping(engine: str, root: Path, asset_ref: dict[str, Any]) -> dict[str, Any]:
    rel_path = str(asset_ref.get("path") or "")
    asset_type = _asset_type_for_path(rel_path)
    asset_id = _unique_id("asset_import", rel_path, [])
    asset = {
        "id": asset_id,
        "asset_type": asset_type,
        "status": "Linked",
        "path": rel_path,
        "sha256": _sha256_file(root / rel_path),
        "migration_source": {
            "engine": engine,
            "path": rel_path,
            "reference_only": True,
        },
    }
    return {
        "mapping_id": f"map.asset.{asset_id}",
        "mapping_type": "engine_asset_to_cgs_asset_reference",
        "manual_approval_required": True,
        "source": _source(root, engine, rel_path, reference_kind="asset"),
        "target": {
            "cgs_path": f"assets[id={asset_id}]",
            "asset_id": asset_id,
            "asset": asset,
        },
        "reverse": _reverse(["asset"], rel_path),
    }


def _semantic_binding_mapping(engine: str, root: Path, asset_ref: dict[str, Any]) -> dict[str, Any] | None:
    rel_path = str(asset_ref.get("path") or "")
    asset_type = _asset_type_for_path(rel_path)
    playback = _PLAYBACK_BY_ASSET_TYPE.get(asset_type)
    if playback is None:
        return None
    playback_kind, event_name, action = playback
    asset_id = _unique_id("asset_import", rel_path, [])
    binding_id = _unique_id("bind_import", f"{playback_kind}_{rel_path}", [])
    binding = {
        "binding_id": binding_id,
        "event_name": event_name,
        "playback_kind": playback_kind,
        "asset": {
            "id": asset_id,
            "asset_type": asset_type,
            "status": "Linked",
        },
        "semantic_action": action,
        "entity_selector": "SourceEntity",
        "parameters": {
            "resource_path": rel_path,
            "asset_path": rel_path,
            "xace_engine_targets": engine,
            "migration_reference_only": True,
        },
        "enabled": True,
        "priority": {"Animation": 10, "Audio": 20, "Vfx": 30}[playback_kind],
        "migration_source": {
            "engine": engine,
            "path": rel_path,
            "reference_only": True,
        },
    }
    return {
        "mapping_id": f"map.semantic_binding.{binding_id}",
        "mapping_type": "engine_asset_to_semantic_binding_candidate",
        "manual_approval_required": True,
        "source": _source(root, engine, rel_path, reference_kind="semantic_asset"),
        "target": {
            "cgs_path": f"semantic_bindings.bindings[binding_id={binding_id}]",
            "binding_id": binding_id,
            "semantic_binding": binding,
        },
        "reverse": _reverse(["semantic_binding"], rel_path),
    }


def _starter_actor_parts(entity_name: str, entity_type: str) -> tuple[str, str, list[dict[str, Any]]]:
    lower = f"{entity_name} {entity_type}".lower()
    if "player" in lower or "character" in lower:
        return (
            "PlayerCharacter",
            "Human",
            [
                component(1, "COMP_TRANSFORM_V1", transform_defaults(0.0, 0.0)),
                component(5, "COMP_VELOCITY_V1", velocity_defaults(5.0)),
                component(6, "COMP_INPUT_V1", input_defaults("third_person")),
                component(100, "COMP_HEALTH_V1", health_defaults(100.0)),
                component(2, "COMP_IDENTITY_V1", identity_defaults(entity_name)),
            ],
        )
    return (
        "EngineReference",
        "WorldObject",
        [
            component(1, "COMP_TRANSFORM_V1", transform_defaults(0.0, 0.0, bounds=False)),
            component(2, "COMP_IDENTITY_V1", identity_defaults(entity_name)),
        ],
    )


def _discover_entity_candidates(root: Path, engine: str, scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    for scene_ref in scenes:
        rel_path = str(scene_ref.get("path") or "")
        path = root / rel_path
        if engine == "godot":
            entities.extend(_discover_godot_entities(path, rel_path))
        elif engine == "unity":
            entities.extend(_discover_unity_entities(path, rel_path))
        elif engine == "unreal":
            entities.extend(_discover_unreal_entities(path, rel_path))
    return _dedupe_entities(entities)


def _discover_godot_entities(path: Path, rel_path: str) -> list[dict[str, Any]]:
    node_re = re.compile(r'^\[node\s+(?P<attrs>.+)\]$')
    entities: list[dict[str, Any]] = []
    for line_no, line in _read_lines(path):
        match = node_re.match(line.strip())
        if not match:
            continue
        attrs = _parse_key_values(match.group("attrs"))
        name = attrs.get("name", "").strip('"')
        entity_type = attrs.get("type", "").strip('"') or "Node"
        if name:
            entities.append(_entity(rel_path, name, entity_type, line_no))
    return entities


def _discover_unity_entities(path: Path, rel_path: str) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    for line_no, line in _read_lines(path):
        stripped = line.strip()
        if stripped.startswith("m_Name:"):
            name = stripped.split(":", 1)[1].strip().strip('"')
            if name:
                entities.append(_entity(rel_path, name, "GameObject", line_no))
    return entities


def _discover_unreal_entities(path: Path, rel_path: str) -> list[dict[str, Any]]:
    actor_re = re.compile(r"Begin\s+Actor\b.*?(?:Name=|ActorLabel=)(?P<name>\"[^\"]+\"|\S+)")
    entities: list[dict[str, Any]] = []
    for line_no, line in _read_lines(path):
        match = actor_re.search(line)
        if not match:
            continue
        name = match.group("name").strip().strip('"')
        entities.append(_entity(rel_path, name, "Actor", line_no))
    if not entities and path.exists():
        entities.append(_entity(rel_path, path.stem, "MapReference", 0))
    return entities


def _entity(scene_path: str, name: str, entity_type: str, line: int) -> dict[str, Any]:
    return {
        "scene_path": scene_path,
        "name": name,
        "entity_type": entity_type,
        "line": line,
        "reference_only": True,
    }


def _dedupe_entities(entities: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for entity in entities:
        key = (
            str(entity.get("scene_path") or ""),
            str(entity.get("name") or "").lower(),
            str(entity.get("entity_type") or "").lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(entity)
    return result


def _manual_work_report(root: Path, engine: str, inventory: dict[str, Any], mappings: list[dict[str, Any]]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for script in _references(inventory, "scripts"):
        items.append(_manual_item(root, engine, script, "script_review", "Review script behavior and choose CGS systems/rules manually."))
    for plugin in _references(inventory, "plugins"):
        items.append(_manual_item(root, engine, plugin, "plugin_review", "Review plugin dependency and decide whether an adapter/package dependency is required."))
    for input_map in _references(inventory, "input_maps"):
        items.append(_manual_item(root, engine, input_map, "input_map_review", "Review engine input action and map it to COMP_INPUT_V1 action_map manually."))
    return {
        "schema": MANUAL_WORK_REPORT_SCHEMA,
        "engine": engine,
        "reference_mode": MIGRATION_REFERENCE_MODE,
        "manual_approval_required": True,
        "items": items,
        "mapping_count": len(mappings),
        "all_sources_reference_only": all(bool(mapping.get("source", {}).get("reference_only")) for mapping in mappings),
    }


def _empty_manual_work_report(root: Path) -> dict[str, Any]:
    return {
        "schema": MANUAL_WORK_REPORT_SCHEMA,
        "engine_project_root": str(root),
        "reference_mode": MIGRATION_REFERENCE_MODE,
        "manual_approval_required": True,
        "items": [],
        "mapping_count": 0,
        "all_sources_reference_only": True,
    }


def _manual_item(root: Path, engine: str, ref: dict[str, Any], item_type: str, instruction: str) -> dict[str, Any]:
    rel_path = str(ref.get("path") or "")
    return {
        "item_id": _unique_id(f"manual_{item_type}", rel_path + str(ref.get("detail", "")), []),
        "item_type": item_type,
        "source": _source(root, engine, rel_path, reference_kind=item_type),
        "instruction": instruction,
        "resolved": False,
        "manual_only": True,
    }


def _file_evidence_for_plan(root: Path, inventory: dict[str, Any], mappings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    paths: set[str] = set()
    for category in INVENTORY_CATEGORIES:
        for ref in _references(inventory, category):
            path = str(ref.get("path") or "")
            if path and "/" in path or path.endswith((".godot", ".unity", ".umap", ".png", ".wav", ".ogg", ".mp3", ".anim", ".prefab", ".tres", ".uasset", ".cpp", ".cs", ".gd", ".ini", ".json", ".cfg")):
                paths.add(path)
    for mapping in mappings:
        path = str(mapping.get("source", {}).get("path") or "")
        if path:
            paths.add(path)
    evidence: list[dict[str, Any]] = []
    for rel_path in sorted(paths, key=str.lower):
        path = root / rel_path
        evidence.append({
            "path": rel_path,
            "exists": path.is_file(),
            "size": path.stat().st_size if path.is_file() else 0,
            "sha256": _sha256_file(path) if path.is_file() else "",
            "reference_only": True,
        })
    return evidence


def _source(root: Path, engine: str, rel_path: str, *, reference_kind: str) -> dict[str, Any]:
    path = root / rel_path
    return {
        "engine": engine,
        "path": rel_path,
        "reference_kind": reference_kind,
        "exists": path.is_file(),
        "sha256": _sha256_file(path) if path.is_file() else "",
        "reference_only": True,
    }


def _reverse(remove_targets: list[str], source_path: str) -> dict[str, Any]:
    return {
        "reversible": True,
        "remove_created_cgs_records": remove_targets,
        "restore_engine_action": "none_engine_files_not_modified",
        "source_path": source_path,
    }


def _draft_summary(mappings: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "scene_modes": sum(1 for mapping in mappings if mapping.get("mapping_type") == "engine_scene_to_cgs_mode"),
        "starter_actors": sum(1 for mapping in mappings if mapping.get("mapping_type") == "engine_entity_to_cgs_starter_actor"),
        "starter_components": sum(
            len(mapping.get("target", {}).get("starter_components", []))
            for mapping in mappings
            if mapping.get("mapping_type") == "engine_entity_to_cgs_starter_actor"
        ),
        "asset_references": sum(1 for mapping in mappings if mapping.get("mapping_type") == "engine_asset_to_cgs_asset_reference"),
        "semantic_binding_candidates": sum(
            1 for mapping in mappings if mapping.get("mapping_type") == "engine_asset_to_semantic_binding_candidate"
        ),
        "reversible_mappings": sum(1 for mapping in mappings if mapping.get("reverse", {}).get("reversible") is True),
    }


def _references(inventory: dict[str, Any], category: str) -> list[dict[str, Any]]:
    refs = inventory.get("inventory", {}).get(category, {}).get("references", [])
    return [dict(ref) for ref in refs if isinstance(ref, dict)]


def _asset_list(cgs: dict[str, Any]) -> list[dict[str, Any]]:
    assets = cgs.setdefault("assets", [])
    if isinstance(assets, dict):
        items = assets.setdefault("items", [])
        return items
    if not isinstance(assets, list):
        cgs["assets"] = []
        return cgs["assets"]
    return assets


def _mode_by_id(cgs: dict[str, Any], mode_id: str) -> dict[str, Any] | None:
    for mode in cgs.get("modes", []):
        if mode.get("id") == mode_id:
            return mode
    return None


def _default_mode_id(cgs: dict[str, Any] | None) -> str:
    if cgs:
        for mode in cgs.get("modes", []):
            if mode.get("is_default"):
                return str(mode.get("id") or "mode_gameplay")
        modes = cgs.get("modes", [])
        if modes:
            return str(modes[0].get("id") or "mode_gameplay")
    return "mode_gameplay"


def _asset_type_for_path(rel_path: str) -> str:
    return _ASSET_TYPE_BY_EXTENSION.get(Path(rel_path).suffix.lower(), "EngineAsset")


def _unique_id(prefix: str, value: str, existing: Iterable[str]) -> str:
    base = slug_name(Path(value).stem if "/" in value or "\\" in value else value).lower()
    if not base:
        base = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    candidate = f"{prefix}_{base}"
    used = set(existing)
    if candidate not in used:
        return candidate
    suffix = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"{candidate}_{suffix}"


def _parse_key_values(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for match in re.finditer(r"(\w+)=(\"[^\"]*\"|\S+)", text):
        result[match.group(1)] = match.group(2)
    return result


def _read_lines(path: Path) -> Iterable[tuple[int, str]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return list(enumerate(text.splitlines(), start=1))


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        return ""
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
