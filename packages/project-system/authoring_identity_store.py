"""NEC-002 atomic metadata revision store under .xace/authoring.

Only the head pointer commits. Immutable, content-addressed revisions retain old
maps and baseline references. This is not NEC-009's multi-editor transaction.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from authoring_identity import (
    MAX_BYTES, IdentityError, IdentityMap, canonical, digest_id, exact, require, token,
)
from project_manifest import MANIFEST_FILENAME, XaceProjectManifest, atomic_write_text_file

REVISION_SCHEMA = "xace.authoring_revision.v1"
HEAD_SCHEMA = "xace.authoring_head.v1"


def read_bounded(path: Path) -> bytes:
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    require(len(raw) <= MAX_BYTES, "identity file exceeds byte limit")
    return raw


def parse(raw: bytes) -> dict:
    require(len(raw) <= MAX_BYTES, "identity file exceeds byte limit")

    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(IdentityError("nonfinite JSON")))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise IdentityError("invalid identity JSON") from exc
    require(type(value) is dict, "identity file must be an object")
    return value


@dataclass(frozen=True)
class PreparedIdentityRevision:
    expected_revision: str | None
    revision: str
    payload: bytes


@dataclass(frozen=True)
class LoadedIdentityRevision:
    revision: str
    mapping: IdentityMap
    journal_ref: str


class AuthoringIdentityStore:
    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root).resolve()
        self.root = self.project_root / ".xace" / "authoring"

    def _path(self, name: str) -> Path:
        path = self.root / name
        require(path.resolve().is_relative_to(self.project_root), "metadata path escapes project")
        # Do not follow directory junctions/symlinks even if they stay in-project.
        for item in (path, *path.parents):
            if item == self.project_root:
                break
            if item.exists() or item.is_symlink():
                attributes = getattr(item.lstat(), "st_file_attributes", 0)
                require(not item.is_symlink() and not attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024),
                        "linked metadata path refused")
        return path

    def _project(self) -> XaceProjectManifest:
        path = self.project_root / MANIFEST_FILENAME
        require(path.is_file(), "existing project manifest required")
        # Read only: load_manifest's automatic recovery is inappropriate here.
        return XaceProjectManifest.from_dict(parse(read_bounded(path)))

    def _check_project(self, mapping: IdentityMap) -> None:
        project = self._project()
        require((mapping.project_id, mapping.engine) == (project.project_id, project.engine_type),
                "identity map belongs to another project/engine")

    def _head(self) -> str | None:
        path = self._path("head.json")
        if not path.exists():
            return None
        value = parse(read_bounded(path))
        exact(value, {"schema", "revision"})
        require(value["schema"] == HEAD_SCHEMA, "unknown head schema")
        digest_id(value["revision"])
        return value["revision"]

    def _revision(self, revision: str) -> LoadedIdentityRevision:
        digest_id(revision)
        path = self._path(f"revisions/{revision}.json")
        require(path.is_file(), "missing revision: explicit recovery required")
        raw = read_bounded(path)
        require(hashlib.sha256(raw).hexdigest() == revision, "corrupt identity revision")
        value = parse(raw)
        exact(value, {"schema", "parent_revision", "journal_ref", "operation", "mapping"})
        require(value["schema"] == REVISION_SCHEMA, "unsupported revision schema")
        if value["parent_revision"] is not None:
            digest_id(value["parent_revision"])
        token(value["journal_ref"], "journal reference")
        require(value["operation"] in {"initialize", "edit", "fork", "migration"}, "invalid revision operation")
        mapping = IdentityMap.from_dict(value["mapping"])
        self._check_project(mapping)
        return LoadedIdentityRevision(revision, mapping, value["journal_ref"])

    def load(self) -> LoadedIdentityRevision:
        revision = self._head()
        require(revision is not None, "identity head missing: explicit initialization/recovery required")
        return self._revision(revision)

    def history(self, revision: str) -> LoadedIdentityRevision:
        """Read an explicitly selected historical revision; no implicit rollback."""
        return self._revision(revision)

    @staticmethod
    def _transition(old: IdentityMap | None, new: IdentityMap, operation: str,
                    journal_ref: str) -> None:
        new.validate()
        require(operation in {"initialize", "edit", "fork", "migration"}, "invalid operation")
        if old is None:
            require(operation in {"initialize", "migration"}, "explicit initialization required")
            require(new.baseline is None, "new map cannot claim a reconciled baseline")
            if operation == "initialize":
                require(not new.objects, "initialize an empty map before adopting objects")
            return
        require(operation in {"edit", "fork"}, "existing mapping cannot be reinitialized/migrated implicitly")
        require((old.project_id, old.namespace_id, old.engine) ==
                (new.project_id, new.namespace_id, new.engine), "namespace/project reassignment refused")
        if operation == "fork":
            require(old.branch_id != new.branch_id and old.objects == new.objects
                    and old.baseline == new.baseline, "fork preserves identities and baseline exactly")
            return
        require(old.branch_id == new.branch_id, "branch changes require explicit fork")
        require(old.objects.keys() <= new.objects.keys(), "objects cannot disappear; use tombstones")
        for key, row in new.objects.items():
            if key not in old.objects:
                require(row.generation == 1 and not row.tombstone, "invalid new object generation")
                continue
            previous = old.objects[key]
            require((row.kind, row.duplicate_of, row.provenance) ==
                    (previous.kind, previous.duplicate_of, previous.provenance), "immutable object provenance/kind changed")
            require(row.generation >= previous.generation, "generation cannot go backwards")
            before, after = copy.deepcopy(previous), copy.deepcopy(row)
            before.generation = after.generation = 0
            require((before == after and row.generation == previous.generation) or
                    (before != after and row.generation > previous.generation), "changed object requires a newer generation")
        if old.baseline != new.baseline and new.baseline is not None:
            require(new.baseline.mapping_digest == new.mapping_digest()
                    and new.baseline.journal_ref == journal_ref, "baseline receipts do not bind this mapping/transaction")
        require(old.baseline is None or new.baseline is not None, "baseline history cannot be silently discarded")

    def prepare(self, mapping: IdentityMap, *, expected_revision: str | None,
                journal_ref: str, operation: str = "edit") -> PreparedIdentityRevision:
        token(journal_ref, "journal reference")
        self._check_project(mapping)
        require(self._head() == expected_revision, "stale mapping revision")
        old = self._revision(expected_revision).mapping if expected_revision else None
        if old is None:
            require(not self._path("revisions").exists() or not any(self._path("revisions").iterdir()),
                    "history exists without head: recover instead of regenerating identities")
        self._transition(old, mapping, operation, journal_ref)
        payload = canonical({"schema": REVISION_SCHEMA, "parent_revision": expected_revision,
                             "journal_ref": journal_ref, "operation": operation, "mapping": mapping.to_dict()})
        return PreparedIdentityRevision(expected_revision, hashlib.sha256(payload).hexdigest(), payload)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        path = self._path("write.lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
                os.fsync(handle.fileno())
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def commit(self, prepared: PreparedIdentityRevision) -> str:
        require(hashlib.sha256(prepared.payload).hexdigest() == prepared.revision, "changed prepared metadata")
        value = parse(prepared.payload)
        exact(value, {"schema", "parent_revision", "journal_ref", "operation", "mapping"})
        require(value["schema"] == REVISION_SCHEMA and value["parent_revision"] == prepared.expected_revision,
                "prepared parent mismatch")
        token(value["journal_ref"], "journal reference")
        new = IdentityMap.from_dict(value["mapping"])
        with self._locked():
            self._check_project(new)
            current = self._head()
            if current == prepared.revision:
                self._revision(current)  # Verify idempotent retry, including existing bytes.
                return current
            require(current == prepared.expected_revision, "stale mapping revision at commit")
            old = self._revision(current).mapping if current else None
            self._transition(old, new, value["operation"], value["journal_ref"])
            target = self._path(f"revisions/{prepared.revision}.json")
            if current is None and target.parent.exists():
                require(all(p == target for p in target.parent.iterdir()), "lost head or competing initialization")
            if target.exists():
                require(read_bounded(target) == prepared.payload, "immutable revision collision")
            else:
                atomic_write_text_file(target, prepared.payload.decode("utf-8"))
            # Publication is the only commit point. Failure keeps the prior head.
            atomic_write_text_file(self._path("head.json"),
                                   canonical({"schema": HEAD_SCHEMA, "revision": prepared.revision}).decode("utf-8"))
            return prepared.revision

    def recover_head(self, revision: str, *, expected_head_digest: str | None,
                     namespace_id: str, branch_id: str) -> None:
        """Explicit lost/corrupt-pointer recovery, never rollback a valid head.

        Caller must select a trusted retained revision and inspect its identity.
        A valid newer map requires tombstone/undo edits, not pointer rollback.
        """
        with self._locked():
            path = self._path("head.json")
            raw = read_bounded(path) if path.exists() else None
            require((hashlib.sha256(raw).hexdigest() if raw is not None else None) == expected_head_digest,
                    "head changed during recovery")
            valid = False
            try:
                valid = self._head() is not None
                if valid:
                    self.load()
            except IdentityError:
                valid = False
            require(not valid, "valid head cannot be rolled back; use explicit authoring undo")
            restored = self._revision(revision).mapping
            require((restored.namespace_id, restored.branch_id) == (namespace_id, branch_id),
                    "recovery namespace/branch mismatch")
            atomic_write_text_file(path, canonical({"schema": HEAD_SCHEMA, "revision": revision}).decode("utf-8"))
