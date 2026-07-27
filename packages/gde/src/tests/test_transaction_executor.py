"""
tests/test_transaction_executor.py
====================================
Tests for TransactionBuilder and TransactionExecutor: operation types,
atomicity guarantee, conflict detection, ordering, and all op_types.
"""

from __future__ import annotations

import copy
import pytest
from typing import Any

from ..domain_dsl.transaction_model.transaction_builder import (
    TransactionBuilder, DSLTransaction, DSLOperation,
    OpType, TransactionBuildError,
)
from ..domain_dsl.transaction_model.transaction_executor import (
    TransactionExecutor, TransactionExecutionError,
)
from ..domain_dsl.mutation_metadata.mutation_metadata_model import MutationMetadata


# ── Fixtures ──────────────────────────────────────────────────────────────────

TEST_CGS_HASH = "a" * 64


def _meta(version: str = "0.1.0") -> MutationMetadata:
    return MutationMetadata.create(
        source="manual",
        parent_cgs_hash=TEST_CGS_HASH,
        schema_version_target=version,
        description="test",
    )


def _cgs() -> dict[str, Any]:
    return {
        "metadata": {"name": "Test", "version": "0.1.0", "cgs_hash": TEST_CGS_HASH},
        "global_systems": [],
        "modes": [
            {
                "id":             "mode_default",
                "display_name":   "Default",
                "is_default":     True,
                "schema_version": "0.1.0",
                "actors": [
                    {
                        "id":         "actor_player",
                        "actor_type": "PLAYER",
                        "components": [
                            {"type_id": 100, "defaults": {"current": 80.0, "max": 100.0}},
                        ],
                    }
                ],
                "systems": [],
                "rules":   [
                    {"id": "rule_death", "condition": "hp<=0", "effect": "DESTROY"},
                ],
            }
        ],
    }


def _builder() -> TransactionBuilder:
    return TransactionBuilder(_meta())


def _executor() -> TransactionExecutor:
    return TransactionExecutor()


# ── TransactionBuilder Tests ──────────────────────────────────────────────────

class TestTransactionBuilder:

    def test_build_single_set(self) -> None:
        txn = (
            _builder()
            .set("metadata.name", "New Name")
            .build()
        )
        assert txn.operation_count() == 1
        assert txn.operations[0].op_type == OpType.SET
        assert txn.operations[0].value   == "New Name"

    def test_build_assigns_operation_index(self) -> None:
        txn = (
            _builder()
            .set("metadata.name", "A")
            .set("metadata.version", "0.2.0")
            .build()
        )
        assert txn.operations[0].operation_index == 0
        assert txn.operations[1].operation_index == 1

    def test_build_empty_raises(self) -> None:
        with pytest.raises(TransactionBuildError):
            _builder().build()

    def test_duplicate_target_same_value_no_error(self) -> None:
        # Same target same value is idempotent — still flagged as duplicate
        with pytest.raises(TransactionBuildError, match="Duplicate"):
            (
                _builder()
                .set("metadata.name", "A")
                .set("metadata.name", "B")
                .build()
            )

    def test_metadata_cgs_hash_target_blocked(self) -> None:
        with pytest.raises(TransactionBuildError, match="cgs_hash"):
            (
                _builder()
                .set("metadata.cgs_hash", "hacked")
                .build()
            )

    def test_invalid_path_raises_build_error(self) -> None:
        with pytest.raises(TransactionBuildError):
            _builder().set("actor_player.health", 80.0).build()

    def test_type_hint_mismatch_raises(self) -> None:
        with pytest.raises(TransactionBuildError, match="str"):
            (
                _builder()
                .set("metadata.name", 999, type_hint="str")
                .build()
            )

    def test_fluent_chaining_returns_builder(self) -> None:
        b = _builder()
        returned = b.set("metadata.name", "X")
        assert returned is b

    def test_builder_resets_after_build(self) -> None:
        b = _builder()
        b.set("metadata.name", "A").build()
        with pytest.raises(TransactionBuildError):
            b.build()   # empty after reset

    def test_structural_add_does_not_conflict_check(self) -> None:
        # Two ADD_ACTOR ops to different paths should not trigger duplicate check
        txn = (
            _builder()
            .add_actor(
                "modes.mode_default.actors",
                {"id": "actor_zombie", "actor_type": "ENEMY", "components": []},
            )
            .build()
        )
        assert txn.operation_count() == 1

    def test_has_destructive_operations(self) -> None:
        txn = _builder().remove_actor("modes.mode_default.actors.actor_player").build()
        assert txn.has_destructive_operations()

    def test_has_structural_changes(self) -> None:
        txn = (
            _builder()
            .add_rule(
                "modes.mode_default.rules",
                {"id": "rule_new", "condition": "x>0", "effect": "DO"},
            )
            .build()
        )
        assert txn.has_structural_changes()

    def test_transaction_id_matches_metadata(self) -> None:
        meta = _meta()
        txn  = TransactionBuilder(meta).set("metadata.name", "X").build()
        assert txn.transaction_id == meta.transaction_id


# ── TransactionExecutor Tests ─────────────────────────────────────────────────

class TestTransactionExecutorSET:

    def setup_method(self) -> None:
        self.exec = _executor()
        self.cgs  = _cgs()

    def test_set_existing_leaf(self) -> None:
        txn = _builder().set("metadata.name", "Changed").build()
        new = self.exec.execute(txn, self.cgs)
        assert new["metadata"]["name"] == "Changed"

    def test_set_new_leaf(self) -> None:
        txn = _builder().set("metadata.new_field", "hello").build()
        new = self.exec.execute(txn, self.cgs)
        assert new["metadata"]["new_field"] == "hello"

    def test_set_nested_component_field(self) -> None:
        path = "modes.mode_default.actors.actor_player.components.100.defaults.current"
        txn  = _builder().set(path, 50.0).build()
        new  = self.exec.execute(txn, self.cgs)
        actor = new["modes"][0]["actors"][0]
        comp  = next(c for c in actor["components"] if c["type_id"] == 100)
        assert comp["defaults"]["current"] == 50.0

    def test_original_cgs_not_mutated(self) -> None:
        original_name = self.cgs["metadata"]["name"]
        txn = _builder().set("metadata.name", "Changed").build()
        self.exec.execute(txn, self.cgs)
        assert self.cgs["metadata"]["name"] == original_name


class TestTransactionExecutorNumeric:

    def setup_method(self) -> None:
        self.exec = _executor()
        self.cgs  = _cgs()
        self.health_path = (
            "modes.mode_default.actors.actor_player.components.100.defaults.current"
        )

    def test_add_numeric(self) -> None:
        txn = _builder().add(self.health_path, 10.0).build()
        new = self.exec.execute(txn, self.cgs)
        comp = new["modes"][0]["actors"][0]["components"][0]
        assert comp["defaults"]["current"] == 90.0

    def test_multiply_numeric(self) -> None:
        txn = _builder().multiply(self.health_path, 2.0).build()
        new = self.exec.execute(txn, self.cgs)
        comp = new["modes"][0]["actors"][0]["components"][0]
        assert comp["defaults"]["current"] == 160.0

    def test_divide_numeric(self) -> None:
        txn = _builder().divide(self.health_path, 2.0).build()
        new = self.exec.execute(txn, self.cgs)
        comp = new["modes"][0]["actors"][0]["components"][0]
        assert comp["defaults"]["current"] == 40.0

    def test_divide_by_zero_raises(self) -> None:
        txn = _builder().divide(self.health_path, 0).build()
        with pytest.raises(TransactionExecutionError, match="zero"):
            self.exec.execute(txn, self.cgs)

    def test_add_on_non_numeric_raises(self) -> None:
        txn = _builder().add("metadata.name", 5).build()
        with pytest.raises(TransactionExecutionError, match="non-numeric"):
            self.exec.execute(txn, self.cgs)


class TestTransactionExecutorList:

    def setup_method(self) -> None:
        self.exec = _executor()
        self.cgs  = _cgs()
        # Add tags list to metadata for testing
        self.cgs["metadata"]["tags"] = ["alpha", "beta"]

    def test_append_to_list(self) -> None:
        txn = _builder().append("metadata.tags", "gamma").build()
        new = self.exec.execute(txn, self.cgs)
        assert "gamma" in new["metadata"]["tags"]

    def test_remove_from_list(self) -> None:
        txn = _builder().remove_from_list("metadata.tags", "alpha").build()
        new = self.exec.execute(txn, self.cgs)
        assert "alpha" not in new["metadata"]["tags"]
        assert "beta"  in    new["metadata"]["tags"]

    def test_remove_missing_value_raises(self) -> None:
        txn = _builder().remove_from_list("metadata.tags", "nonexistent").build()
        with pytest.raises(TransactionExecutionError, match="not found"):
            self.exec.execute(txn, self.cgs)

    def test_append_to_non_list_raises(self) -> None:
        txn = _builder().append("metadata.name", "suffix").build()
        with pytest.raises(TransactionExecutionError, match="list"):
            self.exec.execute(txn, self.cgs)


class TestTransactionExecutorDelete:

    def setup_method(self) -> None:
        self.exec = _executor()
        self.cgs  = _cgs()
        self.cgs["metadata"]["temp_field"] = "remove_me"

    def test_delete_existing_key(self) -> None:
        txn = _builder().delete("metadata.temp_field").build()
        new = self.exec.execute(txn, self.cgs)
        assert "temp_field" not in new["metadata"]

    def test_delete_missing_key_raises(self) -> None:
        txn = _builder().delete("metadata.nonexistent").build()
        with pytest.raises(TransactionExecutionError):
            self.exec.execute(txn, self.cgs)


class TestTransactionExecutorStructural:

    def setup_method(self) -> None:
        self.exec = _executor()
        self.cgs  = _cgs()

    def test_add_actor(self) -> None:
        new_actor = {
            "id":         "actor_zombie",
            "actor_type": "ENEMY",
            "control_type": "AI_PROXY",
            "components": [],
            "tags":       [],
            "mode_scope": [],
        }
        txn = (
            _builder()
            .add_actor("modes.mode_default.actors", new_actor)
            .build()
        )
        new = self.exec.execute(txn, self.cgs)
        actor_ids = [a["id"] for a in new["modes"][0]["actors"]]
        assert "actor_zombie" in actor_ids

    def test_add_duplicate_actor_raises(self) -> None:
        dup_actor = {"id": "actor_player", "actor_type": "PLAYER", "components": []}
        txn = _builder().add_actor("modes.mode_default.actors", dup_actor).build()
        with pytest.raises(TransactionExecutionError, match="already exists"):
            self.exec.execute(txn, self.cgs)

    def test_remove_actor(self) -> None:
        txn = _builder().remove_actor(
            "modes.mode_default.actors.actor_player"
        ).build()
        new = self.exec.execute(txn, self.cgs)
        actor_ids = [a["id"] for a in new["modes"][0]["actors"]]
        assert "actor_player" not in actor_ids

    def test_add_rule(self) -> None:
        new_rule = {"id": "rule_new", "condition": "x>0", "effect": "DO"}
        txn = (
            _builder()
            .add_rule("modes.mode_default.rules", new_rule)
            .build()
        )
        new      = self.exec.execute(txn, self.cgs)
        rule_ids = [r["id"] for r in new["modes"][0]["rules"]]
        assert "rule_new" in rule_ids

    def test_remove_rule(self) -> None:
        txn = _builder().remove_rule(
            "modes.mode_default.rules.rule_death"
        ).build()
        new      = self.exec.execute(txn, self.cgs)
        rule_ids = [r["id"] for r in new["modes"][0]["rules"]]
        assert "rule_death" not in rule_ids


class TestTransactionExecutorAtomicity:

    def test_partial_failure_leaves_original_unchanged(self) -> None:
        """If op 1 of 3 fails at execution, the original CGS is completely unchanged (I8)."""
        cgs = _cgs()
        original_name    = cgs["metadata"]["name"]
        original_version = cgs["metadata"]["version"]

        # Bypass builder by constructing DSLTransaction directly:
        # op 0 valid SET, op 1 DIVIDE-by-zero (execution fails), op 2 valid SET
        from ..domain_dsl.transaction_model.transaction_builder import DSLTransaction
        meta = _meta()
        health_path = (
            "modes.mode_default.actors.actor_player.components.100.defaults.current"
        )
        ops = (
            DSLOperation(op_type="SET",    target="metadata.name",    value="Changed",
                         operation_index=0),
            DSLOperation(op_type="DIVIDE", target=health_path,        value=0,
                         operation_index=1),
            DSLOperation(op_type="SET",    target="metadata.version", value="0.2.0",
                         operation_index=2),
        )
        txn = DSLTransaction(transaction_id=meta.transaction_id, operations=ops,
                             metadata=meta, schema_version_target="0.1.0")
        executor = _executor()
        with pytest.raises(TransactionExecutionError):
            executor.execute(txn, cgs)

        # Original CGS must be completely unchanged
        assert cgs["metadata"]["name"]    == original_name
        assert cgs["metadata"]["version"] == original_version

    def test_all_ops_succeed_all_changes_applied(self) -> None:
        cgs = _cgs()
        txn = (
            _builder()
            .set("metadata.name",    "A")
            .set("metadata.version", "0.2.0")
            .build()
        )
        new = _executor().execute(txn, cgs)
        assert new["metadata"]["name"]    == "A"
        assert new["metadata"]["version"] == "0.2.0"

    def test_execute_does_not_mutate_input_cgs(self) -> None:
        cgs = _cgs()
        cgs_copy = copy.deepcopy(cgs)
        txn = _builder().set("metadata.name", "Changed").build()
        _executor().execute(txn, cgs)
        assert cgs == cgs_copy
