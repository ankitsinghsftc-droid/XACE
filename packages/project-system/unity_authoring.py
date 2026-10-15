"""NEC-004 Unity inventory -> NEC-002/003 bridge; no editor launch or CGS writes.

The caller must explicitly trust the open Unity project before executing its editor
integration. Read-only discovery of an untrusted project remains file inventory;
this module never opens Unity or executes imported MonoBehaviours.
"""
from __future__ import annotations

from authoring_identity import (IdentityMap, NativeLocator, ObjectRecord, associate,
                                canonical, digest, exact, require, token)
from native_authoring_contract import (SCHEMA, AuthoringPolicy, FieldPolicy, Snapshot,
    core_fields, inspect_capture, load_snapshot, parse, writable_fields)
from native_authoring_values import integer

ENGINE_VERSION = "6000.4.9f1"
READER_VERSION = "unity.authoring.reader.v1"
WRITER_VERSION = "unity.authoring.writer.v1"
WRITABLE = frozenset({"transform.position", "transform.rotation", "transform.scale",
                      "collision.size", "collision.offset", "collision.trigger",
                      "input.action", "binding.playback"})


def policy(*, enable_writes: bool = False) -> AuthoringPolicy:
    fields = {k: FieldPolicy(v.value_type, write=enable_writes and k in WRITABLE)
              for k, v in core_fields().items() if k != "animation.state"}
    fields.update({"native.name": FieldPolicy("text", owner="native"),
                   "presentation.material": FieldPolicy("asset")})
    return AuthoringPolicy("unity", ENGINE_VERSION, READER_VERSION, WRITER_VERSION, fields)


def inventory(data: bytes) -> dict:
    result = parse(data)
    exact(result, {"schema", "namespace_id", "source", "objects"})
    require(result["schema"] == "xace.unity_authoring_inventory.v1", "Unity inventory version")
    rows = result["objects"]
    require(type(rows) is dict and 0 < len(rows) <= 10000, "Unity object inventory limit")
    for key, row in rows.items():
        exact(row, {"metadata", "locator", "scene_id", "prefab_id", "parent_id", "fields",
                    "dependencies", "opaque", "name", "path_hint"})
        metadata = row["metadata"]
        exact(metadata, {"schema", "namespace_id", "authoring_id", "kind", "generation"})
        require(metadata["schema"] == "xace.native_identity.v1" and metadata["authoring_id"] == key
                and metadata["namespace_id"] == result["namespace_id"], "Foreign/misbound metadata")
        require(integer(metadata["generation"]) > 0, "Invalid generation")
        exact(row["locator"], {"engine", "document_id", "object_id"})
        token(row["name"], "native name", 1024)
        path = row["path_hint"]
        require(type(path) is str and path.startswith("Assets/") and "\\" not in path
                and all(p not in {"", ".", ".."} for p in path.split("/")), "Invalid native document path")
    return result


def prepare_identity_map(data: bytes, *, project_id: str, branch_id: str) -> IdentityMap:
    """Explicit first-adoption candidate from already attached native IDs, never persisted.

    Do not use this to replace a current map or to repair collisions. Subsequent
    observations must use capture(data, current_mapping), which calls associate.
    """
    observed = inventory(data)
    mapping = IdentityMap(project_id, observed["namespace_id"], branch_id, "unity")
    for key, row in observed["objects"].items():
        metadata = row["metadata"]
        mapping.objects[key] = ObjectRecord(key, metadata["kind"], NativeLocator(**row["locator"]),
            scene_id=row["scene_id"], prefab_id=row["prefab_id"], parent_id=row["parent_id"],
            display_name=row["name"], path_hint=row["path_hint"], generation=integer(metadata["generation"]),
            provenance="unity.authoring.reader.v1:explicit-native-metadata")
    mapping.validate()
    # Also validate framing, pinned versions, scope closure and declared field values.
    capture(data, mapping)
    return mapping


def capture(data: bytes, mapping: IdentityMap, *, enable_writes: bool = False):
    observed = inventory(data)
    associations = []
    for row in observed["objects"].values():
        metadata = dict(row["metadata"], generation=integer(row["metadata"]["generation"]))
        associations.append((NativeLocator(**row["locator"]), metadata))
    associate(mapping, associations)
    rows = {key: dict(generation=row["metadata"]["generation"], deleted=False, parent_id=row["parent_id"],
                     fields=row["fields"], dependencies=row["dependencies"], opaque=row["opaque"])
            for key, row in observed["objects"].items()}
    envelope = dict(schema=SCHEMA, project_id=mapping.project_id, namespace_id=mapping.namespace_id,
                    branch_id=mapping.branch_id, mapping_digest=mapping.mapping_digest(),
                    source=observed["source"], scope=sorted(rows), objects=rows)
    return inspect_capture(envelope, mapping, policy(enable_writes=enable_writes))


def write_request(native_inventory: bytes, base: Snapshot, target: Snapshot, mapping: IdentityMap) -> bytes:
    """Concrete allowlisted writer input; later coordinator supplies reviewed approval.

    Targets must already be valid NEC-003 snapshots with this certified write policy.
    No structural edits, native-owned changes, resource fabrication or inferred deletion.
    """
    configured = policy(enable_writes=True)
    observed = inventory(native_inventory)
    loaded = load_snapshot(base.payload, mapping, configured)
    inspected = capture(native_inventory, mapping, enable_writes=True)
    receipt = loaded.to_dict()
    require(inspected.admit(receipt["accepted_loss_digest"]) == loaded, "Native inventory/base mismatch")
    after = load_snapshot(target.payload, mapping, configured).to_dict()["inspection"]["normalized"]
    before = receipt["inspection"]["normalized"]
    require(set(before) == set(after), "Structural adoption requires later GDE/coordinator workflow")
    edits = []
    for key in sorted(before):
        old, new = before[key], after[key]
        require({k:v for k,v in old.items() if k != "fields"} ==
                {k:v for k,v in new.items() if k != "fields"}, "Structural/opaque changes cannot use field writer")
        require(set(old["fields"]) == set(new["fields"]), "Adding/removing native components is not a field write")
        changed = [k for k in new["fields"] if new["fields"][k] != old["fields"][k]]
        if changed:
            edits.append(dict(document=observed["objects"][key]["path_hint"], authoring_id=key,
                              fields=writable_fields(target,key,changed,mapping,configured)))
    require(bool(edits), "No native write changes")
    return canonical(dict(schema="xace.unity_authoring_write_request.v1",
                          expected_inventory_digest=digest(observed), edits=edits))
