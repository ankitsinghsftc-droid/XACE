"""
cgs_manager.py — CGSManager
============================
Single source of truth for the Canonical Game Schema (CGS) within
a GDE session.

## Responsibilities
- Holds the current CGS dict (one at a time — no branching)
- Accepts validated new CGS dicts produced by TransactionExecutor
  and records them as new snapshots via SchemaVersionManager
- Exposes rollback to any prior snapshot by hash
- Guarantees the CGS is never left in a partial or uncommitted state (I8)
- Provides read-only access to the current CGS for all downstream consumers

## What CGSManager Does NOT Do
- It does not parse prompts or build transactions (GDE orchestrator does)
- It does not validate schema correctness (SchemaValidationContract does)
- It does not execute mutations (TransactionExecutor does)
- It does not compile the schema for the runtime (SchemaFactory does)

## Mutation Flow
    1. TransactionExecutor applies a DSLTransaction to a COPY of the CGS
    2. ConsistencyValidator confirms the result is coherent
    3. GDE orchestrator calls CGSManager.commit(new_cgs, metadata)
    4. CGSManager computes the new hash, records a snapshot, stores new CGS
    5. Returns the new SchemaSnapshot to the orchestrator

## Thread Safety
CGSManager is NOT thread-safe. It is owned by a single GDE session.
Concurrent mutation is architecturally prohibited (I3).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from .cgs_serializer import CGSSerializer, CGSSerializationError

if TYPE_CHECKING:
    from .mutation_metadata_model import MutationMetadata


# ── Import SchemaVersionManager lazily to avoid circular imports ──────────────
# SchemaVersionManager lives in packages/schema-factory, which the GDE imports.
# The TYPE_CHECKING guard keeps this import from running at module load time.

try:
    from xace_schema_factory.versioning.schema_version_manager import (  # type: ignore[import]
        SchemaVersionManager,
        SchemaVersionError,
    )
    from xace_schema_factory.versioning.schema_snapshot import SchemaSnapshot  # type: ignore[import]
    _HAS_SCHEMA_FACTORY = True
except ImportError:
    _HAS_SCHEMA_FACTORY = False
    SchemaVersionManager = None  # type: ignore[assignment,misc]
    SchemaSnapshot = None        # type: ignore[assignment,misc]


# ── CGS Manager Error ─────────────────────────────────────────────────────────

class CGSManagerError(Exception):
    """Raised when a CGSManager invariant is violated."""


# ── CGS Manager ───────────────────────────────────────────────────────────────

@dataclass
class CGSManager:
    """
    Single-source-of-truth CGS manager for one GDE session.

    Holds the current CGS dict, its hash, and the version chain.
    All mutation flows through commit(). All reads go through current_cgs.

    Attributes
    ----------
    _cgs : dict[str, Any]
        The current authoritative CGS dict. Deep-copied on read to prevent
        accidental mutation by callers (I3).
    _version_manager : SchemaVersionManager | None
        Version chain manager. None when schema-factory is not installed.
    _session_id : str | None
        Builder session identifier for snapshot provenance.
    """

    _cgs:             dict[str, Any]    = field(default_factory=dict)
    _version_manager: Any               = field(default=None, repr=False)
    _session_id:      str | None        = None

    # ── Initialisation ────────────────────────────────────────────────────────

    @classmethod
    def initialise(
        cls,
        initial_cgs: dict[str, Any],
        session_id:  str | None = None,
    ) -> "CGSManager":
        """
        Creates a CGSManager with an initial CGS.

        Stamps the CGS with a freshly computed cgs_hash if one is not
        already present (genesis flow from GGE), then initialises the
        SchemaVersionManager snapshot chain.

        Parameters
        ----------
        initial_cgs : dict[str, Any]
            The starting CGS. May come from GGE, an import, or a save file.
        session_id : str | None
            Builder session identifier for provenance tracking.
        """
        cgs = _deep_copy_cgs(initial_cgs)
        cgs = _ensure_hash(cgs)

        manager = cls(_cgs=cgs, _session_id=session_id)

        if _HAS_SCHEMA_FACTORY:
            try:
                manager._version_manager = SchemaVersionManager.initialise(
                    cgs, session_id=session_id
                )
            except Exception:
                # Schema factory unavailable or initialisation failed —
                # CGSManager continues without version chain tracking.
                manager._version_manager = None

        return manager

    @classmethod
    def restore(
        cls,
        cgs:          dict[str, Any],
        session_id:   str | None = None,
    ) -> "CGSManager":
        """
        Restores a CGSManager from a persisted CGS dict (e.g. loaded from disk).
        The CGS must already have a metadata.cgs_hash field.

        Raises
        ------
        CGSManagerError
            If the CGS is missing metadata.cgs_hash.
        """
        if not cgs.get("metadata", {}).get("cgs_hash"):
            raise CGSManagerError(
                "Cannot restore CGSManager from a CGS without a cgs_hash. "
                "The persisted CGS must have metadata.cgs_hash set."
            )
        return cls.initialise(cgs, session_id=session_id)

    # ── Read Access ───────────────────────────────────────────────────────────

    @property
    def current_cgs(self) -> dict[str, Any]:
        """
        Returns a deep copy of the current CGS.
        Deep copy prevents callers from accidentally mutating the stored CGS (I3).
        """
        return _deep_copy_cgs(self._cgs)

    @property
    def current_hash(self) -> str:
        """Returns the SHA-256 hash of the current CGS."""
        return self._cgs.get("metadata", {}).get("cgs_hash", "")

    @property
    def current_version(self) -> str:
        """Returns the MAJOR.MINOR.PATCH version of the current CGS."""
        return self._cgs.get("metadata", {}).get("version", "0.1.0")

    def get_metadata(self) -> dict[str, Any]:
        """Returns a copy of the CGS metadata block."""
        return dict(self._cgs.get("metadata", {}))

    def get_mode(self, mode_id: str) -> dict[str, Any] | None:
        """Returns a deep copy of the mode dict with the given ID, or None."""
        for mode in self._cgs.get("modes", []):
            if mode.get("id") == mode_id:
                return _deep_copy_cgs(mode)
        return None

    def get_global_systems(self) -> list[dict[str, Any]]:
        """Returns a deep copy of the global_systems list."""
        return copy.deepcopy(self._cgs.get("global_systems", []))

    def all_mode_ids(self) -> list[str]:
        """Returns all mode IDs in declaration order."""
        return [m.get("id", "") for m in self._cgs.get("modes", [])]

    def is_initialised(self) -> bool:
        return bool(self._cgs)

    # ── Commit (the only mutation path) ──────────────────────────────────────

    def commit(
        self,
        new_cgs:   dict[str, Any],
        metadata:  "MutationMetadata",
        bump:      str = "patch",
    ) -> dict[str, Any]:
        """
        Commits a new CGS produced by TransactionExecutor.

        This is the ONLY path through which the stored CGS changes (I8, I3).

        Steps:
        1. Verify new_cgs was derived from the current CGS (parent hash check)
        2. Compute new cgs_hash, stamp into new_cgs metadata
        3. If SchemaVersionManager available, record snapshot
        4. Store new_cgs as current
        5. Return the new snapshot dict for the caller to reference

        Parameters
        ----------
        new_cgs : dict[str, Any]
            The result of applying a DSLTransaction to the current CGS.
            Produced by TransactionExecutor.
        metadata : MutationMetadata
            Provenance record for this commit.
        bump : str
            Version bump type: "patch" | "minor" | "major".
            Default "patch" — most mutations are incremental.

        Returns
        -------
        dict[str, Any]
            Snapshot record: {"version", "cgs_hash", "transaction_id",
                              "description", "source"}

        Raises
        ------
        CGSManagerError
            If metadata.parent_cgs_hash does not match the current CGS hash
            (stale-mutation guard — prevents applying to wrong version).
        """
        # ── Stale-mutation guard ──────────────────────────────────────────────
        if metadata.parent_cgs_hash != self.current_hash:
            raise CGSManagerError(
                f"Stale mutation: metadata.parent_cgs_hash "
                f"'{metadata.parent_cgs_hash[:8]}…' does not match "
                f"current CGS hash '{self.current_hash[:8]}…'. "
                f"The CGS was mutated between when this transaction was "
                f"created and when it was committed. Re-apply the transaction "
                f"against the current CGS."
            )

        # ── Stamp new hash and version ────────────────────────────────────────
        committed = _deep_copy_cgs(new_cgs)
        new_hash  = CGSSerializer.compute_hash(_strip_hash(committed))
        new_version = _bump_version(self.current_version, bump)

        committed.setdefault("metadata", {})
        committed["metadata"]["cgs_hash"] = new_hash
        committed["metadata"]["version"]  = new_version

        # ── Record snapshot ───────────────────────────────────────────────────
        if self._version_manager is not None:
            try:
                bump_fn = getattr(self._version_manager, f"bump_{bump}", None)
                if bump_fn:
                    bump_fn(
                        committed,
                        description=metadata.description,
                        mutation_source=metadata.source,
                        transaction_id=metadata.transaction_id,
                        session_id=self._session_id,
                    )
            except Exception:
                # Version manager failure must not block a commit
                pass

        # ── Swap in new CGS ───────────────────────────────────────────────────
        self._cgs = committed

        return {
            "version":        new_version,
            "cgs_hash":       new_hash,
            "transaction_id": metadata.transaction_id,
            "description":    metadata.description,
            "source":         metadata.source,
        }

    # ── Rollback ──────────────────────────────────────────────────────────────

    def rollback_to_hash(
        self,
        target_cgs_hash: str,
        prior_cgs:       dict[str, Any],
        session_id:      str | None = None,
    ) -> None:
        """
        Rolls back to a prior CGS state identified by its hash.

        The caller must supply the prior CGS content (retrieved from
        persistent storage or the snapshot chain). The manager verifies
        that hashing it produces target_cgs_hash.

        Raises
        ------
        CGSManagerError
            If the supplied prior_cgs does not hash to target_cgs_hash.
        """
        actual = CGSSerializer.compute_hash(_strip_hash(prior_cgs))
        if actual != target_cgs_hash:
            raise CGSManagerError(
                f"Rollback target mismatch: "
                f"supplied CGS hashes to '{actual[:8]}…' "
                f"but expected '{target_cgs_hash[:8]}…'."
            )
        restored = _deep_copy_cgs(prior_cgs)
        restored.setdefault("metadata", {})
        restored["metadata"]["cgs_hash"] = target_cgs_hash
        self._cgs = restored

    # ── Snapshot History ──────────────────────────────────────────────────────

    def snapshot_count(self) -> int:
        """Returns number of snapshots in the version chain (0 if unavailable)."""
        if self._version_manager is None:
            return 0
        return self._version_manager.snapshot_count()

    def snapshot_history(self) -> list[dict[str, Any]]:
        """
        Returns the snapshot chain as a list of summary dicts, oldest first.
        Empty list if SchemaVersionManager is unavailable.
        """
        if self._version_manager is None:
            return []
        return [
            {
                "version":    s.version,
                "cgs_hash":   s.cgs_hash,
                "source":     s.mutation_source,
                "created_at": s.created_at,
                "description":s.description,
            }
            for s in self._version_manager.all_snapshots()
        ]

    def __repr__(self) -> str:
        return (
            f"CGSManager(v={self.current_version}, "
            f"hash={self.current_hash[:8]}…, "
            f"snapshots={self.snapshot_count()})"
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _deep_copy_cgs(cgs: dict[str, Any]) -> dict[str, Any]:
    """Deep copies a CGS dict. Uses copy.deepcopy for full isolation."""
    return copy.deepcopy(cgs)


def _ensure_hash(cgs: dict[str, Any]) -> dict[str, Any]:
    """Stamps cgs_hash into metadata if not already present."""
    cgs.setdefault("metadata", {})
    if not cgs["metadata"].get("cgs_hash"):
        cgs["metadata"]["cgs_hash"] = CGSSerializer.compute_hash(_strip_hash(cgs))
    return cgs


def _strip_hash(cgs: dict[str, Any]) -> dict[str, Any]:
    """
    Returns a shallow copy of the CGS with cgs_hash removed from metadata.
    Used to compute a stable hash that doesn't include the hash itself.
    """
    stripped = copy.deepcopy(cgs)
    stripped.get("metadata", {}).pop("cgs_hash", None)
    return stripped


def _bump_version(version: str, bump: str) -> str:
    """Increments a MAJOR.MINOR.PATCH version string."""
    parts = version.split(".")
    if len(parts) != 3:
        return version
    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
    match bump:
        case "major": return f"{major + 1}.0.0"
        case "minor": return f"{major}.{minor + 1}.0"
        case _:       return f"{major}.{minor}.{patch + 1}"