"""NEC-007 opt-in structural GDE preview grammar. No persistence/activation.

The existing prompt grammar is unchanged. The host explicitly selects this
extension and supplies final Factory validation; every operation runs on a copy.
"""
from __future__ import annotations
import copy
import hashlib
import json
import re
from dataclasses import dataclass
from .typed_operation_executor import TypedOperationExecutor, TypedOperationExecutionError

SCHEMA = "xace.native_adoption_operations.v1"
PARENT_ROLE = "xace.authoring_parent.v1"
# Up to four materialization operations per1,000 native instances plus declarations.
# The independent16MiB batch bound and all atomic validation remain unchanged.
MAX_ADOPTION_OPERATIONS = 4096


def encode(value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()
    require(len(data) <= 16 * 1024**2, "adoption size limit")
    return data


def digest(value): return hashlib.sha256(encode(value)).hexdigest()


def require(ok, message):
    if not ok: raise TypedOperationExecutionError(message)


def exact(value, keys):
    require(type(value) is dict and set(value) == set(keys), "missing/unknown adoption fields")


def identifier(value):
    require(type(value) is str and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,127}", value), "invalid adoption ID")
    return value


def index(rows, key="id"):
    require(type(rows) is list and all(type(r) is dict and key in r for r in rows), "invalid record list")
    result = {r[key]: r for r in rows}
    require(len(result) == len(rows), "duplicate record ID")
    return result


def insert(rows, record, key="id"):
    records = index(rows, key); rid = identifier(record[key])
    require(rid not in records, "create collides with existing record")
    rows.append(copy.deepcopy(record)); rows.sort(key=lambda r: r[key])


@dataclass(frozen=True)
class AdoptionOperationResult:
    proposed_cgs: dict
    batch_digest: str
    changed: bool


class NativeAdoptionExecutor:
    def __init__(self, *, validate, gameplay_catalog=None):
        require(callable(validate), "host Factory validator required")
        self.validate = validate
        self.legacy = TypedOperationExecutor(gameplay_catalog)

    def execute(self, batch, current):
        exact(batch, {"schema", "expected_cgs_digest", "operations"})
        require(batch["schema"] == SCHEMA and batch["expected_cgs_digest"] == digest(current), "stale adoption CGS")
        ops = batch["operations"]
        require(type(ops) is list and len(ops) <= MAX_ADOPTION_OPERATIONS, "adoption operation limit")
        encode(batch); proposed = copy.deepcopy(current); ids = set()
        for op in ops:
            require(type(op) is dict, "invalid operation")
            oid = identifier(op.get("operation_id")); require(oid not in ids, "duplicate operation ID"); ids.add(oid)
            kind = op.get("kind")
            if kind == "legacy":
                exact(op, {"operation_id", "kind", "operation"})
                # Reuse the existing trust boundary, never monkey-patch its closed grammar.
                raw = copy.deepcopy(op["operation"])
                require(raw.get("kind") in {"install_gameplay_package", "add_component", "add_system", "add_asset", "add_event", "set_defaults"}, "unsupported adoption legacy operation")
                proposed = self.legacy.execute(dict(schema="xace.typed_cgs_operation_batch.v1", request_id="nec.adoption", prompt_id="nec.adoption", summary="Reviewed native adoption", operations=[raw]), proposed).proposed_cgs
                continue
            if kind in {"set_playback_binding", "remove_playback_binding"}:
                fields = {"operation_id", "kind", "binding_id", "expected_digest"}
                exact(op, fields | ({"binding"} if kind == "set_playback_binding" else set()))
                bindings = proposed.setdefault("semantic_bindings", {}).setdefault("bindings", [])
                records = index(bindings, "binding_id"); bid = identifier(op["binding_id"])
                require(op["expected_digest"] == (digest(records[bid]) if bid in records else None), "stale playback binding")
                if kind == "remove_playback_binding": require(bid in records, "missing playback binding"); del records[bid]
                else:
                    binding = op["binding"]
                    exact(binding, {"binding_id", "event_name", "playback_kind", "asset", "semantic_action", "entity_selector", "parameters", "enabled", "priority"})
                    require(binding["binding_id"] == bid, "binding identity mismatch")
                    identifier(binding["event_name"]); identifier(binding["semantic_action"])
                    require(binding["entity_selector"] in {"SourceEntity", "TargetEntity"}, "unsupported binding selector")
                    require(type(binding["enabled"]) is bool and type(binding["priority"]) is int and 0 <= binding["priority"] <= 65535, "invalid binding flags")
                    require(type(binding["parameters"]) is dict and all(type(k) is str and type(v) is str for k,v in binding["parameters"].items()), "binding parameters must be strings")
                    pairs = {"Animation": {"AnimationClip", "AnimationController"}, "Audio": {"AudioClip", "AudioMusic"}, "Vfx": {"Particle"}}
                    ref = binding["asset"]; exact(ref, {"id", "asset_type", "status"})
                    require(ref["asset_type"] in pairs.get(binding["playback_kind"], set()), "incompatible playback asset")
                    records[bid] = copy.deepcopy(binding)
                proposed["semantic_bindings"]["bindings"] = [records[k] for k in sorted(records)]
                continue
            if kind == "create_mode":
                exact(op, {"operation_id", "kind", "mode"})
                exact(op["mode"], {"id", "schema_version", "is_default", "actors", "systems", "rules", "world", "ui"})
                require(not op["mode"]["actors"] and not op["mode"]["systems"] and not op["mode"]["rules"], "new mode scaffold must be empty")
                insert(proposed.setdefault("modes", []), op["mode"]); continue
            require("mode_id" in op, "mode required")
            modes = index(proposed.get("modes", [])); require(op["mode_id"] in modes, "unknown mode")
            mode = modes[op["mode_id"]]
            if kind == "create_actor":
                exact(op, {"operation_id", "kind", "mode_id", "actor"})
                exact(op["actor"], {"id", "actor_type", "control_type", "spawn_count", "components"})
                require(type(op["actor"]["spawn_count"]) is int and op["actor"]["spawn_count"] == 1, "one authoring object per actor")
                index(op["actor"]["components"], "type_id")
                for component in op["actor"]["components"]: exact(component, {"type_id", "name", "defaults"})
                insert(mode["actors"], op["actor"])
            elif kind == "remove_actor":
                exact(op, {"operation_id", "kind", "mode_id", "actor_id", "expected_digest"})
                actors = index(mode["actors"]); require(op["actor_id"] in actors, "unknown actor")
                require(digest(actors[op["actor_id"]]) == op["expected_digest"], "stale actor removal")
                mode["actors"] = [r for r in mode["actors"] if r["id"] != op["actor_id"]]
            elif kind == "initialize_world":
                exact(op, {"operation_id", "kind", "mode_id", "contract"})
                require("contract" not in mode.setdefault("world", {}), "World already exists")
                require(op["contract"].get("contract_version") == 3 and not op["contract"].get("objects"), "empty v3 contract required")
                mode["world"]["contract"] = copy.deepcopy(op["contract"])
            elif kind in {"create_world_object", "remove_world_object", "reparent_world_object", "set_asset_binding"}:
                contract = mode.get("world", {}).get("contract", {})
                require(contract.get("contract_version") == 3, "World v3 required")
                objects = index(contract["objects"])
                if kind == "create_world_object":
                    exact(op, {"operation_id", "kind", "mode_id", "object"}); insert(contract["objects"], op["object"])
                else:
                    require(op.get("object_id") in objects, "unknown World object"); obj = objects[op["object_id"]]
                    require(op.get("expected_digest") == digest(obj), "stale World object")
                    if kind == "remove_world_object":
                        exact(op, {"operation_id", "kind", "mode_id", "object_id", "expected_digest"})
                        contract["objects"] = [r for r in contract["objects"] if r["id"] != op["object_id"]]
                    elif kind == "reparent_world_object":
                        exact(op, {"operation_id", "kind", "mode_id", "object_id", "expected_digest", "parent_id"})
                        parent = op["parent_id"]
                        require(parent is None or (parent in objects and parent != op["object_id"]), "invalid semantic parent")
                        if parent is None: obj["relationships"].pop(PARENT_ROLE, None)
                        else: obj["relationships"][PARENT_ROLE] = [parent]
                    else:
                        exact(op, {"operation_id", "kind", "mode_id", "object_id", "expected_digest", "role", "asset"})
                        identifier(op["role"])
                        if op["asset"] is None: obj["asset_bindings"].pop(op["role"], None)
                        else:
                            exact(op["asset"], {"id", "asset_type", "status"})
                            obj["asset_bindings"][op["role"]] = copy.deepcopy(op["asset"])
            else:
                raise TypedOperationExecutionError("unknown structural adoption operation")
        # Relationship validation is additional to World v3, which allows general graphs.
        for mode in proposed.get("modes", []):
            objects = index(mode.get("world", {}).get("contract", {}).get("objects", []))
            for oid in objects:
                seen = set(); cursor = oid
                while cursor is not None:
                    require(cursor in objects and cursor not in seen, "dangling/cyclic authoring parent")
                    seen.add(cursor); parents = objects[cursor].get("relationships", {}).get(PARENT_ROLE, [])
                    require(type(parents) is list and len(parents) <= 1, "ambiguous authoring parent")
                    cursor = parents[0] if parents else None
        events = {r["name"] for r in proposed.get("semantic_events", [])}
        assets = index(proposed.get("assets", []))
        for binding in proposed.get("semantic_bindings", {}).get("bindings", []):
            require(binding["event_name"] in events, "undeclared playback event")
            ref = binding["asset"]; registered = assets.get(ref["id"])
            require(registered is not None and ref["status"] in {"Linked", "Placeholder", "Missing"}
                    and ref["status"].upper() == registered["status"]
                    and ref["asset_type"] == "".join(part.title() for part in registered["asset_type"].split("_")), "unresolved playback asset")
        changed = proposed != current
        if changed:
            # Publication/version advancement is later; this is only an isolated proposal hash.
            from ...cgs.cgs_serializer import CGSSerializer
            hash_input = copy.deepcopy(proposed); hash_input["metadata"].pop("cgs_hash", None)
            proposed["metadata"]["cgs_hash"] = CGSSerializer.compute_hash(hash_input)
        try: self.validate(copy.deepcopy(proposed))
        except Exception as exc: raise TypedOperationExecutionError("Factory rejected adoption: " + str(exc)[:1024]) from exc
        return AdoptionOperationResult(proposed, digest(batch), changed)
