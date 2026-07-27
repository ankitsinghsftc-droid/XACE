"""
schema_snapshot.py — SchemaSnapshot
=====================================
Immutable record of one CGS state at a point in time.

Every mutation to the CGS produces a new SchemaSnapshot that is appended
to the snapshot chain. The chain forms the complete history of design
decisions made during a game creation session.

## What a Snapshot Is NOT
A snapshot is NOT a full copy of the CGS content. It is a metadata record
— a chain link — that carries the version, the content hash, and
provenance (who made the change, from what parent, via which transaction).

The full CGS content is managed separately by the CGSManager (Phase 12).
SchemaVersionManager uses the snapshot chain for version validation,
rollback navigation, and migration path tracing.

## Chain Invariants
- The initial snapshot has parent_version_hash=None.
- Every subsequent snapshot's parent_version_hash equals the cgs_hash
  of the previous snapshot.
- cgs_hash is computed deterministically from the CGS content dict (D9).
  Same CGS content always produces the same hash.
- Snapshots are immutable once created (frozen=True).

## Mutation Sources
"genesis"   — Created by Game Genesis Engine (first CGS for a new game)
"prompt"    — Created by PIL/LLM from a natural-language prompt
"manual"    — Created by a developer via the DSL directly
"migration" — Created by the save migration engine (schema upgrade)
"rollback"  — Created when restoring a prior snapshot
"import"    — Created when importing an external CGS

## Usage
    snapshot = SchemaSnapshot.create(
        version="0.1.1",
        cgs_hash="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        parent_version_hash="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        mutation_source="prompt",
        transaction_id="txn-uuid-...",
        description="Added health regeneration to player",
    )
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import ClassVar


# ── Mutation Source Vocabulary ────────────────────────────────────────────────

VALID_MUTATION_SOURCES: frozenset[str] = frozenset({
    "genesis",
    "prompt",
    "manual",
    "migration",
    "rollback",
    "import",
})


# ── Schema Snapshot ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SchemaSnapshot:
    """
    Immutable record of one CGS version state.

    Attributes
    ----------
    version : str
        MAJOR.MINOR.PATCH version string for this snapshot.
        Incremented by SchemaVersionManager on each mutation.
    cgs_hash : str
        SHA-256 hex digest of the CGS content at this version.
        Computed deterministically — same content = same hash (D9, D11).
    parent_version_hash : str | None
        cgs_hash of the parent snapshot. None for the initial snapshot.
        Forms the immutable chain: child.parent_version_hash == parent.cgs_hash
    created_at : float
        Unix timestamp (seconds since epoch) when this snapshot was created.
        Set by SchemaSnapshot.create() — callers do not set this directly.
    mutation_source : str
        What produced this snapshot. One of VALID_MUTATION_SOURCES.
    transaction_id : str | None
        UUID of the DSLTransaction that produced this snapshot.
        None for genesis snapshots and rollbacks.
    description : str
        Human-readable description of what changed. Shown in the version
        timeline UI and Design Mentor history.
    session_id : str | None
        ID of the builder session in which this snapshot was created.
        Used by HistoryManager (Phase 13) for session-scoped rollback.
    """

    version:              str
    cgs_hash:             str
    parent_version_hash:  str | None   = None
    created_at:           float        = field(default_factory=time.time)
    mutation_source:      str          = "manual"
    transaction_id:       str | None   = None
    description:          str          = ""
    session_id:           str | None   = None

    # Class-level sentinel for the initial snapshot parent hash
    GENESIS_PARENT_HASH: ClassVar[None] = None

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def create(
        cls,
        version:             str,
        cgs_hash:            str,
        parent_version_hash: str | None = None,
        mutation_source:     str        = "manual",
        transaction_id:      str | None = None,
        description:         str        = "",
        session_id:          str | None = None,
    ) -> "SchemaSnapshot":
        """
        Creates a new SchemaSnapshot with the current timestamp.

        Raises
        ------
        ValueError
            If mutation_source is not in VALID_MUTATION_SOURCES.
            If version string does not match MAJOR.MINOR.PATCH format.
            If cgs_hash is empty.
        """
        if mutation_source not in VALID_MUTATION_SOURCES:
            raise ValueError(
                f"Invalid mutation_source '{mutation_source}'. "
                f"Valid values: {sorted(VALID_MUTATION_SOURCES)}"
            )
        if not cgs_hash:
            raise ValueError(
                "cgs_hash must not be empty. "
                "Compute it from the CGS content before creating a snapshot."
            )
        _validate_version_string(version)

        return cls(
            version=version,
            cgs_hash=cgs_hash,
            parent_version_hash=parent_version_hash,
            created_at=time.time(),
            mutation_source=mutation_source,
            transaction_id=transaction_id,
            description=description,
            session_id=session_id,
        )

    @classmethod
    def genesis(cls, cgs_hash: str, session_id: str | None = None) -> "SchemaSnapshot":
        """
        Creates the initial snapshot for a new game.
        Version is always "0.1.0". parent_version_hash is always None.
        """
        return cls.create(
            version="0.1.0",
            cgs_hash=cgs_hash,
            parent_version_hash=None,
            mutation_source="genesis",
            description="Initial game schema created by Game Genesis Engine.",
            session_id=session_id,
        )

    # ── Chain Queries ─────────────────────────────────────────────────────────

    @property
    def is_genesis(self) -> bool:
        """True if this is the first snapshot in the chain."""
        return self.parent_version_hash is None

    def is_child_of(self, parent: "SchemaSnapshot") -> bool:
        """
        Returns True if this snapshot is the direct child of `parent`.
        Validates the chain link: self.parent_version_hash == parent.cgs_hash
        """
        return self.parent_version_hash == parent.cgs_hash

    def chain_is_intact(self, parent: "SchemaSnapshot") -> bool:
        """Alias for is_child_of — more readable in validation contexts."""
        return self.is_child_of(parent)

    # ── Version Parsing ───────────────────────────────────────────────────────

    def version_tuple(self) -> tuple[int, int, int]:
        """Returns (major, minor, patch) as integers."""
        parts = self.version.split(".")
        return int(parts[0]), int(parts[1]), int(parts[2])

    @property
    def major(self) -> int:
        return self.version_tuple()[0]

    @property
    def minor(self) -> int:
        return self.version_tuple()[1]

    @property
    def patch(self) -> int:
        return self.version_tuple()[2]

    # ── Display ───────────────────────────────────────────────────────────────

    def short_hash(self) -> str:
        """Returns a non-authoritative cgs_hash display prefix for logs/UI only."""
        return self.cgs_hash[:8]

    def __repr__(self) -> str:
        parent = self.parent_version_hash[:8] if self.parent_version_hash else "genesis"
        return (
            f"SchemaSnapshot(v={self.version}, hash={self.short_hash()}, "
            f"parent={parent}, source={self.mutation_source!r})"
        )


# ── Version String Validation ─────────────────────────────────────────────────

def _validate_version_string(version: str) -> None:
    """
    Validates MAJOR.MINOR.PATCH format. All parts must be non-negative integers.

    Raises
    ------
    ValueError
        If the version string does not conform to MAJOR.MINOR.PATCH.
    """
    parts = version.split(".")
    if len(parts) != 3:
        raise ValueError(
            f"Version string '{version}' must be MAJOR.MINOR.PATCH "
            f"(e.g. '0.1.0', '1.0.0'). Got {len(parts)} part(s)."
        )
    for i, part in enumerate(parts):
        try:
            value = int(part)
        except ValueError:
            raise ValueError(
                f"Version string '{version}' part {i} ('{part}') "
                f"is not a valid integer."
            )
        if value < 0:
            raise ValueError(
                f"Version string '{version}' part {i} ({value}) "
                f"must be non-negative."
            )
