"""
cgs_persistence.py — CGS File Persistence
==========================================
Handles loading and saving CGS JSON files with atomic writes and
versioned snapshots.

## Atomic Write Pattern
    write → /tmp/xace_<hash>.json.tmp
    fsync  → ensure bytes on disk
    rename → replaces the real file atomically
    This prevents corrupt CGS files if the process is killed mid-write.

## Snapshot Strategy
    Each committed mutation creates a snapshot:
        <project_root>/.xace/snapshots/<cgs_hash>.json
    Snapshots are immutable — never overwritten.
    The current CGS lives at:
        <project_root>/game.cgs.json
    The snapshot index lives at:
        <project_root>/.xace/snapshot_index.json

## Schema Validation
    Loads are validated against the required top-level keys.
    Invalid files raise CGSLoadError, not ValueError.
"""

from __future__ import annotations

import json
import os
import time
import tempfile
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ── Required CGS structure ────────────────────────────────────────────────────

_REQUIRED_TOP_LEVEL_KEYS = {"metadata", "global_systems", "modes"}
_REQUIRED_METADATA_KEYS  = {"name", "cgs_hash", "version", "schema_version"}

# ── Exceptions ────────────────────────────────────────────────────────────────

class CGSLoadError(Exception):
    """Raised when a CGS file cannot be loaded or is structurally invalid."""

class CGSSaveError(Exception):
    """Raised when a CGS file cannot be saved."""

# ── Snapshot index record ─────────────────────────────────────────────────────

@dataclass
class SnapshotRecord:
    cgs_hash:       str
    schema_version: str
    turn_index:     int
    mutation_count: int
    timestamp:      float
    summary:        str       = ""
    version_bump:   str       = "patch"
    risk_level:     str       = "low"

    def to_dict(self) -> dict[str, Any]:
        return {
            "cgs_hash":       self.cgs_hash,
            "schema_version": self.schema_version,
            "turn_index":     self.turn_index,
            "mutation_count": self.mutation_count,
            "timestamp":      self.timestamp,
            "summary":        self.summary,
            "version_bump":   self.version_bump,
            "risk_level":     self.risk_level,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SnapshotRecord":
        return cls(
            cgs_hash       = d["cgs_hash"],
            schema_version = d.get("schema_version", "0.0.0"),
            turn_index     = d.get("turn_index", 0),
            mutation_count = d.get("mutation_count", 0),
            timestamp      = d.get("timestamp", 0.0),
            summary        = d.get("summary", ""),
            version_bump   = d.get("version_bump", "patch"),
            risk_level     = d.get("risk_level", "low"),
        )


# ── CGS Persistence ───────────────────────────────────────────────────────────

class CGSPersistence:
    """
    Manages CGS file I/O and versioned snapshots for one project.

    Usage
    -----
        persist = CGSPersistence(project_path="/path/to/project")
        cgs     = persist.load()
        persist.save(cgs)
        persist.snapshot(cgs, record)
        history = persist.list_snapshots(limit=20)
    """

    MAIN_FILENAME   = "game.cgs.json"
    XACE_DIR        = ".xace"
    SNAPSHOT_DIR    = "snapshots"
    SNAPSHOT_INDEX  = "snapshot_index.json"

    def __init__(self, project_path: str | Path) -> None:
        self._root          = Path(project_path).resolve()
        self._main_file     = self._root / self.MAIN_FILENAME
        self._xace_dir      = self._root / self.XACE_DIR
        self._snapshot_dir  = self._xace_dir / self.SNAPSHOT_DIR
        self._index_file    = self._xace_dir / self.SNAPSHOT_INDEX

        # Ensure directories exist
        self._xace_dir.mkdir(parents=True, exist_ok=True)
        self._snapshot_dir.mkdir(parents=True, exist_ok=True)

    # ── Load ──────────────────────────────────────────────────────────────────

    def load(self) -> dict[str, Any]:
        """
        Loads the main CGS file.

        Returns
        -------
        dict — parsed CGS JSON

        Raises
        ------
        CGSLoadError — if file is missing, unreadable, or structurally invalid
        """
        if not self._main_file.exists():
            raise CGSLoadError(
                f"CGS file not found: {self._main_file}. "
                f"Create a new project or copy an existing game.cgs.json."
            )

        try:
            text = self._main_file.read_text(encoding="utf-8")
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CGSLoadError(f"CGS file is invalid JSON: {exc}") from exc
        except OSError as exc:
            raise CGSLoadError(f"Cannot read CGS file: {exc}") from exc

        self._validate(data)
        log.info(
            "Loaded CGS '%s' hash=%s",
            data["metadata"].get("name"),
            data["metadata"].get("cgs_hash", "?")[:8],
        )
        return data

    def load_snapshot(self, cgs_hash: str) -> dict[str, Any]:
        """Loads a specific snapshot by CGS hash."""
        snap_path = self._snapshot_dir / f"{cgs_hash}.json"
        if not snap_path.exists():
            raise CGSLoadError(f"Snapshot {cgs_hash[:8]} not found.")
        try:
            data = json.loads(snap_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise CGSLoadError(f"Cannot load snapshot: {exc}") from exc
        self._validate(data)
        return data

    # ── Save ──────────────────────────────────────────────────────────────────

    def save(self, cgs: dict[str, Any]) -> None:
        """
        Atomically saves the CGS to the main file.
        Writes to a temp file, syncs, then renames.
        """
        self._validate(cgs)
        self._atomic_write(self._main_file, cgs)
        log.info(
            "Saved CGS '%s' hash=%s",
            cgs["metadata"].get("name"),
            cgs["metadata"].get("cgs_hash", "?")[:8],
        )

    def snapshot(
        self,
        cgs:    dict[str, Any],
        record: SnapshotRecord,
    ) -> None:
        """
        Saves a snapshot of the current CGS.
        Snapshot files are immutable — never overwritten.
        Updates the snapshot index.
        """
        snap_path = self._snapshot_dir / f"{record.cgs_hash}.json"
        if not snap_path.exists():
            self._atomic_write(snap_path, cgs)

        # Update index
        index = self._load_index()
        # Prepend new record, deduplicate by hash, keep latest 100
        existing = [r for r in index if r.cgs_hash != record.cgs_hash]
        updated  = [record] + existing
        updated  = updated[:100]
        self._save_index(updated)

        log.info(
            "Snapshot saved: hash=%s bump=%s",
            record.cgs_hash[:8],
            record.version_bump,
        )

    # ── Snapshot listing ──────────────────────────────────────────────────────

    def list_snapshots(self, limit: int = 50) -> list[SnapshotRecord]:
        """Returns snapshot records, newest first."""
        index = self._load_index()
        return index[:limit]

    # ── ExecutionPlan storage (Phase 14.5) ────────────────────────────────────

    PLANS_DIR = "execution_plans"

    @property
    def _plans_dir(self) -> Path:
        d = self._xace_dir / self.PLANS_DIR
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_execution_plan(self, cgs_hash: str, plan_json: str) -> None:
        """
        Saves an ExecutionPlan JSON string produced by the SGC binary.

        ExecutionPlans are immutable per CGS hash — one plan per schema version.
        Stored at: .xace/execution_plans/<cgs_hash>.plan.json

        Parameters
        ----------
        cgs_hash : str
            Hash of the CGS this plan was compiled from.
        plan_json : str
            Raw JSON string from the SGC binary stdout.
        """
        plan_path = self._plans_dir / f"{cgs_hash}.plan.json"
        if plan_path.exists():
            log.debug("ExecutionPlan already exists for hash=%s, skipping", cgs_hash[:8])
            return
        try:
            plan_path.write_text(plan_json, encoding="utf-8")
            log.info("ExecutionPlan saved: hash=%s bytes=%d", cgs_hash[:8], len(plan_json))
        except OSError as exc:
            raise CGSSaveError(f"Cannot save ExecutionPlan: {exc}") from exc

    def load_execution_plan(self, cgs_hash: str) -> str | None:
        """
        Loads the ExecutionPlan JSON for a given CGS hash.

        Returns
        -------
        str | None — plan JSON string, or None if not found.
        """
        plan_path = self._plans_dir / f"{cgs_hash}.plan.json"
        if not plan_path.exists():
            return None
        try:
            return plan_path.read_text(encoding="utf-8")
        except OSError as exc:
            log.warning("Cannot read ExecutionPlan: %s", exc)
            return None

    def has_execution_plan(self, cgs_hash: str) -> bool:
        """Returns True if an ExecutionPlan exists for this CGS hash."""
        if not cgs_hash:
            return False
        return (self._plans_dir / f"{cgs_hash}.plan.json").exists()

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _validate(cgs: Any) -> None:
        """Raises CGSLoadError if the CGS is structurally invalid."""
        if not isinstance(cgs, dict):
            raise CGSLoadError("CGS must be a JSON object at the top level.")
        missing_top = _REQUIRED_TOP_LEVEL_KEYS - set(cgs.keys())
        if missing_top:
            raise CGSLoadError(f"CGS missing required keys: {missing_top}")
        meta = cgs.get("metadata", {})
        if not isinstance(meta, dict):
            raise CGSLoadError("CGS metadata must be an object.")
        missing_meta = _REQUIRED_METADATA_KEYS - set(meta.keys())
        if missing_meta:
            raise CGSLoadError(f"CGS metadata missing: {missing_meta}")

    @staticmethod
    def _atomic_write(path: Path, data: dict[str, Any]) -> None:
        """Write JSON atomically: temp → sync → rename."""
        dir_path = path.parent
        try:
            fd, tmp_path = tempfile.mkstemp(
                prefix=".xace_tmp_",
                suffix=".json",
                dir=str(dir_path),
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, str(path))
            except Exception:
                try: os.unlink(tmp_path)
                except OSError: pass
                raise
        except OSError as exc:
            raise CGSSaveError(f"Cannot write to {path}: {exc}") from exc

    def _load_index(self) -> list[SnapshotRecord]:
        if not self._index_file.exists():
            return []
        try:
            raw = json.loads(self._index_file.read_text(encoding="utf-8"))
            return [SnapshotRecord.from_dict(r) for r in raw]
        except (json.JSONDecodeError, KeyError, OSError):
            return []

    def _save_index(self, records: list[SnapshotRecord]) -> None:
        data = [r.to_dict() for r in records]
        self._atomic_write(self._index_file, {"snapshots": data})

    def _load_index(self) -> list[SnapshotRecord]:
        if not self._index_file.exists():
            return []
        try:
            raw = json.loads(self._index_file.read_text(encoding="utf-8"))
            items = raw if isinstance(raw, list) else raw.get("snapshots", [])
            return [SnapshotRecord.from_dict(r) for r in items]
        except (json.JSONDecodeError, KeyError, TypeError, OSError):
            return []

    def __repr__(self) -> str:
        return f"CGSPersistence(root={self._root!r})"