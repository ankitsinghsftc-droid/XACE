"""XP-003 immutable world projection from CGS and compiled actor blueprints."""
from __future__ import annotations
import hashlib
import copy
import importlib.util
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from .entity_blueprint.blueprint_registry import BlueprintRegistry

SCALE = 1_000_000
LIMIT = 8192 * SCALE
MAX_OBJECTS = 4096
PROFILE = "fixed64_y_up_neg_z_v1"
KINDS = {"static_box", "kinematic_box", "trigger", "spawn", "anchor"}
ASSET_TYPES = {name.upper(): "".join(word.title() for word in name.split("_")) for name in (
    "mesh", "texture", "material", "animation_controller", "animation_clip",
    "audio_clip", "audio_music", "sprite", "particle", "prefab", "font")}

class WorldCompileError(ValueError):
    pass

def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")

@dataclass(frozen=True)
class CompiledWorld:
    content_bytes: bytes
    manifest_bytes: bytes

    def content(self) -> dict:
        return json.loads(self.content_bytes)

    def manifest(self) -> dict:
        return json.loads(self.manifest_bytes)

def require(condition: bool, message: str) -> None:
    if not condition:
        raise WorldCompileError(message)

def semantic_id(value: Any) -> str:
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", value) is not None,
            "world IDs must be bounded semantic tokens, never native paths")
    return value

def exact(value: Any, keys: set[str], optional: set[str] = frozenset()) -> dict:
    require(isinstance(value, dict), "world record must be an object")
    require(keys <= value.keys() and value.keys() <= keys | optional, "world record has missing or unknown fields")
    return value

def vector(value: Any, positive: bool = False) -> dict:
    exact(value, {"x", "y", "z"})
    require(all(type(v) is int and -LIMIT <= v <= LIMIT and (not positive or v > 0) for v in value.values()),
            "coordinates require bounded Fixed64 micro-units; sizes must be positive")
    return dict(value)

def validate_source(cgs: dict) -> None:
    # Reuse the strict repository validator, not its permissive legacy/draft modes.
    name = "_xace_strict_cgs_validator"
    module = sys.modules.get(name)
    if module is None:
        path = Path(__file__).resolve().parents[3] / "tools" / "cgs_schema_validate.py"
        spec = importlib.util.spec_from_file_location(name, path)
        require(spec is not None and spec.loader is not None, "strict CGS validator unavailable")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(name, None)
            raise
    result = module.ValidationResult()
    module.validate_cgs(cgs, result, allow_legacy_hash=False, allow_draft_hash=False)
    require(result.ok, "strict CGS validation: " + "; ".join(result.errors))

def compile_world(cgs: dict[str, Any], blueprints: BlueprintRegistry, source_cgs: dict[str, Any]) -> CompiledWorld | None:
    selected = [(m, m["world"]["contract"]) for m in cgs.get("modes", [])
                if isinstance(m.get("world"), dict) and "contract" in m["world"]]
    if not selected:
        return None
    require(len(selected) == 1, "world v2 requires exactly one selected contract mode")
    validate_source(source_cgs)
    # Portable normalization may change display enums only, never world/source data.
    def without_display_enums(value):
        value = copy.deepcopy(value)
        for item in value.get("modes", []):
            for actor in item.get("actors", []):
                actor.pop("actor_type", None); actor.pop("control_type", None)
        return value
    require(without_display_enums(cgs) == without_display_enums(source_cgs), "world projection differs from source CGS")
    mode, contract = selected[0]
    if contract.get("contract_version") == 3:
        from .world_contract_v3 import compile_world_v3
        return compile_world_v3(mode, copy.deepcopy(contract), blueprints, source_cgs)
    exact(contract, {"contract_version", "id", "version", "numeric_profile", "objects", "capability_declarations"})
    require(type(contract["contract_version"]) is int and contract["contract_version"] == 2, "unsupported world version")
    require(contract["numeric_profile"] == PROFILE, "unsupported numeric profile")
    capability_declarations = contract["capability_declarations"]
    require(isinstance(capability_declarations, list) and len(capability_declarations) <= 4096, "invalid capability declarations")
    declared = {}
    for declaration in capability_declarations:
        exact(declaration, {"id", "allowed_kinds"})
        cid = semantic_id(declaration["id"])
        require(re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+\.v[1-9][0-9]*", cid) is not None and
                cid not in {"input.timed.v1", "world.aabb.v1", "world.semantic_bindings.v1"}, "invalid semantic capability ID")
        kinds = declaration["allowed_kinds"]
        require(isinstance(kinds, list) and kinds and all(isinstance(k, str) for k in kinds) and
                len(set(kinds)) == len(kinds) and set(kinds) <= KINDS, "invalid declared roles")
        require(cid not in declared, "duplicate capability declaration")
        declared[cid] = sorted(kinds)
    mode_id = semantic_id(mode["id"])
    actor_list = mode.get("actors", [])
    actors = {a["id"]: a for a in actor_list}
    require(len(actors) == len(actor_list), "duplicate actor IDs")
    declarations = contract["objects"]
    require(isinstance(declarations, list) and 0 < len(declarations) <= MAX_OBJECTS, "world object count must be 1..4096")
    assets = {a["id"]: a for a in source_cgs.get("assets", [])}
    def validate_reference(ref):
        exact(ref, {"id", "asset_type", "status"})
        semantic_id(ref["id"])
        registered = assets.get(ref["id"])
        require(registered is not None and ref["status"] in {"PLACEHOLDER", "LINKED", "MISSING"}, "unresolved asset reference")
        require(ref["asset_type"] in ASSET_TYPES and ref["asset_type"] == registered.get("asset_type") and ref["status"] == registered.get("status"), "asset reference differs from registry")
        return {"id": ref["id"], "asset_type": ASSET_TYPES[ref["asset_type"]]}
    def check_references(value):
        if isinstance(value, dict):
            if {"id", "asset_type", "status"} <= value.keys():
                validate_reference(value)
            else:
                for key, child in value.items():
                    if key in {"asset_reference", "material_ref", "controller_ref"}:
                        validate_reference(child)
                    else:
                        check_references(child)
        elif isinstance(value, list):
            for child in value: check_references(child)
    check_references(source_cgs.get("modes", []))
    objects, ids, actor_ids = [], set(), set()
    for record in declarations:
        exact(record, {"id", "actor_id", "kind", "capabilities"}, {"target_id", "asset_reference"})
        oid, aid, kind = semantic_id(record["id"]), semantic_id(record["actor_id"]), record["kind"]
        require(oid not in ids and aid not in actor_ids, "duplicate object or actor binding")
        ids.add(oid); actor_ids.add(aid)
        require(isinstance(kind, str) and kind in KINDS and aid in actors, "unknown kind or actor binding")
        actor = actors[aid]
        require(type(actor.get("spawn_count", 1)) is int and actor.get("spawn_count", 1) == 1, "bound actor requires one spawn instance")
        bp = blueprints.get(aid)
        require(bp is not None and bp.is_active_in_mode(mode_id), "missing compiled actor blueprint")
        components = bp.component_defaults
        t = components.get(1, {})
        exact(t, {"position", "rotation", "scale", "parent_entity_id"})
        position = vector(t["position"])
        exact(t["rotation"], {"x", "y", "z", "w"})
        require(all(type(v) is int for v in t["rotation"].values()) and t["rotation"] == {"x": 0, "y": 0, "z": 0, "w": SCALE}, "rotated transforms unsupported")
        require(vector(t["scale"]) == {"x": SCALE, "y": SCALE, "z": SCALE}, "scaled transforms unsupported")
        require(type(t["parent_entity_id"]) is int and t["parent_entity_id"] == 0, "parented transforms unsupported")
        require(isinstance(components.get(2, {}).get("entity_name"), str) and bool(components[2]["entity_name"]), "world actor requires UCL identity")
        half = None
        if kind in {"static_box", "kinematic_box", "trigger"}:
            c = components.get(4, {})
            exact(c, {"shape", "size", "offset", "is_trigger"}, {"layer_mask", "physics_material_id"})
            require(type(c.get("layer_mask", 1)) is int and 0 <= c.get("layer_mask", 1) < 2**32, "invalid collider layer mask")
            require(c.get("layer_mask", 1) == 1, "non-default collision layers require world v3")
            require(c["shape"] == "BOX" and type(c["is_trigger"]) is bool and c["is_trigger"] == (kind == "trigger"), "unsupported collider shape/trigger role")
            size, offset = vector(c["size"], True), vector(c["offset"])
            require(all(v % 2 == 0 for v in size.values()), "box full size must have exact integer half extents")
            half = {k: v // 2 for k, v in size.items()}
            position = {k: position[k] + offset[k] for k in position}
            require(all(-LIMIT <= position[k] - half[k] and position[k] + half[k] <= LIMIT for k in position), "box bounds exceed profile")
        else:
            require(4 not in components, "point roles cannot silently ignore a collider")
        caps = record["capabilities"]
        require(isinstance(caps, list) and all(isinstance(c, str) for c in caps) and len(caps) == len(set(caps)), "malformed or duplicate capabilities")
        require(set(caps) <= declared.keys(), "undeclared semantic capability")
        require(all(kind in declared[c] for c in caps), "semantic declaration excludes object role")
        target = record.get("target_id")
        if target is not None:
            semantic_id(target)
        ref, requirement = record.get("asset_reference"), None
        if ref is not None:
            requirement = validate_reference(ref)
        objects.append({"id": oid, "actor_id": aid, "kind": kind, "position": position,
                        "half_extents": half, "capabilities": sorted(caps), "target_id": target,
                        "asset_requirement": requirement})
    require(all(o["target_id"] is None or o["target_id"] in ids for o in objects), "dangling world target binding")
    # A collider in this mode cannot disappear from the authoritative projection.
    require(all(a["id"] in actor_ids for a in actor_list if any(c["type_id"] == 4 for c in a.get("components", []))), "unbound authoritative collider")
    world = mode["world"]
    size = exact(world.get("size"), {"width", "height", "depth"})
    vector(dict(zip(("x", "y", "z"), (size["width"], size["height"], size["depth"]))), True)
    gravity = vector(world.get("gravity"))
    day = world.get("day_length_ticks", 0)
    require(type(day) is int and 0 <= day <= 2**64 - 1, "invalid day_length_ticks")
    content = {"schema": "xace.world_contract.v2", "contract_version": 2, "numeric_profile": PROFILE,
               "mode_id": mode_id, "size": size, "gravity": gravity, "day_length_ticks": day,
               "required_capabilities": ["world.aabb.v1", "world.semantic_bindings.v1"],
               "capability_declarations": [{"id": cid, "allowed_kinds": declared[cid]} for cid in sorted(declared)],
               "objects": sorted(objects, key=lambda o: o["id"])}
    encoded = canonical_bytes(content)
    identity = {"artifact": {"id": semantic_id(contract["id"]), "version": semantic_id(contract["version"]),
                             "content_hash": hashlib.sha256(encoded).hexdigest()}, "contract_version": 2,
                "compiled_from_cgs_hash": source_cgs["metadata"]["cgs_hash"], "mode_id": mode_id}
    manifest = {"schema": "xace.world_manifest.v1", "world": identity,
                "schema_package": {"cgs_hash": source_cgs["metadata"]["cgs_hash"],
                                   "schema_version": source_cgs["metadata"].get("schema_version", source_cgs["metadata"]["version"])}}
    return CompiledWorld(encoded, canonical_bytes(manifest))
