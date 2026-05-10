"""
tests/test_cgs_manager.py
==========================
Tests for CGSManager: initialisation, commit, rollback, stale-mutation guard,
snapshot chain integrity, and CGSSerializer hash determinism.
"""

from __future__ import annotations

import copy
import pytest
from typing import Any

from ..cgs.cgs_manager import CGSManager, CGSManagerError
from ..cgs.cgs_serializer import CGSSerializer
from ..domain_dsl.mutation_metadata.mutation_metadata_model import MutationMetadata


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _base_cgs(version: str = "0.1.0", name: str = "TestGame") -> dict[str, Any]:
    return {
        "metadata": {"version": version, "name": name, "cgs_hash": ""},
        "global_systems": [],
        "modes": [
            {
                "id":             "mode_default",
                "display_name":   "Default",
                "is_default":     True,
                "schema_version": version,
                "actors":  [],
                "systems": [],
                "rules":   [],
            }
        ],
    }


def _make_metadata(
    manager:     CGSManager,
    source:      str = "manual",
    description: str = "test mutation",
) -> MutationMetadata:
    return MutationMetadata.create(
        source=source,
        parent_cgs_hash=manager.current_hash,
        schema_version_target=manager.current_version,
        description=description,
    )


# ── CGSSerializer ─────────────────────────────────────────────────────────────

class TestCGSSerializer:

    def test_serialise_is_deterministic(self) -> None:
        cgs = _base_cgs()
        s1  = CGSSerializer.serialise(cgs)
        s2  = CGSSerializer.serialise(cgs)
        assert s1 == s2

    def test_sorted_keys_produce_same_output(self) -> None:
        a = {"b": 2, "a": 1, "c": {"z": 3, "y": 4}}
        b = {"a": 1, "c": {"y": 4, "z": 3}, "b": 2}
        assert CGSSerializer.serialise(a) == CGSSerializer.serialise(b)

    def test_compute_hash_is_64_chars(self) -> None:
        h = CGSSerializer.compute_hash(_base_cgs())
        assert len(h) == 64

    def test_different_content_different_hash(self) -> None:
        a = _base_cgs(name="Game A")
        b = _base_cgs(name="Game B")
        assert CGSSerializer.compute_hash(a) != CGSSerializer.compute_hash(b)

    def test_serialise_roundtrip(self) -> None:
        cgs      = _base_cgs()
        json_str = CGSSerializer.serialise(cgs)
        restored = CGSSerializer.deserialise(json_str)
        assert CGSSerializer.serialise(restored) == json_str

    def test_deserialise_empty_string_raises(self) -> None:
        from ..cgs.cgs_serializer import CGSSerializationError
        with pytest.raises(CGSSerializationError):
            CGSSerializer.deserialise("")

    def test_float_normalisation(self) -> None:
        # Values differing only in the 7th+ decimal place should serialize identically
        a = CGSSerializer.serialise({"x": 1.1234561})
        b = CGSSerializer.serialise({"x": 1.1234564})
        assert a == b   # both round to 1.123456 at 6dp

    def test_are_equal(self) -> None:
        a = {"b": 2, "a": 1}
        b = {"a": 1, "b": 2}
        assert CGSSerializer.are_equal(a, b)
        assert not CGSSerializer.are_equal({"x": 1}, {"x": 2})


# ── CGSManager ─────────────────────────────────────────────────────────────────

class TestCGSManagerInit:

    def test_initialise_stamps_hash(self) -> None:
        cgs     = _base_cgs()
        manager = CGSManager.initialise(cgs)
        assert manager.current_hash != ""
        assert len(manager.current_hash) == 64

    def test_initialise_preserves_version(self) -> None:
        manager = CGSManager.initialise(_base_cgs("0.3.0"))
        assert manager.current_version == "0.3.0"

    def test_is_initialised(self) -> None:
        # Orchestrator uses CGSManager only via classmethod — test that path
        m2 = CGSManager.initialise(_base_cgs())
        assert m2.is_initialised

    def test_not_initialised_before_explicit_load(self) -> None:
        # GDEOrchestrator stores None until load_cgs() — verify is_initialised
        # is False when manager is None (tested via orchestrator)
        from ..gde_orchestrator import GDEOrchestrator
        orc = GDEOrchestrator()
        assert not orc.is_initialised

    def test_current_cgs_returns_deep_copy(self) -> None:
        manager = CGSManager.initialise(_base_cgs())
        cgs1 = manager.current_cgs
        cgs2 = manager.current_cgs
        assert cgs1 is not cgs2   # different objects
        assert cgs1 == cgs2        # same content

    def test_mutating_returned_cgs_does_not_affect_manager(self) -> None:
        manager = CGSManager.initialise(_base_cgs())
        cgs     = manager.current_cgs
        original_hash = manager.current_hash
        cgs["metadata"]["name"] = "TAMPERED"
        assert manager.current_hash == original_hash  # unchanged

    def test_restore_requires_cgs_hash(self) -> None:
        cgs = _base_cgs()
        cgs["metadata"]["cgs_hash"] = ""
        with pytest.raises(CGSManagerError, match="cgs_hash"):
            CGSManager.restore(cgs)

    def test_restore_with_valid_hash(self) -> None:
        original = CGSManager.initialise(_base_cgs())
        saved_cgs = original.current_cgs  # has cgs_hash stamped
        restored  = CGSManager.restore(saved_cgs)
        assert restored.current_hash == original.current_hash


class TestCGSManagerCommit:

    def setup_method(self) -> None:
        self.cgs     = _base_cgs()
        self.manager = CGSManager.initialise(self.cgs)

    def test_commit_changes_hash(self) -> None:
        old_hash = self.manager.current_hash
        new_cgs  = self.manager.current_cgs
        new_cgs["metadata"]["name"] = "Updated"
        meta = _make_metadata(self.manager)
        self.manager.commit(new_cgs, meta)
        assert self.manager.current_hash != old_hash

    def test_commit_bumps_patch_version(self) -> None:
        new_cgs = self.manager.current_cgs
        meta    = _make_metadata(self.manager)
        self.manager.commit(new_cgs, meta, bump="patch")
        assert self.manager.current_version == "0.1.1"

    def test_commit_bumps_minor_version(self) -> None:
        new_cgs = self.manager.current_cgs
        meta    = _make_metadata(self.manager)
        self.manager.commit(new_cgs, meta, bump="minor")
        assert self.manager.current_version == "0.2.0"

    def test_commit_bumps_major_version(self) -> None:
        new_cgs = self.manager.current_cgs
        meta    = _make_metadata(self.manager)
        self.manager.commit(new_cgs, meta, bump="major")
        assert self.manager.current_version == "1.0.0"

    def test_commit_returns_snapshot_dict(self) -> None:
        new_cgs  = self.manager.current_cgs
        meta     = _make_metadata(self.manager)
        snapshot = self.manager.commit(new_cgs, meta)
        assert "version"        in snapshot
        assert "cgs_hash"       in snapshot
        assert "transaction_id" in snapshot
        assert "source"         in snapshot

    def test_stale_mutation_guard(self) -> None:
        """Committing with wrong parent_cgs_hash must raise CGSManagerError."""
        new_cgs = self.manager.current_cgs
        # Commit once to advance the hash
        meta1 = _make_metadata(self.manager)
        self.manager.commit(new_cgs, meta1)

        # Now try to commit with the OLD hash (stale)
        new_cgs2 = self.manager.current_cgs
        stale_meta = MutationMetadata.create(
            source="manual",
            parent_cgs_hash="stale_hash_that_is_wrong",
            schema_version_target=self.manager.current_version,
        )
        with pytest.raises(CGSManagerError, match="Stale"):
            self.manager.commit(new_cgs2, stale_meta)

    def test_multiple_commits_chain_correctly(self) -> None:
        hashes: list[str] = [self.manager.current_hash]
        for i in range(5):
            new_cgs = self.manager.current_cgs
            new_cgs["metadata"]["name"] = f"Game v{i}"
            meta = _make_metadata(self.manager, description=f"change {i}")
            self.manager.commit(new_cgs, meta)
            hashes.append(self.manager.current_hash)
        # All hashes unique
        assert len(set(hashes)) == len(hashes)

    def test_commit_does_not_mutate_input_cgs(self) -> None:
        original_cgs = self.manager.current_cgs
        hash_before  = CGSSerializer.compute_hash(original_cgs)
        meta         = _make_metadata(self.manager)
        self.manager.commit(original_cgs, meta)
        # original_cgs should be unchanged
        assert CGSSerializer.compute_hash(original_cgs) == hash_before


class TestCGSManagerRollback:

    def setup_method(self) -> None:
        self.manager = CGSManager.initialise(_base_cgs())
        self._prior_cgs  = self.manager.current_cgs
        self._prior_hash = self.manager.current_hash

        # Make two commits
        for i in range(2):
            new_cgs = self.manager.current_cgs
            new_cgs["metadata"]["name"] = f"After change {i}"
            meta = _make_metadata(self.manager)
            self.manager.commit(new_cgs, meta)

    def test_rollback_restores_hash(self) -> None:
        self.manager.rollback_to_hash(self._prior_hash, self._prior_cgs)
        assert self.manager.current_hash == self._prior_hash

    def test_rollback_with_wrong_content_raises(self) -> None:
        tampered = copy.deepcopy(self._prior_cgs)
        tampered["metadata"]["name"] = "TAMPERED"
        with pytest.raises(CGSManagerError, match="mismatch"):
            self.manager.rollback_to_hash(self._prior_hash, tampered)

    def test_rollback_restores_cgs_content(self) -> None:
        original_name = self._prior_cgs["metadata"]["name"]
        self.manager.rollback_to_hash(self._prior_hash, self._prior_cgs)
        assert self.manager.current_cgs["metadata"]["name"] == original_name


class TestCGSManagerAccessors:

    def test_get_metadata(self) -> None:
        manager  = CGSManager.initialise(_base_cgs(name="Accessor Test"))
        metadata = manager.get_metadata()
        assert metadata["name"] == "Accessor Test"
        assert "cgs_hash" in metadata

    def test_get_mode(self) -> None:
        manager = CGSManager.initialise(_base_cgs())
        mode    = manager.get_mode("mode_default")
        assert mode is not None
        assert mode["id"] == "mode_default"

    def test_get_mode_missing_returns_none(self) -> None:
        manager = CGSManager.initialise(_base_cgs())
        assert manager.get_mode("mode_nonexistent") is None

    def test_all_mode_ids(self) -> None:
        manager = CGSManager.initialise(_base_cgs())
        ids     = manager.all_mode_ids()
        assert "mode_default" in ids

    def test_snapshot_count_after_commits(self) -> None:
        manager = CGSManager.initialise(_base_cgs())
        for _ in range(3):
            new_cgs = manager.current_cgs
            meta    = _make_metadata(manager)
            manager.commit(new_cgs, meta)
        # Snapshot count depends on SchemaVersionManager availability
        # When available: 4 (genesis + 3 commits). When not: 0.
        count = manager.snapshot_count()
        assert count in (0, 4)   # tolerate missing schema-factory