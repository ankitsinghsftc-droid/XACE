"""NEC-003 bounded native authoring proposals, not engine feedback or CGS writes.

Only a trusted reader can establish capture completeness/content fingerprints.
Admission verifies the supplied evidence, not the editor itself. Host-owned policy
and the NEC-002 identity map are mandatory out-of-band inputs on every load.
"""
from __future__ import annotations

import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from typing import Any

from authoring_identity import (IdentityError, IdentityMap, MAX_BYTES, MAX_OBJECTS,
                                canonical, digest, digest_id, exact, require, token)
from native_authoring_values import PROFILE, geometry, integer, normalize

SCHEMA = "xace.native_authoring_capture.v1"
SNAPSHOT_SCHEMA = "xace.native_authoring_snapshot.v1"
DELTA_SCHEMA = "xace.native_authoring_delta.v1"
MAX_EDGES = 40_000
MAX_DEPTH = 24
MAX_FIELDS = 64
_SURROGATES = re.compile(r"[\ud800-\udfff]")


def bounded(value: Any) -> None:
    """Reject ambiguous numbers, excessive nesting and oversized values before use."""
    pending = [(value, 0)]
    count = 0
    # Equal immutable strings have identical validity. Memoization is limited to
    # this traversal; every occurrence still counts toward depth/node limits.
    keys, texts = set(), set()
    while pending:
        item, depth = pending.pop()
        count += 1
        if depth > MAX_DEPTH or count > 1_000_000:
            raise IdentityError("authoring structure limit")
        kind = type(item)
        if kind is dict:
            for key in item:
                if type(key) is not str:
                    raise IdentityError("invalid JSON key")
                if key not in keys:
                    if len(key) > 256 or not key.isascii():
                        raise IdentityError("invalid JSON key")
                    keys.add(key)
            pending.extend((v, depth + 1) for v in item.values())
        elif kind is list:
            pending.extend((v, depth + 1) for v in item)
        elif kind is str:
            if item not in texts:
                if len(item) > 4096 or _SURROGATES.search(item) is not None:
                    raise IdentityError("oversized text or unpaired surrogate")
                texts.add(item)
        elif item is not None and kind is not bool:
            raise IdentityError("wire numbers must be decimal strings")
    canonical(value)  # Enforce the same 16 MiB bound in memory and on disk.


_validated_payloads = ContextVar('native_authoring_validated_payloads', default=None)


@contextmanager
def wire_validation_session():
    """Bounded call-local memo of structural JSON validation, never map/policy trust.

    Bytes are immutable; decoded objects are new on every parse. No capture,
    approval, schema or filesystem verification is memoized.
    """
    state = {'bytes': 0, 'payloads': set()}
    token = _validated_payloads.set(state)
    try:
        yield
    finally:
        _validated_payloads.reset(token)


def parse(data: bytes) -> dict:
    require(type(data) is bytes and len(data) <= MAX_BYTES, "authoring payload byte limit")

    state = _validated_payloads.get()
    cache_key = (MAX_DEPTH, MAX_BYTES, data)
    if state is not None and cache_key in state['payloads']:
        return json.loads(data.decode("utf-8"))

    def pairs(rows):
        result = {}
        for k, v in rows:
            require(k not in result, "duplicate JSON key")
            result[k] = v
        return result

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise IdentityError("malformed authoring JSON") from exc
    bounded(value)
    require(type(value) is dict, "expected authoring object")
    if state is not None and state['bytes'] + len(data) <= 32 * 1024 * 1024:
        state['payloads'].add(cache_key)
        state['bytes'] += len(data)
    return value


@dataclass(frozen=True)
class FieldPolicy:
    value_type: str
    owner: str = "canonical"
    read: bool = True
    write: bool = False
    conflict: str = "review"

    def validate(self):
        require(self.value_type in {"int64", "bool", "text", "asset", "binding", "position", "offset",
                                   "size", "scale", "normal", "rotation"}, "unknown field type")
        require(self.owner in {"canonical", "native"} and self.conflict == "review",
                "unsupported ownership/conflict rule")
        require(type(self.read) is bool and type(self.write) is bool, "invalid capability")
        require(not self.write or (self.read and self.owner == "canonical"),
                "native-owned or unreadable fields cannot be written by XACE")


@dataclass(frozen=True)
class AuthoringPolicy:
    engine: str
    engine_version: str
    reader_version: str
    materializer_version: str
    fields: dict[str, FieldPolicy]

    def description(self):
        require(self.engine in {"unity", "unreal", "godot"}, "unsupported engine")
        for version in (self.engine_version, self.reader_version, self.materializer_version):
            token(version, "pinned source version")
        require(type(self.fields) is dict and len(self.fields) <= MAX_FIELDS, "field policy limit")
        for path, field in self.fields.items():
            token(path, "fully qualified field path")
            require("." in path and isinstance(field, FieldPolicy), "invalid field policy")
            field.validate()
            standard = core_fields().get(path)
            require(standard is None or (field.value_type == standard.value_type
                                         and field.owner == standard.owner), "core field schema cannot be redefined")
        return dict(engine=self.engine, engine_version=self.engine_version,
                    reader_version=self.reader_version, materializer_version=self.materializer_version,
                    fields={k: asdict(v) for k, v in self.fields.items()}, numeric_profile=PROFILE)


def core_fields() -> dict[str, FieldPolicy]:
    """Schema vocabulary, not a claim an installed reader/writer supports these fields.

    Host integration must explicitly enable writes after certifying its materializer.
    Binding semantics stay named and typed; arbitrary controller graphs remain opaque.
    """
    types = {"transform.position": "position", "transform.rotation": "rotation",
             "transform.scale": "scale", "collision.size": "size", "collision.offset": "offset",
             "collision.shape": "text", "collision.profile": "text", "collision.trigger": "bool",
             "presentation.asset": "asset", "binding.playback": "binding",
             "input.action": "text", "animation.state": "text"}
    return {k: FieldPolicy(v) for k, v in types.items()}


@dataclass(frozen=True)
class Snapshot:
    """Canonical immutable bytes; all consumers must reload with map/policy validation."""
    payload: bytes

    @property
    def sha256(self):
        import hashlib
        return hashlib.sha256(self.payload).hexdigest()

    def to_dict(self):
        return parse(self.payload)


@dataclass(frozen=True)
class Inspection:
    payload: bytes

    @property
    def losses(self):
        return parse(self.payload)["losses"]

    @property
    def loss_digest(self):
        # Bind acknowledgement to the complete capture, not a reusable warning string.
        return digest(parse(self.payload))

    def admit(self, accepted_loss_digest: str | None = None) -> Snapshot:
        inspection = parse(self.payload)
        losses = inspection["losses"]
        if accepted_loss_digest is not None:
            digest_id(accepted_loss_digest)
        require(not any(r["severity"] == "blocking" for r in losses), "snapshot has blocking losses")
        if any(r["severity"] == "review" for r in losses):
            require(accepted_loss_digest == digest(inspection), "precision loss requires bound review")
        else:
            require(accepted_loss_digest is None, "unexpected loss acknowledgement")
        envelope = {"schema": SNAPSHOT_SCHEMA, "inspection": inspection,
                    "accepted_loss_digest": accepted_loss_digest}
        bounded(envelope)
        return Snapshot(canonical(envelope))


def inspect_capture(capture: dict, mapping: IdentityMap, policy: AuthoringPolicy) -> Inspection:
    """Pure inspection. Malformed framing rejects; semantic loss is itemized.

    No caller input is changed, no baseline advances, and no project files are opened.
    Scope is explicit and closed; absence is never interpreted as native deletion.
    """
    bounded(capture)
    mapping.validate()
    policy_description = policy.description()
    exact(capture, {"schema", "project_id", "namespace_id", "branch_id", "mapping_digest", "source", "scope", "objects"})
    require(capture["schema"] == SCHEMA, "unsupported capture schema")
    require(capture["project_id"] == mapping.project_id and capture["namespace_id"] == mapping.namespace_id
            and capture["branch_id"] == mapping.branch_id
            and capture["mapping_digest"] == mapping.mapping_digest(), "stale/foreign identity map")
    require(policy.engine == mapping.engine, "policy engine mismatch")
    source = capture["source"]
    exact(source, {"engine", "engine_version", "reader_version", "materializer_version", "documents", "play_mode"})
    for k in ("engine", "engine_version", "reader_version", "materializer_version"):
        require(source[k] == policy_description[k], "unsupported source version: " + k)
    require(type(source["play_mode"]) is bool, "invalid editor state")
    scope = capture["scope"]
    require(type(scope) is list and 0 < len(scope) <= MAX_OBJECTS and all(type(k) is str for k in scope),
            "invalid scope")
    require(scope == sorted(set(scope)) and all(k in mapping.objects and not mapping.objects[k].tombstone
                                               for k in scope), "ambiguous/unregistered scope")
    rows = capture["objects"]
    require(type(rows) is dict and set(rows) == set(scope), "incomplete capture; missing is not deletion")
    for row in rows.values():
        exact(row, {"generation", "deleted", "parent_id", "fields", "dependencies", "opaque"})
        require(type(row["deleted"]) is bool, "invalid deletion marker")
    documents = source["documents"]
    require(type(documents) is list and len(documents) <= MAX_OBJECTS, "invalid document inventory")
    doc_ids = []
    losses = []

    def loss(code, object_id="", field="", severity="blocking", detail=""):
        require(len(losses) < MAX_EDGES, "loss report limit")
        losses.append(dict(code=code, object_id=object_id, field=field, severity=severity, detail=detail))

    for document in documents:
        exact(document, {"id", "before", "after", "dirty"})
        token(document["id"], "persistent document key")
        digest_id(document["before"])
        digest_id(document["after"])
        require(type(document["dirty"]) is bool, "invalid dirty flag")
        doc_ids.append(document["id"])
        if document["dirty"] or document["before"] != document["after"]:
            loss("unstable_document", field=document["id"])
    require(doc_ids == sorted(set(doc_ids)) and set(doc_ids) ==
            {mapping.objects[k].locator.document_id for k in scope}, "document scope mismatch")
    if source["play_mode"]:
        loss("play_mode_capture")
    normalized = {}
    parents = {}
    edge_count = 0
    geometry_count = 0
    for key in scope:
        row = rows[key]
        record = mapping.objects[key]
        exact(row, {"generation", "deleted", "parent_id", "fields", "dependencies", "opaque"})
        require(integer(row["generation"]) == record.generation, "stale object generation")
        require(type(row["deleted"]) is bool, "invalid deletion marker")
        parent = row["parent_id"]
        require(parent is None or (type(parent) is str and parent in rows and parent != key),
                "parent outside declared scope")
        fields = row["fields"]
        require(type(fields) is dict and len(fields) <= MAX_FIELDS, "field count limit")
        edges = row["dependencies"]
        opaque = row["opaque"]
        require(type(edges) is list and type(opaque) is list, "invalid dependency inventory")
        edge_count += len(edges) + len(opaque)
        require(edge_count <= MAX_EDGES, "dependency limit")
        if row["deleted"]:
            require(parent is None and not fields and not edges and not opaque, "deleted object has content")
        else:
            # Scene/prefab edges are required implicitly by identity; cannot disappear in a delta.
            for reference in (record.scene_id, record.prefab_id, parent):
                require(reference is None or (reference in rows and not rows[reference].get("deleted", True)),
                        "dependency closure missing/live object depends on deleted object")
            if parent:
                require(mapping.objects[parent].scene_id == record.scene_id, "parent crosses scene boundary")
            require(record.kind not in {"scene", "prefab_definition"} or parent is None,
                    "definition cannot be parented")
        parents[key] = parent
        out = {}
        for path, value in sorted(fields.items()):
            rule = policy.fields.get(path)
            if rule is None or not rule.read:
                loss("field_not_readable", key, path)
                continue
            try:
                out[path], axes = normalize(mapping.engine, rule.value_type, value)
                if axes:
                    loss("fixed_point_rounding", key, path, "review", ",".join(axes))
            except (ValueError, TypeError) as exc:
                loss("invalid_value", key, path, detail=str(exc)[:1024])
        if any(path.startswith("collision.") for path in fields):
            geometry_count += 1
            try:
                geometry(out, parent)
            except ValueError as exc:
                loss("unsupported_geometry", key, "collision", detail=str(exc))
        seen_edges = set()
        for edge in edges:
            exact(edge, {"target", "kind"})
            require(type(edge["kind"]) is str and edge["kind"] in {"resource", "binding", "behavior"}
                    and type(edge["target"]) is str,
                    "invalid dependency edge")
            pair = (edge["kind"], edge["target"])
            require(pair not in seen_edges, "duplicate dependency edge")
            seen_edges.add(pair)
            require(edge["target"] in rows and not rows[edge["target"]].get("deleted", True),
                    "dependency outside live scope")
        opaque_ids = set()
        for item in opaque:
            exact(item, {"id", "sha256", "critical", "reason"})
            token(item["id"], "opaque content id")
            token(item["reason"], "opaque disposition", 1024)
            digest_id(item["sha256"])
            require(type(item["critical"]) is bool and item["id"] not in opaque_ids,
                    "invalid/duplicate opaque content")
            opaque_ids.add(item["id"])
            loss("retained_native", key, item["id"], "blocking" if item["critical"] else "info", item["reason"])
        normalized[key] = dict(generation=row["generation"], deleted=row["deleted"], parent_id=parent,
                               fields=out, dependencies=sorted(edges, key=lambda e: (e["kind"], e["target"])),
                               opaque=sorted(opaque, key=lambda e: e["id"]))
    require(geometry_count <= 4096, "frozen geometry body limit")
    # Iterative forest validation avoids stack overflow on deep native hierarchies.
    done = set()
    for key in scope:
        path = set()
        cursor = key
        while cursor is not None and cursor not in done:
            require(cursor not in path, "cyclic hierarchy")
            path.add(cursor)
            cursor = parents[cursor]
        done.update(path)
    envelope = dict(schema="xace.native_authoring_inspection.v1", loss_report_schema="xace.native_authoring_loss_report.v1",
                    capture=capture, policy_digest=digest(policy_description), numeric_profile=PROFILE,
                    normalized=normalized, losses=sorted(losses, key=lambda r: canonical(r)))
    bounded(envelope)
    return Inspection(canonical(envelope))


def load_snapshot(data: bytes, mapping: IdentityMap, policy: AuthoringPolicy) -> Snapshot:
    envelope = parse(data)
    exact(envelope, {"schema", "inspection", "accepted_loss_digest"})
    require(envelope["schema"] == SNAPSHOT_SCHEMA, "unsupported snapshot schema")
    inspection = envelope["inspection"]
    exact(inspection, {"schema", "loss_report_schema", "capture", "policy_digest", "numeric_profile", "normalized", "losses"})
    verified = inspect_capture(inspection["capture"], mapping, policy)
    require(verified.payload == canonical(inspection), "snapshot policy/normalization/loss evidence mismatch")
    result = verified.admit(envelope["accepted_loss_digest"])
    require(result.payload == data, "snapshot must use canonical JSON bytes")
    return result


def make_delta(base: Snapshot, target: Snapshot, mapping: IdentityMap, policy: AuthoringPolicy) -> bytes:
    """Two-snapshot, hash-guarded transport delta; no B/X/E reconciliation."""
    before = load_snapshot(base.payload, mapping, policy).to_dict()["inspection"]["capture"]
    after = load_snapshot(target.payload, mapping, policy).to_dict()["inspection"]["capture"]
    require(before["scope"] == after["scope"], "scope change requires a full snapshot")
    changes = {k: dict(before=digest(before["objects"][k]), after=after["objects"][k])
               for k in after["scope"] if before["objects"][k] != after["objects"][k]}
    envelope = dict(schema=DELTA_SCHEMA, base_digest=base.sha256, target_digest=target.sha256,
                    header={k: v for k, v in after.items() if k != "objects"}, changes=changes,
                    accepted_loss_digest=target.to_dict()["accepted_loss_digest"])
    bounded(envelope)
    return canonical(envelope)


def apply_delta(base: Snapshot, data: bytes, mapping: IdentityMap, policy: AuthoringPolicy) -> Snapshot:
    before = load_snapshot(base.payload, mapping, policy).to_dict()["inspection"]["capture"]
    delta = parse(data)
    exact(delta, {"schema", "base_digest", "target_digest", "header", "changes", "accepted_loss_digest"})
    require(delta["schema"] == DELTA_SCHEMA and delta["base_digest"] == base.sha256, "stale delta")
    digest_id(delta["target_digest"])
    header = delta["header"]
    exact(header, set(before) - {"objects"})
    require(header["scope"] == before["scope"], "delta scope changed")
    changes = delta["changes"]
    require(type(changes) is dict and set(changes) <= set(before["objects"]), "unknown delta objects")
    for key, change in changes.items():
        exact(change, {"before", "after"})
        require(change["before"] == digest(before["objects"][key]), "stale object precondition")
        before["objects"][key] = change["after"]
    capture = dict(header, objects=before["objects"])
    target = inspect_capture(capture, mapping, policy).admit(delta["accepted_loss_digest"])
    require(target.sha256 == delta["target_digest"], "delta target digest mismatch")
    return target


def writable_fields_batch(snapshot: Snapshot, selections: dict[str, list[str]],
                          mapping: IdentityMap, policy: AuthoringPolicy) -> dict:
    """Validate one immutable snapshot per call, then every selected write field.

    Returns proposals only; approval, fresh capture and publication CAS are unchanged.
    No verified snapshot is cached across calls or exposed as a trusted input.
    """
    require(type(selections) is dict, "invalid write selections")
    verified = load_snapshot(snapshot.payload, mapping, policy).to_dict()
    rows = verified["inspection"]["normalized"]
    result = {}
    for object_id, fields in selections.items():
        require(object_id in rows and not rows[object_id]["deleted"], "unknown/deleted write target")
        require(type(fields) is list and all(type(k) is str for k in fields)
                and len(fields) == len(set(fields)), "invalid write field selection")
        for path in fields:
            rule = policy.fields.get(path)
            require(rule is not None and rule.write and path in rows[object_id]["fields"],
                    "field is not allowlisted for native write")
        result[object_id] = {k: rows[object_id]["fields"][k] for k in sorted(fields)}
    return result


def writable_fields(snapshot: Snapshot, object_id: str, fields: list[str],
                    mapping: IdentityMap, policy: AuthoringPolicy) -> dict:
    """Return an allowlisted proposal, never a native write authorization."""
    return writable_fields_batch(snapshot, {object_id: fields}, mapping, policy)[object_id]
