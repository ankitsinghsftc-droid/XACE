"""Generic semantic world envelope. Geometry profiles are separate consumers.

Project schema declarations are immutable package data, never executable code.
The small portable schema language is versioned with this contract; project nouns
and properties are not an engine enum. Unknown required backends fail admission.
"""
from __future__ import annotations
import copy
import hashlib
import re
import json
from pathlib import Path
from .world_contract import (CompiledWorld, canonical_bytes, require, exact, semantic_id,
                             vector, SCALE, ASSET_TYPES)

PROFILE_REGISTRY = json.loads((Path(__file__).resolve().parents[2] / "core/src/world/profiles.json").read_text(encoding="utf8"))
PROFILE = PROFILE_REGISTRY["profiles"]["aabb_v1"]["id"]
VERSIONED = r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+\.v[1-9][0-9]*"

def versioned(value):
    semantic_id(value)
    require(re.fullmatch(VERSIONED, value) is not None, "expected namespaced versioned schema ID")
    return value

def schema_check(schema, value=None, *, declaration=False, depth=0):
    require(depth <= 16, "extension schema nesting exceeds limit")
    require(isinstance(schema, dict), "extension schema must be an object")
    kind = schema.get("type")
    if kind == "object":
        exact(schema, {"type", "fields"})
        require(isinstance(schema["fields"], dict) and len(schema["fields"]) <= 256, "invalid schema fields")
        for key, child in schema["fields"].items():
            semantic_id(key)
            schema_check(child, declaration=True, depth=depth+1)
        if not declaration:
            exact(value, set(schema["fields"]))
            for key, child in schema["fields"].items():
                schema_check(child, value[key], depth=depth+1)
    elif kind == "array":
        exact(schema, {"type", "items"})
        schema_check(schema["items"], declaration=True, depth=depth+1)
        if not declaration:
            require(isinstance(value, list) and len(value) <= 4096, "invalid extension array")
            for item in value: schema_check(schema["items"], item, depth=depth+1)
    else:
        exact(schema, {"type"})
        require(kind in {"integer", "boolean", "string"}, "unknown portable extension field type")
        if not declaration:
            ok = ((kind == "integer" and type(value) is int and -(2**63) <= value < 2**63) or
                  (kind == "boolean" and type(value) is bool) or
                  (kind == "string" and isinstance(value, str) and len(value.encode("utf8")) <= 16384))
            require(ok, "extension value differs from declared field type")

def index(records, label):
    require(isinstance(records, list) and len(records) <= 4096, "invalid " + label + " count")
    result = {}
    for record in records:
        require(isinstance(record, dict), "invalid " + label)
        key = semantic_id(record.get("id"))
        require(key not in result, "duplicate " + label)
        result[key] = record
    return result

def compile_world_v3(mode, contract, blueprints, source):
    exact(contract, {"contract_version", "id", "version", "schemas", "capability_declarations", "objects", "geometry_profiles"})
    schemas = index(contract["schemas"], "schemas")
    for sid, schema in schemas.items():
        versioned(sid); exact(schema, {"id", "definition"})
        schema_check(schema["definition"], declaration=True)
    caps = index(contract["capability_declarations"], "capabilities")
    for cid, cap in caps.items():
        versioned(cid); exact(cap, {"id", "allowed_types"})
        require(cid not in {"input.timed.v1", "world.aabb.v1", "world.semantic_bindings.v1", "world.semantic_bindings.v3"}, "reserved platform capability")
        require(isinstance(cap["allowed_types"], list) and len(set(cap["allowed_types"])) == len(cap["allowed_types"])
                and set(cap["allowed_types"]) <= set(schemas), "invalid capability semantic types")
        cap["allowed_types"] = sorted(cap["allowed_types"])
    profiles = index(contract["geometry_profiles"], "geometry profiles")
    for pid, profile in profiles.items():
        versioned(pid); exact(profile, {"id", "required"})
        require(type(profile["required"]) is bool, "profile requirement must be boolean")
        # Compilation never certifies an unavailable authoritative backend.
        require(pid == PROFILE, "unsupported geometry profile")
    actors = index(mode.get("actors", []), "actors")
    assets = index(source.get("assets", []), "assets")
    objects = index(contract["objects"], "world objects")
    result = []
    geometry_bindings = set()
    def payload(sid, data):
        require(sid in schemas, "unregistered semantic schema")
        schema_check(schemas[sid]["definition"], data)
    for oid, obj in objects.items():
        exact(obj, {"id", "actor_id", "instance_index", "semantic_type", "properties", "capabilities", "relationships", "asset_bindings", "geometry_profile"})
        aid = semantic_id(obj["actor_id"]); require(aid in actors, "unknown actor binding")
        instance = obj["instance_index"]
        count = actors[aid].get("spawn_count", 1)
        require(type(count) is int and type(instance) is int and 0 <= instance < count <= 4096, "invalid spawn instance binding")
        payload(obj["semantic_type"], obj["properties"])
        require(isinstance(obj["capabilities"], list) and len(set(obj["capabilities"])) == len(obj["capabilities"]), "invalid capabilities")
        for cid in obj["capabilities"]:
            require(cid in caps and (not caps[cid]["allowed_types"] or obj["semantic_type"] in caps[cid]["allowed_types"]), "undeclared or incompatible capability")
        require(isinstance(obj["relationships"], dict), "relationships must be role-keyed")
        for role, targets in obj["relationships"].items():
            versioned(role)
            require(isinstance(targets, list) and len(set(targets)) == len(targets) and set(targets) <= set(objects), "dangling or duplicate relationship")
        require(isinstance(obj["asset_bindings"], dict), "assets must be role-keyed typed references")
        bindings = {}
        for role, ref in obj["asset_bindings"].items():
            versioned(role); exact(ref, {"id", "asset_type", "status"})
            registered = assets.get(semantic_id(ref["id"]))
            require(registered is not None and ref["status"] in {"PLACEHOLDER", "LINKED", "MISSING"}
                    and all(registered.get(k) == ref[k] for k in ("asset_type", "status")), "unresolved or mismatched asset binding")
            category = ref["asset_type"]
            require(category in ASSET_TYPES or category in schemas, "unregistered asset category")
            bindings[role] = {"id": ref["id"], "asset_type": category}
        bp = blueprints.get(aid)
        require(bp is not None and bp.is_active_in_mode(mode["id"]), "missing compiled actor blueprint")
        t = copy.deepcopy(bp.component_defaults.get(1))
        exact(t, {"position", "rotation", "scale", "parent_entity_id"})
        for name in ("position", "scale"):
            exact(t[name], {"x", "y", "z"})
            require(all(type(v) is int and -(2**63) <= v < 2**63 for v in t[name].values()), "transform must use Fixed64")
        exact(t["rotation"], {"x", "y", "z", "w"})
        require(all(type(v) is int and -(2**63) <= v < 2**63 for v in t["rotation"].values()) and any(t["rotation"].values()), "invalid rotation")
        require(all(v != 0 for v in t["scale"].values()) and type(t["parent_entity_id"]) is int and 0 <= t["parent_entity_id"] < 2**64, "invalid transform")
        profile = obj["geometry_profile"]
        geometry = None
        if profile is not None:
            require(profile in profiles and profiles[profile]["required"], "authoritative geometry must declare a required profile")
            require((aid, instance) not in geometry_bindings, "duplicate geometry instance binding")
            geometry_bindings.add((aid, instance))
            require(t["rotation"] == {"x": 0, "y": 0, "z": 0, "w": SCALE} and t["scale"] == {"x": SCALE, "y": SCALE, "z": SCALE} and t["parent_entity_id"] == 0, "AABB profile requires unparented identity rotation/scale")
            c = bp.component_defaults.get(4, {})
            exact(c, {"shape", "size", "offset", "is_trigger"}, {"layer_mask", "physics_material_id"})
            require(c["shape"] == "BOX" and type(c["is_trigger"]) is bool, "AABB profile requires BOX")
            size, offset, position = vector(c["size"], True), vector(c["offset"]), vector(t["position"])
            require(all(v % 2 == 0 for v in size.values()), "AABB half extents must be exact")
            from .world_contract import LIMIT
            require(all(size[k] <= LIMIT and -LIMIT <= position[k]+offset[k]-size[k]//2 and position[k]+offset[k]+size[k]//2 <= LIMIT for k in size), "AABB bounds exceeded")
            layer = c.get("layer_mask", 1)
            require(type(layer) is int and 0 <= layer < 2**32, "invalid collider layer mask")
            geometry = {"profile": profile, "size": size, "offset": offset, "is_trigger": c["is_trigger"], "layer_mask": layer}
        out = copy.deepcopy(obj)
        out.pop("geometry_profile")
        out.update(transform=t, geometry=geometry, asset_bindings=bindings,
                   capabilities=sorted(obj["capabilities"]), relationships={k: sorted(v) for k,v in obj["relationships"].items()})
        result.append(out)
    content = {"schema": "xace.world_contract.v3", "contract_version": 3, "mode_id": semantic_id(mode["id"]),
               "schemas": [schemas[k] for k in sorted(schemas)], "geometry_profiles": [profiles[k] for k in sorted(profiles)],
               "capability_declarations": [caps[k] for k in sorted(caps)], "objects": sorted(result, key=lambda o:o["id"])}
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf8")
    require(len(encoded) <= 16*1024*1024, "world artifact exceeds 16 MiB")
    identity = {"artifact": {"id": semantic_id(contract["id"]), "version": semantic_id(contract["version"]), "content_hash": hashlib.sha256(encoded).hexdigest()},
                "contract_version": 3, "compiled_from_cgs_hash": source["metadata"]["cgs_hash"], "mode_id": mode["id"]}
    return CompiledWorld(encoded, canonical_bytes({"schema": "xace.world_manifest.v1", "world": identity,
        "schema_package": {"cgs_hash": source["metadata"]["cgs_hash"], "schema_version": source["metadata"].get("schema_version", source["metadata"]["version"])}}))

def migrate_v2_source(contract):
    """Explicit detached source migration; caller must rehash/recompile CGS.

    Legacy artifact bytes and session identity are never silently reinterpreted.
    Geometry roles become ordinary schema declarations in the migrated package.
    """
    from .world_contract import KINDS
    require(contract.get("contract_version") == 2, "migration requires legacy v2 source")
    def sid(kind):
        require(kind in KINDS, "unknown legacy role")
        return "xace.legacy_" + kind + ".v1"
    schemas = [{"id":sid(k),"definition":{"type":"object","fields":{}}} for k in sorted(KINDS)]
    objects = []
    for old in contract["objects"]:
        objects.append({"id":old["id"], "actor_id":old["actor_id"], "instance_index":0,
            "semantic_type":sid(old["kind"]),"properties":{},"capabilities":copy.deepcopy(old["capabilities"]),
            "relationships":{"xace.legacy_target.v1":[old["target_id"]]} if old.get("target_id") else {},
            "asset_bindings":{"xace.legacy_asset.v1":copy.deepcopy(old["asset_reference"])} if old.get("asset_reference") else {},
            "geometry_profile":PROFILE if old["kind"] in {"static_box","kinematic_box","trigger"} else None})
    return {"contract_version":3,"id":contract["id"],"version":contract["version"],"schemas":schemas,
        "geometry_profiles":[{"id":PROFILE,"required":True}],"objects":objects,
        "capability_declarations":[{"id":c["id"],"allowed_types":sorted(sid(k) for k in c["allowed_kinds"])} for c in contract["capability_declarations"]]}
