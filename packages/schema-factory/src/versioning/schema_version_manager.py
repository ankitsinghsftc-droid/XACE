"""
schema_version_manager.py — SchemaVersionManager
==================================================
Manages the CGS version chain: computes deterministic content hashes,
increments version numbers, creates SchemaSnapshots, and supports
rollback navigation.

## Hash Computation (D9, D11)
cgs_hash is computed by serialising the CGS content dict to canonical JSON
(sorted keys, no whitespace) and taking its SHA-256 digest. This guarantees:
    - Same CGS content → same hash (D9)
    - Hash is independent of dict insertion order (D11)
    - Any field change produces a different hash (change detection)

## Version Increment Strategy
The Schema Factory does not choose which component to increment —
that is the GDE's responsibility. The version manager just applies
whichever bump the caller requests:
    bump_patch()  — bug fixes, cosmetic tweaks, balance adjustments
    bump_minor()  — new systems, actors, or game mechanics added
    bump_major()  — breaking change — save files require migration

## Snapshot Chain
The manager maintains an ordered list of SchemaSnapshots.
The chain is append-only. Rollback does not remove snapshots —
it creates a new "rollback" snapshot that points to the target
version's hash. This preserves the full audit trail.

## Thread Safety
SchemaVersionManager is NOT thread-safe. It is used synchronously
within a single CGSManager session (Phase 12). Concurrent writes
to the same CGS are architecturally prohibited (I3).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .schema_snapshot import SchemaSnapshot, _validate_version_string


# ── Version Manager Error ─────────────────────────────────────────────────────

class SchemaVersionError(Exception):
    """Raised when a version management invariant is violated."""


# ── Schema Version Manager ────────────────────────────────────────────────────

@dataclass
class SchemaVersionManager:
    """
    Manages the CGS version chain for one game project.

    Tracks the current version, computes content hashes, creates
    snapshots, and provides rollback navigation.

    Attributes
    ----------
    _snapshots : list[SchemaSnapshot]
        Ordered list of all snapshots in the chain.
        Index 0 is always the genesis snapshot.
        Append-only — entries are never removed.
    _current_version : str
        The MAJOR.MINOR.PATCH version of the most recent snapshot.
    """

    _snapshots:        list[SchemaSnapshot] = field(default_factory=list)
    _current_version:  str                  = "0.1.0"

    # ── Initialisation ────────────────────────────────────────────────────────

    @classmethod
    def initialise(
        cls,
        initial_cgs: dict[str, Any],
        session_id:  str | None = None,
    ) -> "SchemaVersionManager":
        """
        Creates a SchemaVersionManager with the genesis snapshot.

        Call this once when a new game is created by the Game Genesis Engine.
        The initial_cgs dict is the starting CGS produced by GGE.

        Parameters
        ----------
        initial_cgs : dict[str, Any]
            The starting CGS content dict.
        session_id : str | None
            Builder session ID for the creation session.
        """
        manager = cls()
        cgs_hash = cls.compute_hash(initial_cgs)
        genesis  = SchemaSnapshot.genesis(cgs_hash=cgs_hash, session_id=session_id)
        manager._snapshots.append(genesis)
        manager._current_version = genesis.version
        return manager

    @classmethod
    def restore(cls, snapshots: list[SchemaSnapshot]) -> "SchemaVersionManager":
        """
        Restores a SchemaVersionManager from a persisted snapshot chain.
        Validates chain integrity before restoring.

        Raises
        ------
        SchemaVersionError
            If the chain has gaps, duplicates, or hash mismatches.
        """
        if not snapshots:
            raise SchemaVersionError(
                "Cannot restore from an empty snapshot list. "
                "At least a genesis snapshot is required."
            )
        errors = _validate_chain_integrity(snapshots)
        if errors:
            raise SchemaVersionError(
                f"Snapshot chain integrity check failed:\n"
                + "\n".join(f"  {e}" for e in errors)
            )
        manager = cls()
        manager._snapshots = list(snapshots)
        manager._current_version = snapshots[-1].version
        return manager

    # ── Hash Computation (D9, D11) ────────────────────────────────────────────

    @staticmethod
    def compute_hash(cgs_content: dict[str, Any]) -> str:
        """
        Computes a deterministic SHA-256 hash of the CGS content dict.

        Serialises to canonical JSON: sorted keys, no separators beyond
        the structural minimum, UTF-8 encoded. This guarantees:
            - Same content → same hash regardless of insertion order (D11)
            - Any field change → different hash (D9)

        Parameters
        ----------
        cgs_content : dict[str, Any]
            The full CGS dict to hash.

        Returns
        -------
        str
            64-character lowercase hex SHA-256 digest.
        """
        canonical = json.dumps(
            cgs_content,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    # ── Version Bumping ───────────────────────────────────────────────────────

    def bump_patch(
        self,
        new_cgs:        dict[str, Any],
        description:    str        = "",
        mutation_source: str       = "manual",
        transaction_id: str | None = None,
        session_id:     str | None = None,
    ) -> SchemaSnapshot:
        """
        Increments the PATCH component and records a new snapshot.
        Use for: balance tweaks, parameter adjustments, cosmetic changes.
        """
        return self._bump(
            component="patch",
            new_cgs=new_cgs,
            description=description,
            mutation_source=mutation_source,
            transaction_id=transaction_id,
            session_id=session_id,
        )

    def bump_minor(
        self,
        new_cgs:         dict[str, Any],
        description:     str        = "",
        mutation_source: str        = "manual",
        transaction_id:  str | None = None,
        session_id:      str | None = None,
    ) -> SchemaSnapshot:
        """
        Increments the MINOR component (resets PATCH to 0) and snapshots.
        Use for: new systems, actors, mechanics — backward-compatible additions.
        """
        return self._bump(
            component="minor",
            new_cgs=new_cgs,
            description=description,
            mutation_source=mutation_source,
            transaction_id=transaction_id,
            session_id=session_id,
        )

    def bump_major(
        self,
        new_cgs:         dict[str, Any],
        description:     str        = "",
        mutation_source: str        = "manual",
        transaction_id:  str | None = None,
        session_id:      str | None = None,
    ) -> SchemaSnapshot:
        """
        Increments the MAJOR component (resets MINOR and PATCH) and snapshots.
        Use for: breaking changes — existing save files require migration.
        """
        return self._bump(
            component="major",
            new_cgs=new_cgs,
            description=description,
            mutation_source=mutation_source,
            transaction_id=transaction_id,
            session_id=session_id,
        )

    def record_snapshot(
        self,
        new_cgs:         dict[str, Any],
        new_version:     str,
        description:     str        = "",
        mutation_source: str        = "manual",
        transaction_id:  str | None = None,
        session_id:      str | None = None,
    ) -> SchemaSnapshot:
        """
        Records a snapshot with a caller-supplied version string.
        Used by the GDE when the version bump type is explicitly specified
        by the mutation planner. Validates the new version is strictly
        greater than the current version.
        """
        _validate_version_string(new_version)
        current = self._current_snapshot()
        if current and not _version_gt(new_version, self._current_version):
            raise SchemaVersionError(
                f"New version '{new_version}' must be strictly greater than "
                f"current version '{self._current_version}'."
            )
        return self._create_and_append(
            new_version=new_version,
            cgs_hash=self.compute_hash(new_cgs),
            description=description,
            mutation_source=mutation_source,
            transaction_id=transaction_id,
            session_id=session_id,
        )

    # ── Rollback ──────────────────────────────────────────────────────────────

    def rollback_to(
        self,
        target_cgs_hash: str,
        new_cgs:         dict[str, Any],
        session_id:      str | None = None,
    ) -> SchemaSnapshot:
        """
        Creates a rollback snapshot pointing to a prior CGS state.

        Rollback does not remove snapshots — it appends a new "rollback"
        snapshot. The audit trail is always preserved.

        The caller must supply the actual CGS content (new_cgs) matching
        the target_cgs_hash. The manager verifies the hash matches.

        Raises
        ------
        SchemaVersionError
            If target_cgs_hash is not found in the chain.
            If the supplied new_cgs does not hash to target_cgs_hash.
        """
        target = self.find_by_hash(target_cgs_hash)
        if target is None:
            raise SchemaVersionError(
                f"Rollback target hash '{target_cgs_hash[:8]}…' "
                f"not found in the snapshot chain. "
                f"Available hashes: "
                f"{[s.short_hash() for s in self._snapshots]}"
            )
        actual_hash = self.compute_hash(new_cgs)
        if actual_hash != target_cgs_hash:
            raise SchemaVersionError(
                f"Rollback CGS content does not match target hash. "
                f"Expected {target_cgs_hash[:8]}…, got {actual_hash[:8]}…. "
                f"The CGS content supplied must exactly match the target snapshot."
            )
        return self._create_and_append(
            new_version=self._next_version("patch"),
            cgs_hash=actual_hash,
            description=f"Rollback to version {target.version} ({target.short_hash()})",
            mutation_source="rollback",
            transaction_id=None,
            session_id=session_id,
        )

    # ── Queries ───────────────────────────────────────────────────────────────

    @property
    def current_version(self) -> str:
        """The MAJOR.MINOR.PATCH version of the most recent snapshot."""
        return self._current_version

    @property
    def current_hash(self) -> str | None:
        """The cgs_hash of the most recent snapshot, or None if empty."""
        snap = self._current_snapshot()
        return snap.cgs_hash if snap else None

    def snapshot_count(self) -> int:
        return len(self._snapshots)

    def all_snapshots(self) -> list[SchemaSnapshot]:
        """Returns all snapshots in chain order (genesis first)."""
        return list(self._snapshots)

    def find_by_version(self, version: str) -> SchemaSnapshot | None:
        """Returns the snapshot with the given version string, or None."""
        for snap in reversed(self._snapshots):
            if snap.version == version:
                return snap
        return None

    def find_by_hash(self, cgs_hash: str) -> SchemaSnapshot | None:
        """Returns the snapshot with the given cgs_hash, or None."""
        for snap in self._snapshots:
            if snap.cgs_hash == cgs_hash:
                return snap
        return None

    def genesis_snapshot(self) -> SchemaSnapshot | None:
        """Returns the initial genesis snapshot, or None if chain is empty."""
        return self._snapshots[0] if self._snapshots else None

    def validate_content(self, cgs_content: dict[str, Any]) -> bool:
        """
        Returns True if the hash of the given CGS content matches the
        current snapshot's hash. Used at runtime to detect CGS tampering.
        """
        if not self._snapshots:
            return False
        return self.compute_hash(cgs_content) == self.current_hash

    # ── Internal ──────────────────────────────────────────────────────────────

    def _current_snapshot(self) -> SchemaSnapshot | None:
        return self._snapshots[-1] if self._snapshots else None

    def _next_version(self, component: str) -> str:
        """Computes the next version string by bumping the given component."""
        parts = self._current_version.split(".")
        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
        match component:
            case "major":
                return f"{major + 1}.0.0"
            case "minor":
                return f"{major}.{minor + 1}.0"
            case "patch":
                return f"{major}.{minor}.{patch + 1}"
            case _:
                raise SchemaVersionError(
                    f"Unknown version component '{component}'. "
                    f"Must be 'major', 'minor', or 'patch'."
                )

    def _create_and_append(
        self,
        new_version:     str,
        cgs_hash:        str,
        description:     str,
        mutation_source: str,
        transaction_id:  str | None,
        session_id:      str | None,
    ) -> SchemaSnapshot:
        """Creates a snapshot, appends it to the chain, updates current version."""
        current = self._current_snapshot()
        snapshot = SchemaSnapshot.create(
            version=new_version,
            cgs_hash=cgs_hash,
            parent_version_hash=current.cgs_hash if current else None,
            mutation_source=mutation_source,
            transaction_id=transaction_id,
            description=description,
            session_id=session_id,
        )
        self._snapshots.append(snapshot)
        self._current_version = new_version
        return snapshot

    def _bump(
        self,
        component:       str,
        new_cgs:         dict[str, Any],
        description:     str,
        mutation_source: str,
        transaction_id:  str | None,
        session_id:      str | None,
    ) -> SchemaSnapshot:
        if not self._snapshots:
            raise SchemaVersionError(
                "Cannot bump version on an uninitialised SchemaVersionManager. "
                "Call SchemaVersionManager.initialise() first."
            )
        return self._create_and_append(
            new_version=self._next_version(component),
            cgs_hash=self.compute_hash(new_cgs),
            description=description,
            mutation_source=mutation_source,
            transaction_id=transaction_id,
            session_id=session_id,
        )


# ── Chain Integrity Validation ────────────────────────────────────────────────

def _validate_chain_integrity(snapshots: list[SchemaSnapshot]) -> list[str]:
    """
    Validates that a list of snapshots forms an unbroken chain.
    Returns a list of error strings (empty = valid).
    """
    errors: list[str] = []
    if not snapshots:
        return errors

    if not snapshots[0].is_genesis:
        errors.append(
            f"First snapshot (v={snapshots[0].version}) has a non-None "
            f"parent_version_hash. The chain must start with a genesis snapshot."
        )

    seen_hashes: set[str] = set()
    for i, snap in enumerate(snapshots):
        if snap.cgs_hash in seen_hashes:
            errors.append(
                f"Duplicate cgs_hash '{snap.short_hash()}' at position {i} "
                f"(version {snap.version}). Snapshot hashes must be unique."
            )
        seen_hashes.add(snap.cgs_hash)

        if i > 0:
            parent = snapshots[i - 1]
            if snap.parent_version_hash != parent.cgs_hash:
                errors.append(
                    f"Chain break at position {i}: snapshot v={snap.version} "
                    f"parent_version_hash={str(snap.parent_version_hash)[:8]}… "
                    f"does not match previous snapshot cgs_hash={parent.short_hash()}…"
                )

    return errors


def _version_gt(a: str, b: str) -> bool:
    """Returns True if version string a is strictly greater than b."""
    def to_tuple(v: str) -> tuple[int, int, int]:
        parts = v.split(".")
        return int(parts[0]), int(parts[1]), int(parts[2])
    return to_tuple(a) > to_tuple(b)