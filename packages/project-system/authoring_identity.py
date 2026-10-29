"""NEC-002 project metadata contracts, independent of CGS and runtime EntityID.

Native locators are opaque persistent keys supplied by a trusted editor reader.
Paths/names are hints only. This module never reads or writes an engine project.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

SCHEMA = "xace.authoring_identity.v2"
LEGACY_SCHEMA = "xace.authoring_identity.v1"
MAX_OBJECTS = 10_000
MAX_BYTES = 16 * 1024 * 1024
Engine = Literal["unity", "unreal", "godot"]
ObjectKind = Literal["scene", "prefab_definition", "prefab_instance", "object"]


class IdentityError(ValueError):
    """Invalid, ambiguous or stale authoring metadata; never repair by guessing."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise IdentityError(message)


_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f]")


def token(value: Any, label: str, maximum: int = 256) -> None:
    require(type(value) is str and 0 < len(value) <= maximum
            and _CONTROL_CHARACTERS.search(value) is None, f"invalid {label}")


def opaque_id(value: Any) -> None:
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{32}", value) is not None,
            "expected opaque 128-bit authoring identifier")


def digest_id(value: Any) -> None:
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
            "expected SHA-256 identity")


def new_id() -> str:
    """Allocate only for an explicit new authoring identity; never at runtime/load."""
    return uuid.uuid4().hex


def canonical(value: Any) -> bytes:
    try:
        data = json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError) as exc:
        raise IdentityError("invalid identity JSON") from exc
    require(len(data) <= MAX_BYTES, "identity metadata exceeds byte limit")
    return data


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def exact(value: Any, fields: set[str]) -> None:
    require(type(value) is dict and set(value) == fields, "unknown or missing metadata fields")


@dataclass(frozen=True)
class NativeLocator:
    engine: Engine
    document_id: str
    object_id: str

    def validate(self) -> None:
        require(type(self.engine) is str and self.engine in {"unity", "unreal", "godot"}, "unsupported native engine")
        token(self.document_id, "persistent document key")
        token(self.object_id, "persistent object key")


@dataclass(frozen=True)
class WorldBinding:
    world_object_id: str
    actor_id: str
    instance_index: int

    def validate(self) -> None:
        token(self.world_object_id, "World object")
        token(self.actor_id, "actor")
        require(type(self.instance_index) is int and 0 <= self.instance_index < 2**32,
                "invalid instance index")


@dataclass
class ObjectRecord:
    authoring_id: str
    kind: ObjectKind
    locator: NativeLocator
    scene_id: str | None = None
    prefab_id: str | None = None
    parent_id: str | None = None
    display_name: str = ""
    path_hint: str = ""
    world_binding: WorldBinding | None = None
    generation: int = 1
    tombstone: bool = False
    duplicate_of: str | None = None
    provenance: str = ""


@dataclass(frozen=True)
class Baseline:
    """References to NEC-003 snapshots, not a claim that they were reconciled."""
    cgs_digest: str
    native_snapshot_digest: str
    mapping_digest: str
    journal_ref: str
    canonical_receipt: str
    native_receipt: str

    def validate(self) -> None:
        for value in (self.cgs_digest, self.native_snapshot_digest, self.mapping_digest,
                      self.canonical_receipt, self.native_receipt):
            digest_id(value)
        token(self.journal_ref, "baseline journal reference")


@dataclass
class IdentityMap:
    project_id: str
    namespace_id: str
    branch_id: str
    engine: Engine
    objects: dict[str, ObjectRecord] = field(default_factory=dict)
    baseline: Baseline | None = None

    def validate(self) -> None:
        token(self.project_id, "project id")
        opaque_id(self.namespace_id)
        opaque_id(self.branch_id)
        require(type(self.engine) is str and self.engine in {"unity", "unreal", "godot"}, "unsupported engine")
        require(type(self.objects) is dict and len(self.objects) <= MAX_OBJECTS,
                "invalid object inventory")
        locators, bindings = set(), set()
        for key, row in self.objects.items():
            opaque_id(key)
            require(isinstance(row, ObjectRecord) and row.authoring_id == key, "object key mismatch")
            require(type(row.kind) is str and row.kind in {"scene", "prefab_definition", "prefab_instance", "object"}, "invalid object kind")
            row.locator.validate()
            require(row.locator.engine == self.engine, "cross-engine association")
            require(row.locator not in locators, "colliding persistent native locator")
            locators.add(row.locator)  # Tombstones reserve identity too.
            require(type(row.generation) is int and 1 <= row.generation < 2**63, "invalid generation")
            require(type(row.tombstone) is bool, "invalid tombstone")
            require(type(row.display_name) is str and len(row.display_name) <= 1024, "invalid name hint")
            require(type(row.path_hint) is str and len(row.path_hint) <= 4096, "invalid path hint")
            token(row.provenance, "object provenance")
            for reference in (row.scene_id, row.prefab_id, row.parent_id, row.duplicate_of):
                if reference is not None:
                    opaque_id(reference)
                    require(reference in self.objects and reference != key, "dangling/self identity reference")
            if row.scene_id:
                require(self.objects[row.scene_id].kind == "scene", "scene reference is not a scene")
            if row.prefab_id:
                require(self.objects[row.prefab_id].kind == "prefab_definition", "prefab reference is not a definition")
            require((row.kind == "prefab_instance") == (row.prefab_id is not None), "prefab instance requires its definition")
            if row.kind in {"scene", "prefab_definition"}:
                require(row.scene_id is None and row.parent_id is None, "definition cannot be a placed instance")
            if row.parent_id:
                parent = self.objects[row.parent_id]
                require(parent.scene_id == row.scene_id, "parent crosses scene boundary")
            if not row.tombstone:
                for reference in (row.scene_id, row.prefab_id, row.parent_id):
                    require(reference is None or not self.objects[reference].tombstone,
                            "active object depends on a tombstone")
            if row.world_binding is not None:
                row.world_binding.validate()
                binding = row.world_binding
                for identity in (("world", binding.world_object_id),
                                 ("actor", binding.actor_id, binding.instance_index)):
                    require(identity not in bindings, "ambiguous World binding")
                    bindings.add(identity)
        # Iterative traversal avoids recursion limits on deep native hierarchies.
        for relation in ("parent_id", "duplicate_of"):
            finished: set[str] = set()
            for key in self.objects:
                trail: set[str] = set()
                cursor: str | None = key
                while cursor is not None and cursor not in finished:
                    require(cursor not in trail, f"{relation} cycle")
                    trail.add(cursor)
                    cursor = getattr(self.objects[cursor], relation)
                finished.update(trail)
        if self.baseline is not None:
            self.baseline.validate()

    def mapping_digest(self) -> str:
        self.validate()
        return digest({"namespace_id": self.namespace_id, "engine": self.engine,
                       "objects": {key: asdict(row) for key, row in sorted(self.objects.items())}})

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {"schema": SCHEMA, **asdict(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IdentityMap:
        exact(data, {"schema", "project_id", "namespace_id", "branch_id", "engine", "objects", "baseline"})
        require(data["schema"] == SCHEMA, "schema migration required")
        require(type(data["objects"]) is dict and len(data["objects"]) <= MAX_OBJECTS, "invalid inventory")
        rows = {}
        for key, raw in data["objects"].items():
            exact(raw, set(ObjectRecord.__dataclass_fields__))
            exact(raw["locator"], set(NativeLocator.__dataclass_fields__))
            values = dict(raw, locator=NativeLocator(**raw["locator"]))
            if raw["world_binding"] is not None:
                exact(raw["world_binding"], set(WorldBinding.__dataclass_fields__))
                values["world_binding"] = WorldBinding(**raw["world_binding"])
            rows[key] = ObjectRecord(**values)
        baseline = data["baseline"]
        if baseline is not None:
            exact(baseline, set(Baseline.__dataclass_fields__))
            baseline = Baseline(**baseline)
        result = cls(data["project_id"], data["namespace_id"], data["branch_id"], data["engine"], rows, baseline)
        result.validate()
        return result


def migrate_v1(data: dict[str, Any]) -> IdentityMap:
    """Explicit compatibility migration, never invoked silently by load.

    v1 is the retained-map compatibility format documented with NEC-002, not a
    claim that an earlier XP release generated native identity mappings.
    """
    data = copy.deepcopy(data)
    exact(data, {"schema", "project_id", "namespace_id", "branch_id", "engine", "objects", "baseline"})
    require(data["schema"] == LEGACY_SCHEMA and data["baseline"] is None, "unsupported legacy mapping")
    require(type(data["objects"]) is dict, "invalid legacy inventory")
    for raw in data["objects"].values():
        exact(raw, set(ObjectRecord.__dataclass_fields__) - {"generation", "tombstone"})
        raw.update(generation=1, tombstone=False)
    data["schema"] = SCHEMA
    return IdentityMap.from_dict(data)


class IdentityDraft:
    """Copy-based, all-or-nothing preparation; no disk or native side effects."""
    def __init__(self, source: IdentityMap):
        source.validate()
        self._map = copy.deepcopy(source)

    def snapshot(self) -> IdentityMap:
        self._map.validate()
        return copy.deepcopy(self._map)

    def _accept(self, candidate: IdentityMap) -> None:
        candidate.validate()
        self._map = candidate

    def add(self, row: ObjectRecord) -> None:
        require(row.authoring_id not in self._map.objects, "identity already exists, including tombstones")
        require(row.generation == 1 and not row.tombstone, "new object must begin active at generation one")
        candidate = self.snapshot()
        candidate.objects[row.authoring_id] = copy.deepcopy(row)
        self._accept(candidate)

    def update(self, identity: str, *, locator: NativeLocator | None = None,
               display_name: str | None = None, path_hint: str | None = None,
               parent_id: str | None = None, set_parent: bool = False) -> None:
        candidate = self.snapshot()
        require(identity in candidate.objects and not candidate.objects[identity].tombstone, "object unavailable")
        row = candidate.objects[identity]
        if locator is not None:
            row.locator = locator
        if display_name is not None:
            row.display_name = display_name
        if path_hint is not None:
            row.path_hint = path_hint
        if set_parent:
            row.parent_id = parent_id
        if row != self._map.objects[identity]:
            row.generation += 1
        self._accept(candidate)

    def duplicate(self, identity: str, new_identity: str, locator: NativeLocator,
                  provenance: str) -> None:
        require(identity in self._map.objects and not self._map.objects[identity].tombstone, "source unavailable")
        row = copy.deepcopy(self._map.objects[identity])
        row.authoring_id, row.locator = new_identity, locator
        row.generation, row.duplicate_of, row.provenance = 1, identity, provenance
        row.world_binding = None  # No duplicate authoritative actor/world association.
        self.add(row)

    def tombstone(self, identities: list[str], *, deleted: bool = True) -> None:
        require(type(deleted) is bool and len(identities) == len(set(identities)), "invalid deletion batch")
        candidate = self.snapshot()
        for identity in identities:
            require(identity in candidate.objects, "unknown object; cannot infer deletion/undo")
            row = candidate.objects[identity]
            if row.tombstone != deleted:
                row.tombstone = deleted
                row.generation += 1
        self._accept(candidate)

    def set_baseline(self, baseline: Baseline) -> None:
        baseline.validate()
        require(baseline.mapping_digest == self._map.mapping_digest(), "baseline does not describe current mapping")
        candidate = self.snapshot()
        candidate.baseline = baseline
        self._accept(candidate)

    def fork(self, branch_id: str) -> None:
        opaque_id(branch_id)
        require(branch_id != self._map.branch_id, "clone needs an explicit distinct branch id")
        candidate = self.snapshot()
        candidate.branch_id = branch_id
        self._accept(candidate)


def metadata_for(mapping: IdentityMap, identity: str) -> dict[str, Any]:
    mapping.validate()
    require(identity in mapping.objects and not mapping.objects[identity].tombstone, "metadata target unavailable")
    return _metadata(mapping.namespace_id, mapping.objects[identity])


def _metadata(namespace_id: str, row: ObjectRecord) -> dict[str, Any]:
    return {"schema": "xace.native_identity.v1", "namespace_id": namespace_id,
            "authoring_id": row.authoring_id, "kind": row.kind, "generation": row.generation}


def associate(mapping: IdentityMap, observations: list[tuple[NativeLocator, dict[str, Any] | None]]) -> list[str]:
    """All observations must agree; lost/duplicated/stale metadata never guesses."""
    mapping.validate()
    require(len(observations) <= MAX_OBJECTS, "observation limit")
    result, seen_locators, seen_ids = [], set(), set()
    for locator, metadata in observations:
        locator.validate()
        require(metadata is not None, "metadata missing: explicit recovery/adoption required")
        exact(metadata, {"schema", "namespace_id", "authoring_id", "kind", "generation"})
        require(type(metadata["generation"]) is int, "invalid attached generation")
        require(metadata["namespace_id"] == mapping.namespace_id, "foreign/clone namespace conflict")
        identity = metadata["authoring_id"]
        opaque_id(identity)
        require(identity not in seen_ids and locator not in seen_locators, "duplicated native metadata")
        require(identity in mapping.objects, "unknown metadata identity")
        row = mapping.objects[identity]
        require(not row.tombstone, "metadata target unavailable")
        require(metadata == _metadata(mapping.namespace_id, row), "stale or conflicting attached metadata")
        require(row.locator == locator, "locator changed: explicit reviewed relocation required")
        result.append(identity)
        seen_ids.add(identity)
        seen_locators.add(locator)
    return result


def branch_conflicts(left: IdentityMap, right: IdentityMap) -> list[str]:
    """Detect ambiguity; this is not NEC-008 three-way merge."""
    left.validate()
    right.validate()
    require((left.project_id, left.namespace_id, left.engine) ==
            (right.project_id, right.namespace_id, right.engine), "foreign namespace/project")
    require(left.branch_id != right.branch_id, "same-branch clone must explicitly fork before association")
    conflicts = {key for key in left.objects.keys() & right.objects.keys()
                 if left.objects[key] != right.objects[key]}
    locators = {row.locator: key for key, row in left.objects.items()}
    for key, row in right.objects.items():
        if row.locator in locators and locators[row.locator] != key:
            conflicts.update((key, locators[row.locator]))
    bindings = {}
    for mapping in (left, right):
        for key, row in mapping.objects.items():
            if row.world_binding:
                binding = row.world_binding
                for identity in (("world", binding.world_object_id),
                                 ("actor", binding.actor_id, binding.instance_index)):
                    if identity in bindings and bindings[identity] != key:
                        conflicts.update((key, bindings[identity]))
                    bindings[identity] = key
    return sorted(conflicts)
