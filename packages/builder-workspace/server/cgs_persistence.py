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
import re
import time
import tempfile
import logging
import threading
import hashlib
import shutil
import copy
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from sgc_plan_validator import (
    SgcExecutionPlanContractError,
    validate_persisted_execution_plan_contract,
)

log = logging.getLogger(__name__)


def _lock_file(handle: Any) -> None:
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


def _unlock_file(handle: Any) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

# ── Required CGS structure ────────────────────────────────────────────────────

_REQUIRED_TOP_LEVEL_KEYS = {"metadata", "global_systems", "modes"}
_REQUIRED_METADATA_KEYS  = {"name", "cgs_hash", "version", "schema_version"}
_SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_CANONICAL_PHASES = {"Initialization", "Input", "Simulation", "PostSimulation", "Cleanup"}
_RESERVED_COMPONENT_TYPE_IDS = {
    1: "COMP_TRANSFORM_V1",
    2: "COMP_IDENTITY_V1",
    5: "COMP_VELOCITY_V1",
    6: "COMP_INPUT_V1",
    100: "COMP_HEALTH_V1",
    101: "COMP_DAMAGE_V1",
    160: "COMP_AI_V1",
    201: "COMP_INVENTORY_V1",
    205: "COMP_ITEM_V1",
    260: "COMP_INTERACTION_V1",
}

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


@dataclass
class CGSRecoveryReport:
    temp_files_removed: int = 0
    snapshot_index_rebuilt: bool = False
    execution_plans_repaired: int = 0
    execution_plans_removed: int = 0
    proof_bundles_removed: int = 0
    restored_cgs_hash: str = ""
    errors: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "temp_files_removed": self.temp_files_removed,
            "snapshot_index_rebuilt": self.snapshot_index_rebuilt,
            "execution_plans_repaired": self.execution_plans_repaired,
            "execution_plans_removed": self.execution_plans_removed,
            "proof_bundles_removed": self.proof_bundles_removed,
            "restored_cgs_hash": self.restored_cgs_hash,
            "errors": list(self.errors or []),
        }


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
    AUDIT_DIR       = "audit"
    AUDIT_LEDGER    = "transactions.jsonl"
    AUDIT_DATASET   = "mutations.jsonl"
    PROMPT_HISTORY  = "prompt_history.json"
    PROMPT_HISTORY_EVENTS = "prompt_history_events.jsonl"
    TXN_COUNTER     = "transaction_counter.json"
    CGS_WRITE_LOCK  = "cgs.write.lock"

    def __init__(self, project_path: str | Path) -> None:
        self._root          = Path(project_path).resolve()
        self._main_file     = self._root / self.MAIN_FILENAME
        self._xace_dir      = self._root / self.XACE_DIR
        self._snapshot_dir  = self._xace_dir / self.SNAPSHOT_DIR
        self._index_file    = self._xace_dir / self.SNAPSHOT_INDEX
        self._audit_dir     = self._xace_dir / self.AUDIT_DIR
        self._audit_ledger  = self._audit_dir / self.AUDIT_LEDGER
        self._audit_dataset = self._audit_dir / self.AUDIT_DATASET
        self._prompt_history_file = self._audit_dir / self.PROMPT_HISTORY
        self._prompt_history_events = self._audit_dir / self.PROMPT_HISTORY_EVENTS
        self._txn_counter   = self._audit_dir / self.TXN_COUNTER
        self._write_lock_file = self._xace_dir / self.CGS_WRITE_LOCK
        self._audit_lock    = threading.Lock()
        self._write_lock    = threading.RLock()

        # Ensure directories exist
        self._xace_dir.mkdir(parents=True, exist_ok=True)
        self._snapshot_dir.mkdir(parents=True, exist_ok=True)
        self._audit_dir.mkdir(parents=True, exist_ok=True)

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
        self.recover()
        with self.cgs_write_lock():
            if not self._main_file.exists():
                raise CGSLoadError(
                    f"CGS file not found: {self._main_file}. "
                    f"Create a new project or copy an existing game.cgs.json."
                )
            data = self._read_cgs_file(self._main_file, "CGS file")
        log.info(
            "Loaded CGS '%s' hash=%s",
            data["metadata"].get("name"),
            data["metadata"].get("cgs_hash", "?")[:8],
        )
        return data

    def current_cgs_hash(self) -> str:
        """Returns the hash currently persisted on disk, or empty string if unreadable."""
        if not self._main_file.exists():
            return ""
        try:
            data = json.loads(self._main_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return ""
        return str(data.get("metadata", {}).get("cgs_hash", ""))

    def load_snapshot(self, cgs_hash: str) -> dict[str, Any]:
        """Loads a specific snapshot by CGS hash."""
        snap_path = self._snapshot_dir / f"{cgs_hash}.json"
        if not snap_path.exists():
            raise CGSLoadError(f"Snapshot {cgs_hash[:8]} not found.")
        return self._read_cgs_file(snap_path, "snapshot")

    def recover(self) -> CGSRecoveryReport:
        """
        Repairs crash leftovers and restores the latest valid CGS if needed.

        Recovery is conservative: temp files are discarded, the snapshot index is
        rebuilt from structurally valid snapshots, and the main CGS is restored
        only when it is missing or invalid.
        """
        with self.cgs_write_lock():
            report = CGSRecoveryReport(errors=[])
            report.temp_files_removed = self._cleanup_temp_files()
            records, rebuilt = self._verified_snapshot_index()
            if rebuilt:
                self._save_index(records)
                report.snapshot_index_rebuilt = True

            self._recover_execution_plan_files(report)

            try:
                current_cgs = self._read_cgs_file(self._main_file, "CGS file")
                if self._cgs_requires_execution_plan(current_cgs):
                    current_hash = str(current_cgs.get("metadata", {}).get("cgs_hash", ""))
                    if not self._execution_plan_is_valid_for_hash(current_hash):
                        restored = self._restore_latest_runnable_snapshot(records, report)
                        if restored:
                            return report
                        report.errors.append(
                            f"current CGS {current_hash[:8]} has no valid persisted ExecutionPlan"
                        )
                return report
            except CGSLoadError as exc:
                if self._main_file.exists():
                    report.errors.append(str(exc))

            if not records:
                return report

            self._restore_latest_runnable_snapshot(records, report)
            return report

    # ── Save ──────────────────────────────────────────────────────────────────

    def save(self, cgs: dict[str, Any]) -> None:
        """
        Atomically saves the CGS to the main file.
        Writes to a temp file, syncs, then renames.
        """
        with self.cgs_write_lock():
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
        with self.cgs_write_lock():
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
        with self.cgs_write_lock():
            index, rebuilt = self._verified_snapshot_index()
            if rebuilt:
                self._save_index(index)
        return index[:limit]

    # ── ExecutionPlan storage (Phase 14.5) ────────────────────────────────────

    PLANS_DIR = "execution_plans"
    PROOF_DIR = "proof"
    SGC_PROOF_DIR = "sgc"

    @property
    def _plans_dir(self) -> Path:
        d = self._xace_dir / self.PLANS_DIR
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_execution_plan(
        self,
        cgs_hash: str,
        plan_json: str,
        *,
        cgs: dict[str, Any] | None = None,
        validation: dict[str, Any] | None = None,
    ) -> str:
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

        Returns
        -------
        str
            Exact canonical JSON text written to disk.
        """
        if cgs is not None:
            try:
                self._validate(cgs)
            except CGSLoadError as exc:
                raise CGSSaveError(str(exc)) from exc
            metadata = cgs.get("metadata", {}) if isinstance(cgs.get("metadata"), dict) else {}
            if str(metadata.get("cgs_hash") or "") != cgs_hash:
                raise CGSSaveError(
                    "CGS schema validation failed before SGC input: "
                    "metadata.cgs_hash must match the ExecutionPlan storage hash"
                )
        plan_path = self._plans_dir / f"{cgs_hash}.plan.json"
        try:
            validate_persisted_execution_plan_contract(
                cgs_hash,
                plan_json,
                storage_path=plan_path,
            )
            persisted_plan_json = _canonical_persisted_execution_plan_json(
                cgs_hash,
                plan_json,
                cgs=cgs,
                validation=validation,
            )
            validate_persisted_execution_plan_contract(
                cgs_hash,
                persisted_plan_json,
                storage_path=plan_path,
                require_persistence_metadata=True,
            )
        except SgcExecutionPlanContractError as exc:
            raise CGSSaveError(f"ExecutionPlan contract validation failed: {exc}") from exc
        except CGSLoadError as exc:
            raise CGSSaveError(str(exc)) from exc
        if plan_path.exists():
            try:
                existing = plan_path.read_text(encoding="utf-8")
            except OSError as exc:
                raise CGSSaveError(f"Cannot read existing ExecutionPlan: {exc}") from exc
            if existing == persisted_plan_json:
                log.debug("ExecutionPlan already exists for hash=%s with identical bytes", cgs_hash[:8])
                return persisted_plan_json
            raise CGSSaveError(
                "Existing ExecutionPlan bytes differ for immutable CGS hash "
                f"{cgs_hash[:8]}; regenerate under a new CGS hash instead of overwriting."
            )
        try:
            self._atomic_write_text(plan_path, persisted_plan_json)
            log.info("ExecutionPlan saved: hash=%s bytes=%d", cgs_hash[:8], len(persisted_plan_json))
        except OSError as exc:
            raise CGSSaveError(f"Cannot save ExecutionPlan: {exc}") from exc
        return persisted_plan_json

    def save_sgc_proof_bundle(
        self,
        cgs: dict[str, Any],
        plan_json: str,
        validation: dict[str, Any] | None = None,
    ) -> Path:
        """
        Writes the SGC proof bundle for one compiled CGS hash.

        Stored at:
            .xace/proof/sgc/<cgs_hash>/

        Files:
            input.json     exact CLI input shape reconstructed from CGS
            plan.json      ExecutionPlan JSON emitted by SGC
            metadata.json  schema version, CGS hash, plan hash, input hash
        """
        try:
            self._validate(cgs)
        except CGSLoadError as exc:
            raise CGSSaveError(str(exc)) from exc
        metadata = cgs.get("metadata", {}) if isinstance(cgs.get("metadata"), dict) else {}
        cgs_hash = str(metadata.get("cgs_hash") or "")
        if not cgs_hash:
            raise CGSSaveError("Cannot save SGC proof bundle without metadata.cgs_hash")

        cli_input = _sgc_cli_input_from_cgs(cgs)
        plan = _json_or_empty(plan_json)
        plan_hash = str(plan.get("plan_hash") or _sha256_text(_canonical_json(plan)))
        proof_dir = self._xace_dir / self.PROOF_DIR / self.SGC_PROOF_DIR / cgs_hash
        proof_dir.mkdir(parents=True, exist_ok=True)

        self._atomic_write(proof_dir / "input.json", cli_input)
        self._atomic_write(proof_dir / "plan.json", plan if plan else {"raw_plan": plan_json})
        self._atomic_write(proof_dir / "metadata.json", {
            "schema": "xace.sgc.proof.v1",
            "schema_version": str(cli_input.get("schema_version") or ""),
            "cgs_hash": cgs_hash,
            "plan_hash": plan_hash,
            "input_hash": _sha256_text(_canonical_json(cli_input)),
            "plan_json_hash": _sha256_text(_canonical_json(plan) if plan else plan_json),
            "system_count": len(cli_input.get("systems", [])),
            "created_at_epoch": time.time(),
            "validation": validation or {},
            "runtime_tick_path": "Persisted SGC ExecutionPlan loads as the standalone runtime schedule when launched with --require-sgc-plan; non-SGC fixture runs may use the CGS-derived compatibility path.",
        })
        return proof_dir

    def restore_prompt_apply_failure(
        self,
        pre_apply_cgs: dict[str, Any],
        *,
        failed_cgs_hash: str = "",
        transaction_id: str = "",
        reason: str = "",
    ) -> dict[str, Any]:
        """
        Restore the project after a prompt apply fails mid-commit.

        The prompt apply path writes multiple artifacts: main CGS, snapshot,
        execution plan, and SGC proof bundle. If a later write or validation
        fails, this method restores the pre-apply CGS and removes artifacts
        associated with the failed post-apply hash.
        """
        with self.cgs_write_lock():
            report: dict[str, Any] = {
                "schema": "xace.prompt_apply_recovery.v1",
                "transaction_id": transaction_id,
                "reason": str(reason)[:500],
                "restored": False,
                "restored_cgs_hash": str(pre_apply_cgs.get("metadata", {}).get("cgs_hash", "")),
                "failed_cgs_hash": str(failed_cgs_hash or ""),
                "artifacts_removed": {
                    "snapshot": False,
                    "snapshot_index_entry": False,
                    "execution_plan": False,
                    "sgc_proof_bundle": False,
                },
                "errors": [],
            }
            try:
                self._validate(pre_apply_cgs)
                self._atomic_write(self._main_file, pre_apply_cgs)
            except Exception as exc:  # noqa: BLE001 - recovery report must preserve the exact failure.
                report["errors"].append(f"restore_cgs_failed: {exc}")
                return report

            failed_hash = str(failed_cgs_hash or "")
            if failed_hash:
                snapshot_path = self._snapshot_dir / f"{failed_hash}.json"
                report["artifacts_removed"]["snapshot"] = _remove_file_if_exists(
                    snapshot_path,
                    report["errors"],
                )

                before = self._load_index()
                after = [record for record in before if record.cgs_hash != failed_hash]
                if len(after) != len(before):
                    try:
                        self._save_index(after)
                        report["artifacts_removed"]["snapshot_index_entry"] = True
                    except Exception as exc:  # noqa: BLE001
                        report["errors"].append(f"snapshot_index_restore_failed: {exc}")

                plan_path = self._plans_dir / f"{failed_hash}.plan.json"
                report["artifacts_removed"]["execution_plan"] = _remove_file_if_exists(
                    plan_path,
                    report["errors"],
                )

                proof_dir = self._xace_dir / self.PROOF_DIR / self.SGC_PROOF_DIR / failed_hash
                if proof_dir.exists():
                    try:
                        shutil.rmtree(proof_dir)
                        report["artifacts_removed"]["sgc_proof_bundle"] = True
                    except OSError as exc:
                        report["errors"].append(f"sgc_proof_bundle_remove_failed: {exc}")

            report["restored"] = not report["errors"]
            return report

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
        if not self._execution_plan_file_is_valid(cgs_hash, plan_path):
            self.recover()
            if not self._execution_plan_file_is_valid(cgs_hash, plan_path):
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

    def verify_execution_plan(self, cgs_hash: str) -> bool:
        """Returns True only when the persisted ExecutionPlan is runtime-loadable."""
        return self._execution_plan_is_valid_for_hash(cgs_hash)

    # ── Mutation audit + authority IDs ────────────────────────────────────────

    @property
    def audit_dir(self) -> Path:
        return self._audit_dir

    @contextmanager
    def cgs_write_lock(self) -> Iterator[None]:
        """
        Holds the project-local CGS process lock.

        This serializes all writes to game.cgs.json and the snapshot index
        across threads and cooperating Builder processes for this project.
        """
        with self._write_lock:
            self._write_lock_file.parent.mkdir(parents=True, exist_ok=True)
            with self._write_lock_file.open("a+b") as handle:
                _lock_file(handle)
                try:
                    yield
                finally:
                    _unlock_file(handle)

    def next_transaction_id(self) -> str:
        """
        Allocates a project-local monotonically increasing CGS transaction ID.

        The counter is persisted under .xace/audit/ so Builder restarts do not
        reuse IDs.
        """
        with self._audit_lock:
            last = 0
            if self._txn_counter.exists():
                try:
                    raw = json.loads(self._txn_counter.read_text(encoding="utf-8"))
                    last = int(raw.get("last_sequence", 0))
                except (json.JSONDecodeError, OSError, TypeError, ValueError):
                    last = 0
            sequence = last + 1
            self._atomic_write(self._txn_counter, {
                "last_sequence": sequence,
                "last_transaction_id": f"txn-{sequence:012d}",
                "updated_at": time.time(),
            })
            return f"txn-{sequence:012d}"

    def record_mutation_audit(
        self,
        *,
        ledger_entry: dict[str, Any],
        dataset_entry: dict[str, Any],
    ) -> None:
        """Appends one validated mutation to the ledger and rich audit dataset."""
        with self._audit_lock:
            self._append_jsonl(self._audit_ledger, ledger_entry)
            self._append_jsonl(self._audit_dataset, dataset_entry)

    def prompt_history_state(self) -> dict[str, Any]:
        """Returns the durable prompt undo/redo history index."""
        with self._audit_lock:
            return copy.deepcopy(self._load_prompt_history())

    def record_prompt_history_apply(
        self,
        *,
        transaction_id: str,
        pre_cgs_hash: str,
        post_cgs_hash: str,
        summary: str,
        mutation_count: int,
        version_ids: dict[str, Any] | None = None,
        proof_links: dict[str, Any] | None = None,
        typed_operation_provenance: dict[str, Any] | None = None,
        composite_prompt_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Appends one prompt apply to the durable linear undo/redo history.

        If the user applies a new prompt after undoing, the redo tail is
        truncated. If another writer moves the CGS outside the known history,
        the prompt history safely starts a new branch at ``pre_cgs_hash``.
        """
        pre_hash = str(pre_cgs_hash or "")
        post_hash = str(post_cgs_hash or "")
        if not _HASH_RE.fullmatch(pre_hash) or not _HASH_RE.fullmatch(post_hash):
            raise CGSSaveError("Prompt history apply requires valid pre/post CGS hashes.")
        timestamp = time.time()
        with self._audit_lock:
            state = self._load_prompt_history()
            entries = list(state.get("entries") or [])
            cursor = _prompt_history_cursor(state)
            origin = str(state.get("origin_cgs_hash") or "")
            if not origin:
                origin = pre_hash
                state["origin_cgs_hash"] = origin

            expected_current = _prompt_history_hash_at_cursor(state, cursor)
            if expected_current != pre_hash:
                matching_cursor = _prompt_history_cursor_for_hash(state, pre_hash)
                if matching_cursor is None:
                    state = _empty_prompt_history_state(origin_cgs_hash=pre_hash)
                    entries = []
                    cursor = 0
                    state["branch_reset_count"] = 1
                else:
                    cursor = matching_cursor
                    entries = entries[:cursor]
                    state["entries"] = entries
                    state["cursor"] = cursor

            redo_truncated = max(0, len(entries) - cursor)
            if redo_truncated:
                entries = entries[:cursor]

            sequence = int(state.get("next_sequence") or (len(entries) + 1))
            composite_hash = ""
            if isinstance(composite_prompt_plan, dict):
                composite_hash = _sha256_text(_canonical_json(composite_prompt_plan))
            entry = {
                "schema": "xace.prompt_mutation_history_entry.v1",
                "sequence": sequence,
                "transaction_id": str(transaction_id or ""),
                "timestamp": timestamp,
                "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(timestamp)),
                "summary": str(summary or "")[:500],
                "mutation_count": int(mutation_count or 0),
                "pre_cgs_hash": pre_hash,
                "post_cgs_hash": post_hash,
                "redo_entries_truncated": redo_truncated,
                "proof_links": (
                    copy.deepcopy(proof_links)
                    if isinstance(proof_links, dict)
                    else self._prompt_history_proof_links(post_hash, transaction_id=str(transaction_id or ""))
                ),
                "undo_target_proof_links": self._prompt_history_proof_links(pre_hash, transaction_id=str(transaction_id or "")),
                "version_ids": copy.deepcopy(version_ids) if isinstance(version_ids, dict) else {},
                "typed_operation_provenance": copy.deepcopy(typed_operation_provenance) if isinstance(typed_operation_provenance, dict) else {},
                "composite_prompt_plan_hash": composite_hash,
            }
            entries.append(entry)
            state["entries"] = entries
            state["cursor"] = len(entries)
            state["next_sequence"] = sequence + 1
            state["updated_at"] = timestamp
            state["last_entry"] = copy.deepcopy(entry)
            state["history_hash"] = _prompt_history_hash(state)
            self._save_prompt_history(state)
            return copy.deepcopy(entry)

    def plan_prompt_history_restore(
        self,
        action: str,
        *,
        current_cgs_hash: str,
        require_proof: bool = True,
    ) -> dict[str, Any]:
        """Plans one prompt undo or redo without mutating project state."""
        normalized_action = str(action or "").lower()
        if normalized_action not in {"undo", "redo"}:
            return _prompt_history_rejected(normalized_action, "action must be 'undo' or 'redo'")
        current_hash = str(current_cgs_hash or "")
        with self._audit_lock:
            state = self._load_prompt_history()
            entries = list(state.get("entries") or [])
            cursor = _prompt_history_cursor(state)
            expected_current = _prompt_history_hash_at_cursor(state, cursor)
            if not entries:
                return _prompt_history_rejected(normalized_action, "No prompt mutations are recorded.", state)
            if current_hash != expected_current:
                return _prompt_history_rejected(
                    normalized_action,
                    "Current CGS hash does not match the prompt history cursor.",
                    state,
                )
            if normalized_action == "undo":
                if cursor <= 0:
                    return _prompt_history_rejected("undo", "No earlier prompt mutation state is available.", state)
                entry = entries[cursor - 1]
                source_hash = str(entry.get("post_cgs_hash") or "")
                target_hash = str(entry.get("pre_cgs_hash") or "")
                target_cursor = cursor - 1
            else:
                if cursor >= len(entries):
                    return _prompt_history_rejected("redo", "No later prompt mutation state is available.", state)
                entry = entries[cursor]
                source_hash = str(entry.get("pre_cgs_hash") or "")
                target_hash = str(entry.get("post_cgs_hash") or "")
                target_cursor = cursor + 1

            proof_status = self._prompt_history_proof_status(target_hash)
            if not proof_status["snapshot_available"]:
                return _prompt_history_rejected(normalized_action, "Target prompt snapshot is missing.", state, proof_status)
            if require_proof and not proof_status["execution_plan_available"]:
                return _prompt_history_rejected(normalized_action, "Target prompt ExecutionPlan is missing or invalid.", state, proof_status)
            if require_proof and not proof_status["sgc_proof_bundle_available"]:
                return _prompt_history_rejected(normalized_action, "Target prompt SGC proof bundle is missing or invalid.", state, proof_status)
            plan = {
                "schema": "xace.prompt_history_restore_plan.v1",
                "accepted": True,
                "action": normalized_action,
                "cursor_before": cursor,
                "cursor_after": target_cursor,
                "entry_sequence": int(entry.get("sequence") or 0),
                "entry_transaction_id": str(entry.get("transaction_id") or ""),
                "source_cgs_hash": source_hash,
                "target_cgs_hash": target_hash,
                "current_cgs_hash": current_hash,
                "proof_links": self._prompt_history_proof_links(target_hash, transaction_id=str(entry.get("transaction_id") or "")),
                "proof_status": proof_status,
                "history_hash_before": _prompt_history_hash(state),
            }
            return copy.deepcopy(plan)

    def complete_prompt_history_restore(
        self,
        restore_plan: dict[str, Any],
        *,
        transaction_id: str,
    ) -> dict[str, Any]:
        """Commits the cursor move after the caller has restored the snapshot."""
        if not isinstance(restore_plan, dict) or restore_plan.get("accepted") is not True:
            raise CGSSaveError("Cannot complete an unaccepted prompt history restore plan.")
        timestamp = time.time()
        with self._audit_lock:
            state = self._load_prompt_history()
            cursor_before = _prompt_history_cursor(state)
            expected_before_raw = restore_plan.get("cursor_before")
            expected_before = int(expected_before_raw) if expected_before_raw is not None else -1
            if cursor_before != expected_before:
                raise CGSSaveError("Prompt history cursor changed before restore completion.")
            cursor_after_raw = restore_plan.get("cursor_after")
            cursor_after = int(cursor_after_raw) if cursor_after_raw is not None else -1
            entries = list(state.get("entries") or [])
            if cursor_after < 0 or cursor_after > len(entries):
                raise CGSSaveError("Prompt history restore target cursor is out of range.")
            state["cursor"] = cursor_after
            state["updated_at"] = timestamp
            event = {
                "schema": "xace.prompt_history_restore_event.v1",
                "transaction_id": str(transaction_id or ""),
                "timestamp": timestamp,
                "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(timestamp)),
                "action": str(restore_plan.get("action") or ""),
                "cursor_before": cursor_before,
                "cursor_after": cursor_after,
                "source_cgs_hash": str(restore_plan.get("source_cgs_hash") or ""),
                "target_cgs_hash": str(restore_plan.get("target_cgs_hash") or ""),
                "entry_sequence": int(restore_plan.get("entry_sequence") or 0),
                "proof_links": copy.deepcopy(restore_plan.get("proof_links") if isinstance(restore_plan.get("proof_links"), dict) else {}),
                "proof_status": copy.deepcopy(restore_plan.get("proof_status") if isinstance(restore_plan.get("proof_status"), dict) else {}),
            }
            state["last_restore"] = copy.deepcopy(event)
            state["history_hash"] = _prompt_history_hash(state)
            self._save_prompt_history(state)
            self._append_jsonl(self._prompt_history_events, event)
            return copy.deepcopy(event)

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _validate(cgs: Any) -> None:
        """Raises CGSLoadError if the CGS is structurally invalid."""
        issues = _validate_cgs_schema(cgs)
        if issues:
            raise CGSLoadError(
                "CGS schema validation failed before SGC input: " + "; ".join(issues)
            )

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

    @staticmethod
    def _atomic_write_text(path: Path, text: str) -> None:
        """Write exact text atomically: temp -> sync -> rename."""
        dir_path = path.parent
        try:
            fd, tmp_path = tempfile.mkstemp(
                prefix=".xace_tmp_",
                suffix=".json",
                dir=str(dir_path),
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                    f.write(text)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, str(path))
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except OSError as exc:
            raise CGSSaveError(f"Cannot write to {path}: {exc}") from exc

    def _save_index(self, records: list[SnapshotRecord]) -> None:
        data = [r.to_dict() for r in records]
        self._atomic_write(self._index_file, {"snapshots": data})

    @staticmethod
    def _append_jsonl(path: Path, data: dict[str, Any]) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
        except OSError as exc:
            raise CGSSaveError(f"Cannot append audit record to {path}: {exc}") from exc

    def _load_prompt_history(self) -> dict[str, Any]:
        if not self._prompt_history_file.exists():
            return _empty_prompt_history_state()
        try:
            raw = json.loads(self._prompt_history_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return _empty_prompt_history_state()
        if not isinstance(raw, dict) or raw.get("schema") != "xace.prompt_mutation_history.v1":
            return _empty_prompt_history_state()
        entries = raw.get("entries")
        if not isinstance(entries, list):
            raw["entries"] = []
        cursor = _prompt_history_cursor(raw)
        raw["cursor"] = min(cursor, len(raw.get("entries") or []))
        raw.setdefault("origin_cgs_hash", "")
        raw.setdefault("next_sequence", len(raw.get("entries") or []) + 1)
        raw.setdefault("branch_reset_count", 0)
        raw["can_undo"] = raw["cursor"] > 0
        raw["can_redo"] = raw["cursor"] < len(raw.get("entries") or [])
        raw["current_cgs_hash"] = _prompt_history_hash_at_cursor(raw, raw["cursor"])
        raw["history_hash"] = _prompt_history_hash(raw)
        return raw

    def _save_prompt_history(self, state: dict[str, Any]) -> None:
        state = copy.deepcopy(state)
        state["can_undo"] = _prompt_history_cursor(state) > 0
        state["can_redo"] = _prompt_history_cursor(state) < len(state.get("entries") or [])
        state["current_cgs_hash"] = _prompt_history_hash_at_cursor(state, _prompt_history_cursor(state))
        state["history_hash"] = _prompt_history_hash(state)
        self._atomic_write(self._prompt_history_file, state)

    def _prompt_history_proof_status(self, cgs_hash: str) -> dict[str, Any]:
        target_hash = str(cgs_hash or "")
        snapshot_path = self._snapshot_dir / f"{target_hash}.json"
        plan_path = self._plans_dir / f"{target_hash}.plan.json"
        proof_dir = self._xace_dir / self.PROOF_DIR / self.SGC_PROOF_DIR / target_hash
        return {
            "schema": "xace.prompt_history_proof_status.v1",
            "cgs_hash": target_hash,
            "snapshot_available": bool(target_hash and snapshot_path.exists()),
            "execution_plan_available": self._execution_plan_file_is_valid(target_hash, plan_path),
            "sgc_proof_bundle_available": self._sgc_proof_bundle_is_valid(target_hash, proof_dir),
            "snapshot_path": f".xace/snapshots/{target_hash}.json" if target_hash else "",
            "execution_plan_path": f".xace/execution_plans/{target_hash}.plan.json" if target_hash else "",
            "sgc_proof_bundle_path": f".xace/proof/sgc/{target_hash}" if target_hash else "",
        }

    def _prompt_history_proof_links(self, cgs_hash: str, *, transaction_id: str = "") -> dict[str, Any]:
        target_hash = str(cgs_hash or "")
        status = self._prompt_history_proof_status(target_hash)
        return {
            "schema": "xace.prompt_history.proof_links.v1",
            "project_root": str(self._root),
            "transaction_id": str(transaction_id or ""),
            "cgs_hash": target_hash,
            "snapshot": status["snapshot_path"],
            "execution_plan": {
                "available": bool(status["execution_plan_available"]),
                "path": status["execution_plan_path"],
            },
            "sgc_proof_bundle": {
                "available": bool(status["sgc_proof_bundle_available"]),
                "path": status["sgc_proof_bundle_path"],
            },
            "audit_dataset": ".xace/audit/mutations.jsonl",
            "history": ".xace/audit/prompt_history.json",
            "history_events": ".xace/audit/prompt_history_events.jsonl",
        }

    def _load_index(self) -> list[SnapshotRecord]:
        if not self._index_file.exists():
            return []
        try:
            raw = json.loads(self._index_file.read_text(encoding="utf-8"))
            items = raw if isinstance(raw, list) else raw.get("snapshots", [])
            return [SnapshotRecord.from_dict(r) for r in items]
        except (json.JSONDecodeError, KeyError, TypeError, OSError):
            return []

    def _verified_snapshot_index(self) -> tuple[list[SnapshotRecord], bool]:
        loaded = self._load_index()
        rebuilt = False
        valid_by_hash: dict[str, SnapshotRecord] = {}

        for record in loaded:
            if self._snapshot_record_is_valid(record):
                valid_by_hash[record.cgs_hash] = record
            else:
                rebuilt = True

        for snap_path in self._snapshot_dir.glob("*.json"):
            cgs_hash = snap_path.stem
            try:
                cgs = self._read_cgs_file(snap_path, "snapshot")
            except CGSLoadError:
                rebuilt = True
                continue
            meta = cgs.get("metadata", {})
            if str(meta.get("cgs_hash", "")) != cgs_hash:
                rebuilt = True
                continue
            if cgs_hash not in valid_by_hash:
                rebuilt = True
                valid_by_hash[cgs_hash] = SnapshotRecord(
                    cgs_hash=cgs_hash,
                    schema_version=str(meta.get("schema_version") or meta.get("version") or "0.0.0"),
                    turn_index=0,
                    mutation_count=0,
                    timestamp=snap_path.stat().st_mtime,
                    summary="Recovered from snapshot file",
                )

        records = sorted(
            valid_by_hash.values(),
            key=lambda record: (record.timestamp, record.cgs_hash),
            reverse=True,
        )
        if len(records) != len(loaded):
            rebuilt = True
        return records[:100], rebuilt

    def _snapshot_record_is_valid(self, record: SnapshotRecord) -> bool:
        snap_path = self._snapshot_dir / f"{record.cgs_hash}.json"
        if not snap_path.exists():
            return False
        try:
            cgs = self._read_cgs_file(snap_path, "snapshot")
        except CGSLoadError:
            return False
        return str(cgs.get("metadata", {}).get("cgs_hash", "")) == record.cgs_hash

    def _recover_execution_plan_files(self, report: CGSRecoveryReport) -> None:
        plans_dir = self._xace_dir / self.PLANS_DIR
        if plans_dir.exists():
            for plan_path in sorted(plans_dir.glob("*.plan.json")):
                cgs_hash = plan_path.name.removesuffix(".plan.json")
                if not _HASH_RE.fullmatch(cgs_hash):
                    continue
                if self._execution_plan_file_is_valid(cgs_hash, plan_path):
                    continue
                if self._repair_execution_plan_from_proof(cgs_hash, plan_path):
                    report.execution_plans_repaired += 1
                    continue
                if _remove_file_if_exists(plan_path, _recovery_errors(report)):
                    report.execution_plans_removed += 1
        self._recover_sgc_proof_bundles(report)

    def _repair_execution_plan_from_proof(self, cgs_hash: str, plan_path: Path) -> bool:
        proof_plan_path = self._xace_dir / self.PROOF_DIR / self.SGC_PROOF_DIR / cgs_hash / "plan.json"
        if not proof_plan_path.exists():
            return False
        try:
            raw = proof_plan_path.read_text(encoding="utf-8")
            plan = json.loads(raw)
        except (json.JSONDecodeError, OSError):
            return False
        if not isinstance(plan, dict):
            return False
        canonical = _canonical_json(plan)
        if not self._execution_plan_text_is_valid(cgs_hash, canonical, plan_path):
            return False
        self._atomic_write_text(plan_path, canonical)
        return True

    def _recover_sgc_proof_bundles(self, report: CGSRecoveryReport) -> None:
        proof_root = self._xace_dir / self.PROOF_DIR / self.SGC_PROOF_DIR
        if not proof_root.exists():
            return
        for proof_dir in sorted(path for path in proof_root.iterdir() if path.is_dir()):
            cgs_hash = proof_dir.name
            if not _HASH_RE.fullmatch(cgs_hash):
                continue
            if self._sgc_proof_bundle_is_valid(cgs_hash, proof_dir):
                continue
            try:
                shutil.rmtree(proof_dir)
                report.proof_bundles_removed += 1
            except OSError as exc:
                _recovery_errors(report).append(f"sgc_proof_bundle_remove_failed:{cgs_hash[:8]}:{exc}")

    def _sgc_proof_bundle_is_valid(self, cgs_hash: str, proof_dir: Path) -> bool:
        required = [proof_dir / "input.json", proof_dir / "plan.json", proof_dir / "metadata.json"]
        if any(not path.exists() for path in required):
            return False
        try:
            input_json = json.loads((proof_dir / "input.json").read_text(encoding="utf-8"))
            plan_json = json.loads((proof_dir / "plan.json").read_text(encoding="utf-8"))
            metadata = json.loads((proof_dir / "metadata.json").read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False
        if not all(isinstance(value, dict) for value in (input_json, plan_json, metadata)):
            return False
        plan_hash = str(plan_json.get("plan_hash") or "")
        return (
            input_json.get("cgs_hash") == cgs_hash
            and plan_json.get("compiled_from_cgs_hash") == cgs_hash
            and metadata.get("cgs_hash") == cgs_hash
            and metadata.get("plan_hash") == plan_hash
        )

    def _execution_plan_is_valid_for_hash(self, cgs_hash: str) -> bool:
        if not cgs_hash:
            return False
        plan_path = self._xace_dir / self.PLANS_DIR / f"{cgs_hash}.plan.json"
        return self._execution_plan_file_is_valid(cgs_hash, plan_path)

    def _execution_plan_file_is_valid(self, cgs_hash: str, plan_path: Path) -> bool:
        if not plan_path.exists():
            return False
        try:
            text = plan_path.read_text(encoding="utf-8")
        except OSError:
            return False
        return self._execution_plan_text_is_valid(cgs_hash, text, plan_path)

    @staticmethod
    def _execution_plan_text_is_valid(cgs_hash: str, text: str, plan_path: Path) -> bool:
        try:
            validate_persisted_execution_plan_contract(
                cgs_hash,
                text,
                storage_path=plan_path,
                require_persistence_metadata=True,
            )
            return True
        except SgcExecutionPlanContractError:
            return False

    def _restore_latest_runnable_snapshot(
        self,
        records: list[SnapshotRecord],
        report: CGSRecoveryReport,
    ) -> bool:
        for record in records:
            try:
                snapshot_cgs = self.load_snapshot(record.cgs_hash)
                if (
                    self._cgs_requires_execution_plan(snapshot_cgs)
                    and not self._execution_plan_is_valid_for_hash(record.cgs_hash)
                ):
                    continue
                self._atomic_write(self._main_file, snapshot_cgs)
                report.restored_cgs_hash = record.cgs_hash
                return True
            except (CGSLoadError, CGSSaveError) as exc:
                report.errors.append(f"snapshot_restore_failed:{record.cgs_hash[:8]}:{exc}")
        return False

    @staticmethod
    def _cgs_requires_execution_plan(cgs: dict[str, Any]) -> bool:
        if cgs.get("global_systems"):
            return True
        for mode in cgs.get("modes", []):
            if isinstance(mode, dict) and mode.get("systems"):
                return True
        return False

    def _cleanup_temp_files(self) -> int:
        removed = 0
        directories = [
            self._root,
            self._xace_dir,
            self._snapshot_dir,
            self._audit_dir,
            self._xace_dir / self.PLANS_DIR,
            self._xace_dir / self.PROOF_DIR / self.SGC_PROOF_DIR,
        ]
        proof_root = self._xace_dir / self.PROOF_DIR / self.SGC_PROOF_DIR
        if proof_root.exists():
            directories.extend(path for path in proof_root.iterdir() if path.is_dir())
        for directory in directories:
            if not directory.exists():
                continue
            for path in directory.glob(".xace_tmp_*.json"):
                try:
                    path.unlink()
                    removed += 1
                except OSError as exc:
                    log.warning("Cannot remove stale CGS temp file %s: %s", path, exc)
        return removed

    def _read_cgs_file(self, path: Path, label: str) -> dict[str, Any]:
        if not path.exists():
            raise CGSLoadError(f"{label} not found: {path}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CGSLoadError(f"{label} is invalid JSON: {exc}") from exc
        except OSError as exc:
            raise CGSLoadError(f"Cannot read {label}: {exc}") from exc
        self._validate(data)
        return data

    def __repr__(self) -> str:
        return f"CGSPersistence(root={self._root!r})"


def _remove_file_if_exists(path: Path, errors: list[str]) -> bool:
    if not path.exists():
        return False
    try:
        path.unlink()
        return True
    except OSError as exc:
        errors.append(f"remove_failed:{path.name}: {exc}")
        return False


def _empty_prompt_history_state(*, origin_cgs_hash: str = "") -> dict[str, Any]:
    return {
        "schema": "xace.prompt_mutation_history.v1",
        "origin_cgs_hash": str(origin_cgs_hash or ""),
        "current_cgs_hash": str(origin_cgs_hash or ""),
        "cursor": 0,
        "entries": [],
        "next_sequence": 1,
        "can_undo": False,
        "can_redo": False,
        "branch_reset_count": 0,
        "updated_at": 0.0,
        "history_hash": "",
    }


def _prompt_history_cursor(state: dict[str, Any]) -> int:
    try:
        cursor = int(state.get("cursor") or 0)
    except (TypeError, ValueError):
        cursor = 0
    entries = state.get("entries")
    length = len(entries) if isinstance(entries, list) else 0
    return max(0, min(cursor, length))


def _prompt_history_hash_at_cursor(state: dict[str, Any], cursor: int) -> str:
    entries = state.get("entries")
    if not isinstance(entries, list) or cursor <= 0:
        return str(state.get("origin_cgs_hash") or "")
    if cursor >= len(entries):
        cursor = len(entries)
    entry = entries[cursor - 1]
    if not isinstance(entry, dict):
        return ""
    return str(entry.get("post_cgs_hash") or "")


def _prompt_history_cursor_for_hash(state: dict[str, Any], cgs_hash: str) -> int | None:
    target = str(cgs_hash or "")
    if target == str(state.get("origin_cgs_hash") or ""):
        return 0
    entries = state.get("entries")
    if not isinstance(entries, list):
        return None
    for index, entry in enumerate(entries, start=1):
        if isinstance(entry, dict) and str(entry.get("post_cgs_hash") or "") == target:
            return index
    return None


def _prompt_history_hash(state: dict[str, Any]) -> str:
    payload = copy.deepcopy(state)
    payload.pop("history_hash", None)
    payload.pop("updated_at", None)
    payload.pop("last_restore", None)
    return _sha256_text(_canonical_json(payload))


def _prompt_history_rejected(
    action: str,
    reason: str,
    state: dict[str, Any] | None = None,
    proof_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": "xace.prompt_history_restore_plan.v1",
        "accepted": False,
        "action": str(action or ""),
        "reason": str(reason or ""),
        "cursor": _prompt_history_cursor(state) if isinstance(state, dict) else 0,
        "can_undo": bool(state.get("can_undo")) if isinstance(state, dict) else False,
        "can_redo": bool(state.get("can_redo")) if isinstance(state, dict) else False,
        "current_cgs_hash": str(state.get("current_cgs_hash") or "") if isinstance(state, dict) else "",
        "proof_status": copy.deepcopy(proof_status) if isinstance(proof_status, dict) else {},
    }


def _recovery_errors(report: CGSRecoveryReport) -> list[str]:
    if report.errors is None:
        report.errors = []
    return report.errors


def _validate_cgs_schema(cgs: Any) -> list[str]:
    issues: list[str] = []
    if not isinstance(cgs, dict):
        return ["top-level JSON value must be an object"]

    missing_top = sorted(_REQUIRED_TOP_LEVEL_KEYS - set(cgs.keys()))
    if missing_top:
        issues.append(f"missing top-level fields: {missing_top}")

    metadata = cgs.get("metadata")
    metadata_schema_version = ""
    if not isinstance(metadata, dict):
        issues.append("metadata must be an object")
        metadata = {}
    else:
        missing_meta = sorted(_REQUIRED_METADATA_KEYS - set(metadata.keys()))
        if missing_meta:
            issues.append(f"metadata missing required fields: {missing_meta}")
        _require_nonempty_string(metadata.get("name"), "metadata.name", issues)
        _require_semver(metadata.get("version"), "metadata.version", issues)
        metadata_schema_version = _require_semver(
            metadata.get("schema_version"),
            "metadata.schema_version",
            issues,
        ) or ""
        cgs_hash = _require_nonempty_string(metadata.get("cgs_hash"), "metadata.cgs_hash", issues)
        if cgs_hash and (not _HASH_RE.fullmatch(cgs_hash) or cgs_hash == "0" * 64):
            issues.append("metadata.cgs_hash must be a lowercase 64-character SHA-256 digest")
        if "execution_plan_version" in metadata:
            _require_positive_int(metadata.get("execution_plan_version"), "metadata.execution_plan_version", issues)
        _validate_optional_metadata_extensions(cgs, metadata, issues)

    global_systems = _require_array(cgs.get("global_systems"), "global_systems", issues)
    modes = _require_array(cgs.get("modes"), "modes", issues)

    declared_components = dict(_RESERVED_COMPONENT_TYPE_IDS)
    _validate_component_schemas(cgs.get("component_schemas"), declared_components, issues)
    _validate_modes(modes, metadata_schema_version, declared_components, issues)
    _validate_systems(global_systems, modes, declared_components, issues)
    return issues


def _validate_component_schemas(
    component_schemas: Any,
    declared_components: dict[int, str],
    issues: list[str],
) -> None:
    if component_schemas is None:
        return
    if not isinstance(component_schemas, list):
        issues.append("component_schemas must be an array when present")
        return

    schema_type_ids: set[int] = set()
    for schema_index, schema in enumerate(component_schemas):
        schema_path = f"component_schemas[{schema_index}]"
        if not isinstance(schema, dict):
            issues.append(f"{schema_path} must be an object")
            continue
        type_id = schema.get("type_id")
        if not isinstance(type_id, int) or type_id < 1:
            issues.append(f"{schema_path}.type_id must be a positive component type ID")
            continue
        if type_id in schema_type_ids:
            issues.append(f"component_schemas declares duplicate component type_id {type_id}")
        schema_type_ids.add(type_id)

        name = _require_nonempty_string(schema.get("name"), f"{schema_path}.name", issues)
        if name:
            previous_name = declared_components.get(type_id)
            if previous_name is not None and previous_name != name:
                issues.append(
                    f"{schema_path} component type_id {type_id} name {name!r} conflicts with {previous_name!r}"
                )
            else:
                declared_components[type_id] = name
        if not isinstance(schema.get("defaults"), dict):
            issues.append(f"{schema_path}.defaults must be an object")
        if "source" in schema and (
            not isinstance(schema.get("source"), str) or not schema["source"].strip()
        ):
            issues.append(f"{schema_path}.source must be a non-empty string when present")


def _validate_modes(
    modes: list[Any],
    metadata_schema_version: str,
    declared_components: dict[int, str],
    issues: list[str],
) -> None:
    if not modes:
        issues.append("modes must contain at least one mode")
        return

    mode_ids: set[str] = set()
    actor_ids: dict[str, str] = {}
    default_count = 0
    for mode_index, mode in enumerate(modes):
        mode_path = f"modes[{mode_index}]"
        if not isinstance(mode, dict):
            issues.append(f"{mode_path} must be an object")
            continue
        mode_id = _require_nonempty_string(mode.get("id"), f"{mode_path}.id", issues) or ""
        if mode_id:
            if mode_id in mode_ids:
                issues.append(f"duplicate mode id {mode_id!r}")
            mode_ids.add(mode_id)

        mode_schema_version = _require_semver(mode.get("schema_version"), f"{mode_path}.schema_version", issues)
        if mode_schema_version and metadata_schema_version and mode_schema_version != metadata_schema_version:
            issues.append(
                f"{mode_path}.schema_version {mode_schema_version!r} does not match metadata.schema_version {metadata_schema_version!r}"
            )

        if not isinstance(mode.get("is_default"), bool):
            issues.append(f"{mode_path}.is_default must be boolean")
        elif mode["is_default"]:
            default_count += 1

        actors = _require_array(mode.get("actors"), f"{mode_path}.actors", issues)
        _require_array(mode.get("systems"), f"{mode_path}.systems", issues)
        rules = _require_array(mode.get("rules"), f"{mode_path}.rules", issues)
        _validate_actors(actors, mode_path, actor_ids, declared_components, issues)
        _validate_rules(rules, mode_path, issues)

    if default_count != 1:
        issues.append(f"exactly one mode must have is_default=true; found {default_count}")


def _validate_actors(
    actors: list[Any],
    mode_path: str,
    actor_ids: dict[str, str],
    declared_components: dict[int, str],
    issues: list[str],
) -> None:
    mode_actor_ids: set[str] = set()
    for actor_index, actor in enumerate(actors):
        actor_path = f"{mode_path}.actors[{actor_index}]"
        if not isinstance(actor, dict):
            issues.append(f"{actor_path} must be an object")
            continue
        actor_id = _require_nonempty_string(actor.get("id"), f"{actor_path}.id", issues) or ""
        if actor_id:
            if actor_id in mode_actor_ids:
                issues.append(f"duplicate actor id {actor_id!r} in {mode_path}")
            mode_actor_ids.add(actor_id)
            previous = actor_ids.setdefault(actor_id, actor_path)
            if previous != actor_path:
                issues.append(f"duplicate actor id {actor_id!r} at {previous} and {actor_path}")

        if "spawn_count" in actor:
            _require_positive_int(actor.get("spawn_count"), f"{actor_path}.spawn_count", issues)

        components = _require_array(actor.get("components"), f"{actor_path}.components", issues)
        _validate_components(components, actor_path, declared_components, issues)


def _validate_components(
    components: list[Any],
    actor_path: str,
    declared_components: dict[int, str],
    issues: list[str],
) -> None:
    component_ids: set[int] = set()
    for component_index, component in enumerate(components):
        component_path = f"{actor_path}.components[{component_index}]"
        if not isinstance(component, dict):
            issues.append(f"{component_path} must be an object")
            continue
        type_id = component.get("type_id")
        if not isinstance(type_id, int) or type_id < 1:
            issues.append(f"{component_path}.type_id must be a positive component type ID")
            continue
        if type_id in component_ids:
            issues.append(f"{actor_path} declares duplicate component type_id {type_id}")
        component_ids.add(type_id)

        name = _require_nonempty_string(component.get("name"), f"{component_path}.name", issues)
        if name:
            previous_name = declared_components.get(type_id)
            if previous_name is not None and previous_name != name:
                issues.append(
                    f"{component_path} component type_id {type_id} name {name!r} conflicts with {previous_name!r}"
                )
            else:
                declared_components[type_id] = name
        if not isinstance(component.get("defaults"), dict):
            issues.append(f"{component_path}.defaults must be an object")


def _validate_rules(rules: list[Any], mode_path: str, issues: list[str]) -> None:
    rule_ids: set[str] = set()
    for rule_index, rule in enumerate(rules):
        rule_path = f"{mode_path}.rules[{rule_index}]"
        if not isinstance(rule, dict):
            issues.append(f"{rule_path} must be an object")
            continue
        rule_id = _require_nonempty_string(rule.get("id"), f"{rule_path}.id", issues) or ""
        if rule_id:
            if rule_id in rule_ids:
                issues.append(f"duplicate rule id {rule_id!r} in {mode_path}")
            rule_ids.add(rule_id)
        for field_name in ("condition", "effect"):
            value = rule.get(field_name)
            if not isinstance(value, str) or not value.strip():
                issues.append(f"{rule_path}.{field_name} must be a non-empty string")
        if not isinstance(rule.get("priority"), int):
            issues.append(f"{rule_path}.priority must be an integer")
        if not isinstance(rule.get("is_active"), bool):
            issues.append(f"{rule_path}.is_active must be boolean")


def _validate_systems(
    global_systems: list[Any],
    modes: list[Any],
    declared_components: dict[int, str],
    issues: list[str],
) -> None:
    system_refs: list[tuple[dict[str, Any], str]] = []
    for index, system in enumerate(global_systems):
        if isinstance(system, dict):
            system_refs.append((system, f"global_systems[{index}]"))
        else:
            issues.append(f"global_systems[{index}] must be an object")
    for mode_index, mode in enumerate(modes):
        if not isinstance(mode, dict):
            continue
        systems = mode.get("systems", [])
        if not isinstance(systems, list):
            continue
        for system_index, system in enumerate(systems):
            if isinstance(system, dict):
                system_refs.append((system, f"modes[{mode_index}].systems[{system_index}]"))
            else:
                issues.append(f"modes[{mode_index}].systems[{system_index}] must be an object")

    all_system_ids: set[str] = set()
    system_paths: dict[str, str] = {}
    phase_by_system: dict[str, int] = {}
    dependencies: dict[str, list[str]] = {}
    for system, system_path in system_refs:
        system_id = _require_nonempty_string(system.get("id"), f"{system_path}.id", issues) or ""
        if not system_id:
            continue
        previous = system_paths.setdefault(system_id, system_path)
        if previous != system_path:
            issues.append(f"system id {system_id!r} is declared more than once at {previous} and {system_path}")
        all_system_ids.add(system_id)
        phase = system.get("phase")
        if isinstance(phase, str) and phase in _CANONICAL_PHASES:
            phase_by_system[system_id] = _phase_index(phase)
        raw_depends_on = system.get("depends_on")
        dependencies[system_id] = [
            dep for dep in raw_depends_on if isinstance(dep, str)
        ] if isinstance(raw_depends_on, list) else []

    for system, system_path in system_refs:
        system_id = str(system.get("id") or "<empty>")
        phase = system.get("phase")
        if not isinstance(phase, str) or phase not in _CANONICAL_PHASES:
            issues.append(
                f"{system_path}.phase must be one of {sorted(_CANONICAL_PHASES)}"
            )
        for field_name in ("reads", "writes"):
            values = _require_array(system.get(field_name), f"{system_path}.{field_name}", issues)
            _validate_component_access(values, system_id, system_path, field_name, declared_components, issues)
        depends_on = _require_array(system.get("depends_on"), f"{system_path}.depends_on", issues)
        _validate_depends_on(
            depends_on,
            system_id,
            system_path,
            all_system_ids,
            phase_by_system,
            issues,
        )
        if not isinstance(system.get("deterministic"), bool):
            issues.append(f"{system_path}.deterministic must be boolean")
        if "parallel" in system and not isinstance(system.get("parallel"), bool):
            issues.append(f"{system_path}.parallel must be boolean when present")
        if "runtime_executor" in system and not isinstance(system.get("runtime_executor"), dict):
            issues.append(f"{system_path}.runtime_executor must be an object when present")
    _validate_dependency_cycles(dependencies, issues)


def _validate_component_access(
    values: list[Any],
    system_id: str,
    system_path: str,
    field_name: str,
    declared_components: dict[int, str],
    issues: list[str],
) -> None:
    seen: set[int] = set()
    for value in values:
        if not isinstance(value, int) or value < 1:
            issues.append(f"{system_path}.{field_name} for system {system_id!r} contains invalid component type_id {value!r}")
            continue
        if value in seen:
            issues.append(f"{system_path}.{field_name} for system {system_id!r} contains duplicate component type_id {value}")
        seen.add(value)
        if value not in declared_components:
            issues.append(f"{system_path}.{field_name} for system {system_id!r} references undeclared component type_id {value}")


def _validate_depends_on(
    depends_on: list[Any],
    system_id: str,
    system_path: str,
    all_system_ids: set[str],
    phase_by_system: dict[str, int],
    issues: list[str],
) -> None:
    seen: set[str] = set()
    for dependency in depends_on:
        if not isinstance(dependency, str) or not dependency.strip():
            issues.append(f"{system_path}.depends_on contains an empty system id")
            continue
        dependency_id = dependency.strip()
        if dependency_id in seen:
            issues.append(f"{system_path}.depends_on for system {system_id!r} contains duplicate dependency {dependency_id!r}")
        seen.add(dependency_id)
        if dependency_id == system_id:
            issues.append(f"{system_path}.depends_on for system {system_id!r} references itself")
            continue
        if dependency_id not in all_system_ids:
            issues.append(f"{system_path}.depends_on for system {system_id!r} references unknown system {dependency_id!r}")
            continue
        if phase_by_system.get(dependency_id, 0) > phase_by_system.get(system_id, 0):
            issues.append(f"{system_path}.depends_on for system {system_id!r} points to later-phase system {dependency_id!r}")


def _validate_dependency_cycles(dependencies: dict[str, list[str]], issues: list[str]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()
    reported: set[str] = set()

    def visit(system_id: str, stack: list[str]) -> None:
        if system_id in visited:
            return
        if system_id in visiting:
            if system_id in stack:
                start = stack.index(system_id)
                cycle = stack[start:] + [system_id]
                display = " -> ".join(cycle)
                if display not in reported:
                    issues.append(f"system dependency cycle detected: {display}")
                    reported.add(display)
            return
        visiting.add(system_id)
        stack.append(system_id)
        for dependency in dependencies.get(system_id, []):
            if dependency in dependencies:
                visit(dependency, stack)
        stack.pop()
        visiting.remove(system_id)
        visited.add(system_id)

    for system_id in sorted(dependencies):
        visit(system_id, [])


def _validate_optional_metadata_extensions(
    cgs: dict[str, Any],
    metadata: dict[str, Any],
    issues: list[str],
) -> None:
    if "semantic_bindings" in cgs and not isinstance(cgs.get("semantic_bindings"), dict):
        issues.append("semantic_bindings must be an object when present")
    if "assets" in cgs:
        _validate_assets(cgs.get("assets"), "assets", issues)
    if "assets" in metadata:
        _validate_assets(metadata.get("assets"), "metadata.assets", issues)
    if "networking" in metadata:
        _validate_networking(metadata.get("networking"), "metadata.networking", issues)
    for key in ("save", "saves", "save_metadata"):
        if key in metadata:
            _validate_save_metadata(metadata.get(key), f"metadata.{key}", issues)


def _validate_assets(value: Any, path: str, issues: list[str]) -> None:
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_asset_entry(item, f"{path}[{index}]", issues)
    elif isinstance(value, dict):
        if "items" in value:
            items = value.get("items")
            if isinstance(items, list):
                for index, item in enumerate(items):
                    _validate_asset_entry(item, f"{path}.items[{index}]", issues)
            else:
                issues.append(f"{path}.items must be an array when present")
    else:
        issues.append(f"{path} must be an object or array when present")


def _validate_asset_entry(value: Any, path: str, issues: list[str]) -> None:
    if not isinstance(value, dict):
        issues.append(f"{path} must be an object")
        return
    for field_name in ("id", "asset_type", "status", "path", "source_path"):
        if field_name in value and (not isinstance(value[field_name], str) or not value[field_name].strip()):
            issues.append(f"{path}.{field_name} must be a non-empty string")


def _validate_networking(value: Any, path: str, issues: list[str]) -> None:
    if not isinstance(value, dict):
        issues.append(f"{path} must be an object when present")
        return
    for field_name in ("mode", "authority", "status"):
        if field_name in value and (not isinstance(value[field_name], str) or not value[field_name].strip()):
            issues.append(f"{path}.{field_name} must be a non-empty string")
    if "max_players" in value:
        _require_positive_int(value.get("max_players"), f"{path}.max_players", issues)


def _validate_save_metadata(value: Any, path: str, issues: list[str]) -> None:
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_save_metadata(item, f"{path}[{index}]", issues)
        return
    if not isinstance(value, dict):
        issues.append(f"{path} must be an object or array when present")
        return
    if "version" in value:
        _require_semver(value.get("version"), f"{path}.version", issues)
    for field_name in ("strategy", "mode", "backend", "status"):
        if field_name in value and (not isinstance(value[field_name], str) or not value[field_name].strip()):
            issues.append(f"{path}.{field_name} must be a non-empty string")


def _require_array(value: Any, path: str, issues: list[str]) -> list[Any]:
    if isinstance(value, list):
        return value
    issues.append(f"{path} must be an array")
    return []


def _require_nonempty_string(value: Any, path: str, issues: list[str]) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    issues.append(f"{path} must be a non-empty string")
    return ""


def _require_semver(value: Any, path: str, issues: list[str]) -> str:
    text = _require_nonempty_string(value, path, issues)
    if text and not _SEMVER_RE.fullmatch(text):
        issues.append(f"{path} must be a MAJOR.MINOR.PATCH string")
        return ""
    return text


def _require_positive_int(value: Any, path: str, issues: list[str]) -> None:
    if isinstance(value, int) and value >= 1:
        return
    issues.append(f"{path} must be an integer >= 1")


def _phase_index(phase: str) -> int:
    return {
        "Initialization": 0,
        "Input": 1,
        "Simulation": 2,
        "PostSimulation": 3,
        "Cleanup": 4,
    }.get(phase, 0)


def _sgc_cli_input_from_cgs(cgs: dict[str, Any]) -> dict[str, Any]:
    CGSPersistence._validate(cgs)
    metadata = cgs.get("metadata", {}) if isinstance(cgs.get("metadata"), dict) else {}
    systems: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in list(cgs.get("global_systems", [])):
        if isinstance(raw, dict):
            system = _normalize_sgc_system(raw)
            sid = str(system.get("id") or "")
            if sid and sid not in seen:
                systems.append(system)
                seen.add(sid)
    for mode in cgs.get("modes", []):
        if not isinstance(mode, dict):
            continue
        for raw in mode.get("systems", []):
            if isinstance(raw, dict):
                system = _normalize_sgc_system(raw)
                sid = str(system.get("id") or "")
                if sid and sid not in seen:
                    systems.append(system)
                    seen.add(sid)
    return {
        "schema": "xace.sgc.cli.input.v1",
        "schema_version": str(metadata.get("schema_version") or metadata.get("version") or "0.1.0"),
        "plan_version": int(metadata.get("execution_plan_version") or 1),
        "cgs_hash": str(metadata.get("cgs_hash") or ""),
        "systems": systems,
    }


def _canonical_persisted_execution_plan_json(
    cgs_hash: str,
    plan_json: str,
    *,
    cgs: dict[str, Any] | None = None,
    validation: dict[str, Any] | None = None,
) -> str:
    plan = _json_or_empty(plan_json)
    if not plan:
        return _canonical_json({})

    metadata = cgs.get("metadata", {}) if isinstance(cgs, dict) and isinstance(cgs.get("metadata"), dict) else {}
    systems = _normalized_systems_for_plan(cgs, plan)
    persisted = dict(plan)
    persisted["schema_version"] = str(
        metadata.get("schema_version")
        or metadata.get("version")
        or persisted.get("schema_version")
        or ""
    )
    persisted["plan_version"] = _plan_version_for_persisted_plan(metadata, persisted)
    persisted.setdefault("adapter_protocol_version", 1)
    persisted.setdefault("migration_status", "current")
    persisted.setdefault("compiled_from_cgs_hash", cgs_hash)
    if not _has_component_access_sets(persisted.get("component_access_sets")):
        persisted["component_access_sets"] = _component_access_sets_from_systems(systems)
    if not _has_system_metadata(persisted.get("system_metadata")):
        persisted["system_metadata"] = _system_metadata_from_systems(systems)
    if not _has_proof_bundle_ref(persisted.get("proof_bundle"), cgs_hash, str(persisted.get("plan_hash") or "")):
        persisted["proof_bundle"] = _proof_bundle_ref(
            cgs_hash,
            persisted,
            cgs=cgs,
            validation=validation,
        )
    return _canonical_json(persisted)


def _normalized_systems_for_plan(
    cgs: dict[str, Any] | None,
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    if isinstance(cgs, dict):
        return list(_sgc_cli_input_from_cgs(cgs).get("systems", []))
    return _systems_from_plan(plan)


def _systems_from_plan(plan: dict[str, Any]) -> list[dict[str, Any]]:
    systems: dict[str, dict[str, Any]] = {}
    phases = plan.get("phases")
    if not isinstance(phases, dict):
        return []
    for phase_key in sorted(phases, key=str):
        schedule = phases.get(phase_key)
        if not isinstance(schedule, dict):
            continue
        schedule_phase = str(schedule.get("phase") or "Simulation")
        groups = schedule.get("groups")
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            phase = str(group.get("phase") or schedule_phase)
            ids = group.get("systems")
            if not isinstance(ids, list):
                continue
            for system_id in ids:
                sid = str(system_id or "")
                if not sid or sid in systems:
                    continue
                systems[sid] = {
                    "id": sid,
                    "display_name": sid,
                    "phase": phase,
                    "reads": [],
                    "writes": [],
                    "depends_on": [],
                    "deterministic": True,
                    "description": "",
                    "version": {"major": 1, "minor": 0},
                }
    return [systems[sid] for sid in sorted(systems)]


def _plan_version_for_persisted_plan(
    metadata: dict[str, Any],
    plan: dict[str, Any],
) -> int:
    for value in (plan.get("plan_version"), metadata.get("execution_plan_version")):
        if _is_int_like(value):
            parsed = int(value)
            if parsed >= 1:
                return parsed
    return 1


def _component_access_sets_from_systems(systems: list[dict[str, Any]]) -> dict[str, Any]:
    by_system: dict[str, dict[str, list[int]]] = {}
    all_reads: set[int] = set()
    all_writes: set[int] = set()
    for system in sorted(systems, key=lambda item: str(item.get("id") or "")):
        sid = str(system.get("id") or "")
        if not sid:
            continue
        reads = _sorted_ints(system.get("reads"))
        writes = _sorted_ints(system.get("writes"))
        by_system[sid] = {
            "reads": reads,
            "writes": writes,
        }
        all_reads.update(reads)
        all_writes.update(writes)
    return {
        "schema": "xace.sgc.component_access_sets.v1",
        "by_system": by_system,
        "all_reads": sorted(all_reads),
        "all_writes": sorted(all_writes),
        "component_ids": sorted(all_reads | all_writes),
    }


def _system_metadata_from_systems(systems: list[dict[str, Any]]) -> dict[str, Any]:
    entries: dict[str, dict[str, Any]] = {}
    for system in sorted(systems, key=lambda item: str(item.get("id") or "")):
        sid = str(system.get("id") or "")
        if not sid:
            continue
        version = system.get("version") if isinstance(system.get("version"), dict) else {}
        entries[sid] = {
            "display_name": str(system.get("display_name") or sid),
            "phase": str(system.get("phase") or "Simulation"),
            "depends_on": sorted({str(item) for item in system.get("depends_on", []) if str(item)}),
            "deterministic": bool(system.get("deterministic", True)),
            "version": {
                "major": int(version.get("major") or 1),
                "minor": int(version.get("minor") or 0),
            },
            "description": str(system.get("description") or ""),
        }
    return {
        "schema": "xace.sgc.system_metadata.v1",
        "systems": entries,
    }


def _proof_bundle_ref(
    cgs_hash: str,
    plan: dict[str, Any],
    *,
    cgs: dict[str, Any] | None = None,
    validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(cgs, dict):
        cli_input = _sgc_cli_input_from_cgs(cgs)
    else:
        cli_input = {
            "schema": "xace.sgc.cli.input.v1",
            "schema_version": str(plan.get("schema_version") or ""),
            "plan_version": int(plan.get("plan_version") or 1),
            "cgs_hash": cgs_hash,
            "systems": _systems_from_plan(plan),
        }
    validation_report = validation if isinstance(validation, dict) else {}
    return {
        "schema": "xace.sgc.proof_ref.v1",
        "path": f".xace/proof/sgc/{cgs_hash}",
        "compiled_from_cgs_hash": cgs_hash,
        "plan_hash": str(plan.get("plan_hash") or ""),
        "input_hash": _sha256_text(_canonical_json(cli_input)),
        "validation_hash": _sha256_text(_canonical_json(validation_report)),
    }


def _has_component_access_sets(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("schema") == "xace.sgc.component_access_sets.v1"
        and isinstance(value.get("by_system"), dict)
        and isinstance(value.get("all_reads"), list)
        and isinstance(value.get("all_writes"), list)
        and isinstance(value.get("component_ids"), list)
    )


def _has_system_metadata(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("schema") == "xace.sgc.system_metadata.v1"
        and isinstance(value.get("systems"), dict)
    )


def _has_proof_bundle_ref(value: Any, cgs_hash: str, plan_hash: str) -> bool:
    return (
        isinstance(value, dict)
        and value.get("schema") == "xace.sgc.proof_ref.v1"
        and value.get("path") == f".xace/proof/sgc/{cgs_hash}"
        and value.get("compiled_from_cgs_hash") == cgs_hash
        and value.get("plan_hash") == plan_hash
        and isinstance(value.get("input_hash"), str)
        and len(str(value.get("input_hash"))) == 64
        and isinstance(value.get("validation_hash"), str)
        and len(str(value.get("validation_hash"))) == 64
    )


def _sorted_ints(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    return sorted({int(item) for item in value if _is_int_like(item)})


def _normalize_sgc_system(raw: dict[str, Any]) -> dict[str, Any]:
    system = {
        "id": str(raw.get("id") or ""),
        "display_name": str(raw.get("display_name") or raw.get("name") or raw.get("id") or ""),
        "phase": raw.get("phase") or "Simulation",
        "reads": sorted({int(item) for item in raw.get("reads", []) if _is_int_like(item)}),
        "writes": sorted({int(item) for item in raw.get("writes", []) if _is_int_like(item)}),
        "depends_on": sorted({str(item) for item in raw.get("depends_on", []) if str(item)}),
        "deterministic": bool(raw.get("deterministic", True)),
        "description": str(raw.get("description") or ""),
    }
    version = raw.get("version")
    if isinstance(version, dict):
        system["version"] = {
            "major": int(version.get("major") or 1),
            "minor": int(version.get("minor") or 0),
        }
    else:
        system["version"] = {
            "major": int(raw.get("version_major") or 1),
            "minor": int(raw.get("version_minor") or 0),
        }
    return system


def _is_int_like(value: Any) -> bool:
    try:
        int(value)
        return True
    except (TypeError, ValueError):
        return False


def _json_or_empty(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
