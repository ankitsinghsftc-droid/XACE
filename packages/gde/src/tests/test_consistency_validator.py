"""
tests/test_consistency_validator.py
=====================================
Tests for ConsistencyValidator, TypeChecker, ConflictDetector,
and InvariantEnforcer — all consistency sub-validators.
"""

from __future__ import annotations

import pytest
from typing import Any

from ..consistency_validator.consistency_validator import ConsistencyValidator
from ..consistency_validator.type_checker import TypeChecker, TypeCheckResult
from ..consistency_validator.conflict_detector import ConflictDetector, ConflictReport
from ..consistency_validator.invariant_enforcer import InvariantEnforcer, EnforcementResult
from ..domain_dsl.transaction_model.transaction_builder import (
    TransactionBuilder, DSLOperation, OpType,
)
from ..domain_dsl.transaction_model.transaction_executor import TransactionExecutor
from ..domain_dsl.mutation_metadata.mutation_metadata_model import MutationMetadata


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _meta() -> MutationMetadata:
    return MutationMetadata.create(
        source="manual",
        parent_cgs_hash="abc123",
        schema_version_target="0.1.0",
    )


def _valid_cgs() -> dict[str, Any]:
    return {
        "metadata": {
            "name":     "Test",
            "version":  "0.1.0",
            "cgs_hash": "abc123",
        },
        "global_systems": [
            {
                "id":    "sys_input", "phase": "Input",
                "reads": [6], "writes": [5],
                "depends_on": [], "deterministic": True,
            }
        ],
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
                            {"type_id": 100, "defaults": {
                                "current": 80.0, "max": 100.0
                            }},
                        ],
                    }
                ],
                "systems": [],
                "rules":   [],
            }
        ],
    }


def _builder() -> TransactionBuilder:
    return TransactionBuilder(_meta())


def _make_ops(*ops: DSLOperation) -> tuple[DSLOperation, ...]:
    indexed = tuple(
        DSLOperation(
            op_type=op.op_type, target=op.target, value=op.value,
            type_hint=op.type_hint, operation_index=i, description=op.description,
        )
        for i, op in enumerate(ops)
    )
    return indexed


# ── TypeChecker Tests ─────────────────────────────────────────────────────────

class TestTypeChecker:

    def setup_method(self) -> None:
        self.checker = TypeChecker()

    def test_float_valid(self) -> None:
        r = self.checker.check(3.14, "float", "path")
        assert r.is_valid

    def test_int_coerced_to_float(self) -> None:
        r = self.checker.check(3, "float", "path")
        assert r.is_valid
        assert r.coercion_note != ""

    def test_bool_rejected_as_float(self) -> None:
        r = self.checker.check(True, "float", "path")
        assert not r.is_valid

    def test_int_valid(self) -> None:
        r = self.checker.check(42, "int", "path")
        assert r.is_valid

    def test_float_with_decimal_rejected_as_int(self) -> None:
        r = self.checker.check(3.5, "int", "path")
        assert not r.is_valid
        assert "decimal" in r.error

    def test_float_with_no_decimal_accepted_as_int(self) -> None:
        r = self.checker.check(3.0, "int", "path")
        assert r.is_valid

    def test_bool_rejected_as_int(self) -> None:
        r = self.checker.check(True, "int", "path")
        assert not r.is_valid

    def test_str_valid(self) -> None:
        r = self.checker.check("hello", "str", "path")
        assert r.is_valid

    def test_int_rejected_as_str(self) -> None:
        r = self.checker.check(42, "str", "path")
        assert not r.is_valid

    def test_bool_valid(self) -> None:
        assert self.checker.check(True,  "bool", "p").is_valid
        assert self.checker.check(False, "bool", "p").is_valid

    def test_int_rejected_as_bool(self) -> None:
        r = self.checker.check(1, "bool", "path")
        assert not r.is_valid

    def test_list_str_valid(self) -> None:
        r = self.checker.check(["a", "b"], "list[str]", "path")
        assert r.is_valid

    def test_list_str_invalid_element(self) -> None:
        r = self.checker.check(["a", 2], "list[str]", "path")
        assert not r.is_valid

    def test_asset_reference_string_rejected(self) -> None:
        r = self.checker.check("raw_string", "AssetReference", "path")
        assert not r.is_valid
        assert "raw string" in r.error

    def test_asset_reference_dict_valid(self) -> None:
        ref = {"id": "ref_001", "asset_type": "MESH", "status": "PLACEHOLDER"}
        r   = self.checker.check(ref, "AssetReference", "path")
        assert r.is_valid

    def test_asset_reference_dict_missing_key(self) -> None:
        ref = {"id": "ref_001", "status": "PLACEHOLDER"}  # missing asset_type
        r   = self.checker.check(ref, "AssetReference", "path")
        assert not r.is_valid

    def test_entity_id_valid(self) -> None:
        assert self.checker.check(0,   "EntityID", "p").is_valid
        assert self.checker.check(42,  "EntityID", "p").is_valid

    def test_entity_id_negative_rejected(self) -> None:
        r = self.checker.check(-1, "EntityID", "path")
        assert not r.is_valid

    def test_enum_valid(self) -> None:
        r = self.checker.check("CHASE", "enum:BehaviorModel", "path")
        assert r.is_valid

    def test_enum_invalid_value(self) -> None:
        r = self.checker.check("DANCE", "enum:BehaviorModel", "path")
        assert not r.is_valid
        assert "CHASE" in r.error

    def test_unknown_type_passes_with_warning(self) -> None:
        r = self.checker.check(42, "UnknownType", "path")
        assert r.is_valid
        assert r.warning != ""

    def test_check_many(self) -> None:
        results = self.checker.check_many(
            values={"current": 80.0, "max": 100.0, "is_invincible": False},
            field_types={"current": "float", "max": "float", "is_invincible": "bool"},
        )
        assert all(r.is_valid for r in results)


# ── ConflictDetector Tests ────────────────────────────────────────────────────

class TestConflictDetector:

    def setup_method(self) -> None:
        self.detector = ConflictDetector()

    def _op(self, op_type, target, value=None, index=0) -> DSLOperation:
        return DSLOperation(
            op_type=op_type, target=target, value=value,
            operation_index=index,
        )

    def test_no_conflicts_empty_result(self) -> None:
        ops     = _make_ops(self._op(OpType.SET, "metadata.name", "A"))
        reports = self.detector.detect(ops)
        assert reports == []

    def test_duplicate_set_detected(self) -> None:
        ops = _make_ops(
            self._op(OpType.SET, "metadata.name", "A", 0),
            self._op(OpType.SET, "metadata.name", "B", 1),
        )
        reports = self.detector.detect(ops)
        assert len(reports) == 1
        assert reports[0].conflict_type == "DUPLICATE_SET"
        assert reports[0].is_blocking

    def test_duplicate_set_same_value_no_conflict(self) -> None:
        ops = _make_ops(
            self._op(OpType.SET, "metadata.name", "A", 0),
            self._op(OpType.SET, "metadata.name", "A", 1),
        )
        reports = self.detector.detect(ops)
        assert reports == []

    def test_contradictory_remove_detected(self) -> None:
        ops = _make_ops(
            self._op(OpType.ADD_ACTOR,    "modes.mode_default.actors", {"id":"x"}, 0),
            self._op(OpType.REMOVE_ACTOR, "modes.mode_default.actors", None, 1),
        )
        reports = self.detector.detect(ops)
        assert any(r.conflict_type == "CONTRADICTORY_REMOVE" for r in reports)

    def test_self_cancelling_detected(self) -> None:
        path = "modes.mode_default.actors.actor_player.components.100.defaults.current"
        ops  = _make_ops(
            self._op(OpType.ADD, path, 10.0, 0),
            self._op(OpType.ADD, path, -10.0, 1),
        )
        reports = self.detector.detect(ops)
        sc = [r for r in reports if r.conflict_type == "SELF_CANCELLING"]
        assert len(sc) == 1
        assert not sc[0].is_blocking   # warning, not error

    def test_range_conflict_detected(self) -> None:
        base = "modes.mode_default.actors.actor_player.components.100.defaults"
        ops  = _make_ops(
            self._op(OpType.SET, f"{base}.current", 120.0, 0),  # > max
            self._op(OpType.SET, f"{base}.max",     100.0, 1),
        )
        reports = self.detector.detect(ops)
        rc = [r for r in reports if r.conflict_type == "RANGE_CONFLICT"]
        assert len(rc) == 1
        assert rc[0].is_blocking

    def test_no_range_conflict_when_valid(self) -> None:
        base = "modes.mode_default.actors.actor_player.components.100.defaults"
        ops  = _make_ops(
            self._op(OpType.SET, f"{base}.current", 50.0, 0),
            self._op(OpType.SET, f"{base}.max",    100.0, 1),
        )
        reports = self.detector.detect(ops)
        assert not any(r.conflict_type == "RANGE_CONFLICT" for r in reports)


# ── InvariantEnforcer Tests ───────────────────────────────────────────────────

class TestInvariantEnforcer:

    def setup_method(self) -> None:
        self.enforcer = InvariantEnforcer()

    def test_valid_cgs_passes(self) -> None:
        result = self.enforcer.enforce(_valid_cgs())
        assert result.is_valid, f"Expected valid, got: {result.all_messages()}"

    def test_i4_self_dependency(self) -> None:
        cgs = _valid_cgs()
        cgs["global_systems"][0]["depends_on"] = ["sys_input"]
        result = self.enforcer.enforce(cgs)
        assert not result.is_valid
        assert any("I4" in v.invariant_id for v in result.violations)

    def test_i6_nondeterministic(self) -> None:
        cgs = _valid_cgs()
        cgs["global_systems"][0]["deterministic"] = False
        result = self.enforcer.enforce(cgs)
        assert not result.is_valid
        assert any("I6" in v.invariant_id for v in result.violations)

    def test_i7_missing_version(self) -> None:
        cgs = _valid_cgs()
        del cgs["metadata"]["version"]
        result = self.enforcer.enforce(cgs)
        assert not result.is_valid
        assert any("I7" in v.invariant_id for v in result.violations)

    def test_i12_unresolved_asset_ref(self) -> None:
        cgs = _valid_cgs()
        cgs["modes"][0]["actors"][0]["components"].append({
            "type_id": 1,
            "defaults": {"render_ref": {"status": "UNRESOLVED", "id": "r1"}},
        })
        result = self.enforcer.enforce(cgs)
        assert not result.is_valid
        assert any("I12" in v.invariant_id for v in result.violations)

    def test_i14_missing_mode_schema_version(self) -> None:
        cgs = _valid_cgs()
        del cgs["modes"][0]["schema_version"]
        result = self.enforcer.enforce(cgs)
        assert not result.is_valid
        assert any("I14" in v.invariant_id for v in result.violations)

    def test_d2_duplicate_actor_ids(self) -> None:
        cgs = _valid_cgs()
        cgs["modes"].append({
            "id": "mode_2", "display_name": "M2", "is_default": False,
            "schema_version": "0.1.0",
            "actors": [{"id": "actor_player", "actor_type": "ENEMY", "components": []}],
            "systems": [], "rules": [],
        })
        result = self.enforcer.enforce(cgs)
        assert not result.is_valid
        assert any("D2" in v.invariant_id for v in result.violations)

    def test_empty_mode_warning(self) -> None:
        cgs = _valid_cgs()
        cgs["modes"][0]["actors"] = []
        result = self.enforcer.enforce(cgs)
        # Should be a warning, not an error
        assert result.is_valid  # no blocking errors
        assert len(result.warnings()) > 0

    def test_all_violations_collected(self) -> None:
        cgs = _valid_cgs()
        cgs["global_systems"][0]["deterministic"] = False
        del cgs["modes"][0]["schema_version"]
        result = self.enforcer.enforce(cgs)
        assert len(result.violations) >= 2


# ── ConsistencyValidator Integration Tests ────────────────────────────────────

class TestConsistencyValidatorIntegration:

    def setup_method(self) -> None:
        self.validator = ConsistencyValidator()
        self.executor  = TransactionExecutor()

    def _run(self, txn, orig_cgs):
        proposed = self.executor.execute(txn, orig_cgs)
        return self.validator.validate(proposed, txn, orig_cgs)

    def test_valid_set_passes(self) -> None:
        cgs    = _valid_cgs()
        txn    = _builder().set("metadata.name", "New Name").build()
        report = self._run(txn, cgs)
        assert report.is_valid, f"Errors: {report.errors}"

    def test_type_mismatch_fails(self) -> None:
        cgs  = _valid_cgs()
        path = "modes.mode_default.actors.actor_player.components.100.defaults.current"
        # Bypass builder V3 by constructing DSLTransaction directly
        from ..domain_dsl.transaction_model.transaction_builder import DSLTransaction
        meta = _meta()
        op   = DSLOperation(op_type="SET", target=path, value="not_a_number",
                            type_hint="float", operation_index=0)
        txn  = DSLTransaction(transaction_id=meta.transaction_id, operations=(op,),
                              metadata=meta, schema_version_target="0.1.0")
        report = self._run(txn, cgs)
        assert not report.is_valid
        assert any("[Type]" in e for e in report.errors)

    def test_invariant_violation_fails(self) -> None:
        cgs = _valid_cgs()
        txn = _builder().set(
            "global_systems.sys_input.deterministic", False
        ).build()
        report = self._run(txn, cgs)
        assert not report.is_valid
        assert any("I6" in e for e in report.errors)

    def test_all_errors_collected_before_returning(self) -> None:
        cgs  = _valid_cgs()
        path = "modes.mode_default.actors.actor_player.components.100.defaults.current"
        from ..domain_dsl.transaction_model.transaction_builder import DSLTransaction
        meta = _meta()
        op1  = DSLOperation(op_type="SET", target=path,
                            value="bad", type_hint="float", operation_index=0)
        op2  = DSLOperation(op_type="SET",
                            target="global_systems.sys_input.deterministic",
                            value=False, type_hint="", operation_index=1)
        txn  = DSLTransaction(transaction_id=meta.transaction_id,
                              operations=(op1, op2), metadata=meta,
                              schema_version_target="0.1.0")
        report = self._run(txn, cgs)
        assert not report.is_valid
        assert len(report.errors) >= 2

    def test_validate_cgs_only_valid(self) -> None:
        report = self.validator.validate_cgs_only(_valid_cgs())
        assert report.is_valid

    def test_validate_cgs_only_detects_violation(self) -> None:
        cgs = _valid_cgs()
        del cgs["modes"][0]["schema_version"]
        report = self.validator.validate_cgs_only(cgs)
        assert not report.is_valid