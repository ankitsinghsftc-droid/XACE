"""
tests/test_schema_validation.py
================================
Tests for the full validation pipeline:
    SchemaValidationContract, InvariantChecker,
    ModeValidator, SchemaVersionManager, SchemaSnapshot
"""

from __future__ import annotations

import pytest
from typing import Any

from ..validation.schema_validation_contract import SchemaValidationContract, ValidationReport
from ..validation.invariant_checker import InvariantChecker, InvariantReport
from ..mode_composition.mode_validator import ModeValidator
from ..versioning.schema_snapshot import SchemaSnapshot, _validate_version_string
from ..versioning.schema_version_manager import SchemaVersionManager, SchemaVersionError
from ..component_registry.component_definition_registry import ComponentDefinitionRegistry
from ..component_registry.component_definition import ComponentDefinition

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_registry(
    type_ids: list[int] | None = None,
) -> ComponentDefinitionRegistry:
    """Builds a minimal ComponentDefinitionRegistry for tests."""
    registry = ComponentDefinitionRegistry()
    ids = type_ids or [1, 100, 160, 5]
    for tid in ids:
        registry.register(ComponentDefinition(
            type_id=tid,
            name=f"COMP_{tid}_V1",
            domain="ucl" if tid <= 10 else "dcl/combat",
            is_ucl_core=(tid <= 10),
        ))
    return registry


def _valid_cgs(
    version:    str  = "0.1.0",
    cgs_hash:   str  = HASH_A,
    mode_id:    str  = "mode_default",
    game_name:  str  = "Test Game",
    actor_id:   str  = "actor_player",
    sys_id:     str  = "sys_input",
    schema_version: str = "0.1.0",
) -> dict[str, Any]:
    """Returns a minimal structurally valid CGS dict."""
    return {
        "metadata": {
            "version":  version,
            "name":     game_name,
            "cgs_hash": cgs_hash,
        },
        "global_systems": [
            {
                "id":            sys_id,
                "phase":         "Simulation",
                "reads":         [1],
                "writes":        [5],
                "depends_on":    [],
                "deterministic": True,
            }
        ],
        "modes": [
            {
                "id":             mode_id,
                "display_name":   "Default Mode",
                "is_default":     True,
                "schema_version": schema_version,
                "actors": [
                    {
                        "id":         actor_id,
                        "actor_type": "PLAYER",
                        "components": [
                            {"type_id": 1, "defaults": {}},
                            {"type_id": 100, "defaults": {"current": 80}},
                        ],
                    }
                ],
                "systems": [],
                "rules":   [],
            }
        ],
    }


# ── SchemaValidationContract ──────────────────────────────────────────────────

class TestSchemaValidationContract:

    def setup_method(self) -> None:
        self.registry = _make_registry()
        self.contract = SchemaValidationContract(self.registry)

    def test_valid_cgs_passes(self) -> None:
        cgs    = _valid_cgs()
        report = self.contract.validate(cgs)
        assert report.is_valid, f"Expected valid, got errors: {report.errors}"

    def test_missing_metadata_version_fails(self) -> None:
        cgs = _valid_cgs()
        del cgs["metadata"]["version"]
        report = self.contract.validate(cgs)
        assert not report.is_valid
        assert any("version" in e.lower() for e in report.errors)

    def test_invalid_version_format_fails(self) -> None:
        cgs = _valid_cgs(version="bad-version")
        report = self.contract.validate(cgs)
        assert not report.is_valid

    def test_missing_cgs_hash_fails(self) -> None:
        cgs = _valid_cgs()
        cgs["metadata"]["cgs_hash"] = ""
        report = self.contract.validate(cgs)
        assert not report.is_valid
        assert any("cgs_hash" in e.lower() for e in report.errors)

    def test_no_default_mode_fails(self) -> None:
        cgs = _valid_cgs()
        cgs["modes"][0]["is_default"] = False
        report = self.contract.validate(cgs)
        assert not report.is_valid
        assert any("default" in e.lower() for e in report.errors)

    def test_multiple_default_modes_fails(self) -> None:
        cgs = _valid_cgs()
        second_mode = dict(cgs["modes"][0])
        second_mode["id"]       = "mode_second"
        second_mode["is_default"] = True
        cgs["modes"].append(second_mode)
        report = self.contract.validate(cgs)
        assert not report.is_valid

    def test_duplicate_actor_id_fails(self) -> None:
        cgs = _valid_cgs()
        second_mode = {
            "id": "mode_second", "display_name": "Second", "is_default": False,
            "schema_version": "0.1.0",
            "actors": [{"id": "actor_player", "actor_type": "ENEMY", "components": []}],
            "systems": [], "rules": [],
        }
        cgs["modes"].append(second_mode)
        report = self.contract.validate(cgs)
        assert not report.is_valid
        assert any("actor_player" in e for e in report.errors)

    def test_duplicate_system_id_across_modes_fails(self) -> None:
        cgs = _valid_cgs()
        second_mode = {
            "id": "mode_b", "display_name": "B", "is_default": False,
            "schema_version": "0.1.0",
            "actors": [], "rules": [],
            "systems": [{"id": "sys_unique", "phase": "Simulation",
                         "reads": [], "writes": [], "depends_on": [], "deterministic": True}],
        }
        # Add same non-global system to two modes
        cgs["modes"][0]["systems"] = [
            {"id": "sys_unique", "phase": "Simulation",
             "reads": [], "writes": [], "depends_on": [], "deterministic": True}
        ]
        cgs["modes"].append(second_mode)
        report = self.contract.validate(cgs)
        assert not report.is_valid
        assert any("sys_unique" in e for e in report.errors)

    def test_unresolved_asset_reference_fails(self) -> None:
        cgs = _valid_cgs()
        cgs["modes"][0]["actors"][0]["components"].append({
            "type_id": 1,
            "defaults": {
                "render_ref": {"status": "UNRESOLVED", "id": "ref_001"}
            },
        })
        report = self.contract.validate(cgs)
        assert not report.is_valid
        assert any("UNRESOLVED" in e for e in report.errors)

    def test_unregistered_component_in_actor_fails(self) -> None:
        cgs = _valid_cgs()
        cgs["modes"][0]["actors"][0]["components"].append(
            {"type_id": 99999, "defaults": {}}
        )
        report = self.contract.validate(cgs)
        assert not report.is_valid
        assert any("99999" in e for e in report.errors)

    def test_self_referencing_system_dependency_fails(self) -> None:
        cgs = _valid_cgs()
        cgs["global_systems"][0]["depends_on"] = ["sys_input"]
        report = self.contract.validate(cgs)
        assert not report.is_valid
        assert any("itself" in e for e in report.errors)

    def test_missing_mode_schema_version_is_warning(self) -> None:
        cgs = _valid_cgs()
        del cgs["modes"][0]["schema_version"]
        report = self.contract.validate(cgs)
        # Should still be valid — missing schema_version is a warning
        assert report.is_valid
        assert report.has_warnings
        assert any("schema_version" in w for w in report.warnings)

    def test_global_system_override_is_warning(self) -> None:
        cgs = _valid_cgs()
        # Add same ID as global system to a mode system
        cgs["modes"][0]["systems"].append({
            "id": "sys_input", "phase": "Simulation",
            "reads": [], "writes": [], "depends_on": [], "deterministic": True,
        })
        report = self.contract.validate(cgs)
        assert report.is_valid
        assert any("sys_input" in w for w in report.warnings)

    def test_all_errors_collected_not_stop_at_first(self) -> None:
        cgs = _valid_cgs()
        cgs["metadata"]["version"]  = ""
        cgs["metadata"]["cgs_hash"] = ""
        cgs["modes"][0]["is_default"] = False
        report = self.contract.validate(cgs)
        assert not report.is_valid
        assert len(report.errors) >= 3


# ── InvariantChecker ──────────────────────────────────────────────────────────

class TestInvariantChecker:

    def setup_method(self) -> None:
        self.registry = _make_registry()
        self.checker  = InvariantChecker(self.registry)

    def test_valid_cgs_all_invariants_pass(self) -> None:
        report = self.checker.check(_valid_cgs())
        assert report.is_valid, f"Failed: {report.all_errors()}"

    def test_report_has_15_results(self) -> None:
        report = self.checker.check(_valid_cgs())
        assert len(report.results) == 15

    def test_results_sorted_i1_to_i15(self) -> None:
        report = self.checker.check(_valid_cgs())
        ids = [r.invariant_id for r in report.results]
        nums = [int(i.lstrip("I")) for i in ids]
        assert nums == sorted(nums)

    def test_runtime_invariants_marked_not_checkable(self) -> None:
        report = self.checker.check(_valid_cgs())
        runtime_ids = {"I1", "I2", "I3", "I5", "I9", "I10", "I13", "I15"}
        for r in report.results:
            if r.invariant_id in runtime_ids:
                assert r.not_checkable

    def test_i4_self_dependency_fails(self) -> None:
        cgs = _valid_cgs()
        cgs["global_systems"][0]["depends_on"] = ["sys_input"]
        report = self.checker.check(cgs)
        i4 = report.get("I4")
        assert i4 is not None and not i4.passed

    def test_i6_nondeterministic_system_fails(self) -> None:
        cgs = _valid_cgs()
        cgs["global_systems"][0]["deterministic"] = False
        report = self.checker.check(cgs)
        i6 = report.get("I6")
        assert i6 is not None and not i6.passed

    def test_i7_missing_version_fails(self) -> None:
        cgs = _valid_cgs()
        cgs["metadata"].pop("version", None)
        report = self.checker.check(cgs)
        i7 = report.get("I7")
        assert i7 is not None and not i7.passed

    def test_i8_missing_cgs_hash_fails(self) -> None:
        cgs = _valid_cgs()
        cgs["metadata"]["cgs_hash"] = ""
        report = self.checker.check(cgs)
        i8 = report.get("I8")
        assert i8 is not None and not i8.passed

    def test_i12_unresolved_asset_ref_fails(self) -> None:
        cgs = _valid_cgs()
        cgs["modes"][0]["actors"][0]["components"].append({
            "type_id": 1,
            "defaults": {"render_ref": {"status": "UNRESOLVED"}},
        })
        report = self.checker.check(cgs)
        i12 = report.get("I12")
        assert i12 is not None and not i12.passed

    def test_i14_missing_mode_schema_version_fails(self) -> None:
        cgs = _valid_cgs()
        del cgs["modes"][0]["schema_version"]
        report = self.checker.check(cgs)
        i14 = report.get("I14")
        assert i14 is not None and not i14.passed

    def test_failed_invariants_list_populated(self) -> None:
        cgs = _valid_cgs()
        cgs["global_systems"][0]["deterministic"] = False
        report = self.checker.check(cgs)
        assert len(report.failed_invariants()) >= 1

    def test_summary_string_non_empty(self) -> None:
        report = self.checker.check(_valid_cgs())
        assert len(report.summary()) > 0


# ── ModeValidator ─────────────────────────────────────────────────────────────

class TestModeValidator:

    def setup_method(self) -> None:
        self.registry  = _make_registry()
        self.validator = ModeValidator(self.registry)

    def _valid_mode(self, mode_id: str = "mode_default", is_default: bool = True) -> dict:
        return {
            "id":           mode_id,
            "display_name": "Default Mode",
            "is_default":   is_default,
            "schema_version": "0.1.0",
            "actors": [
                {"id": "actor_player", "actor_type": "PLAYER",
                 "components": [{"type_id": 1, "defaults": {}}]}
            ],
            "systems": [
                {"id": "sys_x", "phase": "Simulation"}
            ],
            "rules": [],
        }

    def test_valid_mode_passes(self) -> None:
        result = self.validator.validate_one(self._valid_mode())
        assert result.is_valid

    def test_missing_mode_id_fails(self) -> None:
        mode = self._valid_mode()
        mode["id"] = ""
        result = self.validator.validate_one(mode)
        assert not result.is_valid

    def test_duplicate_actor_id_within_mode_fails(self) -> None:
        mode = self._valid_mode()
        mode["actors"].append(
            {"id": "actor_player", "actor_type": "ENEMY", "components": []}
        )
        result = self.validator.validate_one(mode)
        assert not result.is_valid
        assert any("actor_player" in e for e in result.errors)

    def test_invalid_system_phase_fails(self) -> None:
        mode = self._valid_mode()
        mode["systems"][0]["phase"] = "InvalidPhase"
        result = self.validator.validate_one(mode)
        assert not result.is_valid

    def test_no_default_mode_in_set_fails(self) -> None:
        modes = [
            self._valid_mode("mode_a", is_default=False),
            self._valid_mode("mode_b", is_default=False),
        ]
        results = self.validator.validate_all(modes)
        all_errors = [e for r in results for e in r.errors]
        assert any("default" in e.lower() for e in all_errors)

    def test_two_default_modes_fails(self) -> None:
        modes = [
            self._valid_mode("mode_a", is_default=True),
            self._valid_mode("mode_b", is_default=True),
        ]
        results = self.validator.validate_all(modes)
        all_errors = [e for r in results for e in r.errors]
        assert any("multiple" in e.lower() for e in all_errors)

    def test_unregistered_component_in_mode_actor_fails(self) -> None:
        mode = self._valid_mode()
        mode["actors"][0]["components"].append(
            {"type_id": 88888, "defaults": {}}
        )
        result = self.validator.validate_one(mode)
        assert not result.is_valid
        assert any("88888" in e for e in result.errors)

    def test_collect_errors_returns_flat_list(self) -> None:
        modes = [self._valid_mode("mode_a", is_default=False)]
        errors = self.validator.collect_errors(modes)
        assert isinstance(errors, list)
        assert len(errors) > 0


# ── SchemaVersionManager ──────────────────────────────────────────────────────

class TestSchemaVersionManager:

    def _initial_cgs(self) -> dict[str, Any]:
        return {"metadata": {"version": "0.1.0", "name": "Test"}, "modes": []}

    def test_initialise_creates_genesis_snapshot(self) -> None:
        manager = SchemaVersionManager.initialise(self._initial_cgs())
        assert manager.snapshot_count() == 1
        assert manager.current_version == "0.1.0"
        genesis = manager.genesis_snapshot()
        assert genesis is not None
        assert genesis.is_genesis

    def test_compute_hash_deterministic(self) -> None:
        cgs = self._initial_cgs()
        h1  = SchemaVersionManager.compute_hash(cgs)
        h2  = SchemaVersionManager.compute_hash(cgs)
        assert h1 == h2
        assert len(h1) == 64

    def test_compute_hash_sorted_keys(self) -> None:
        cgs1 = {"b": 2, "a": 1}
        cgs2 = {"a": 1, "b": 2}
        assert SchemaVersionManager.compute_hash(cgs1) == \
               SchemaVersionManager.compute_hash(cgs2)

    def test_bump_patch_increments_version(self) -> None:
        manager = SchemaVersionManager.initialise(self._initial_cgs())
        new_cgs = {"metadata": {"version": "0.1.1", "name": "Test"}, "modes": []}
        manager.bump_patch(new_cgs, description="patch change")
        assert manager.current_version == "0.1.1"
        assert manager.snapshot_count() == 2

    def test_bump_minor_resets_patch(self) -> None:
        manager = SchemaVersionManager.initialise(self._initial_cgs())
        new_cgs = self._initial_cgs()
        manager.bump_patch(new_cgs)
        manager.bump_minor(new_cgs)
        assert manager.current_version == "0.2.0"

    def test_bump_major_resets_minor_and_patch(self) -> None:
        manager = SchemaVersionManager.initialise(self._initial_cgs())
        new_cgs = self._initial_cgs()
        manager.bump_patch(new_cgs)
        manager.bump_minor(new_cgs)
        manager.bump_major(new_cgs)
        assert manager.current_version == "1.0.0"

    def test_snapshot_chain_integrity(self) -> None:
        manager  = SchemaVersionManager.initialise(self._initial_cgs())
        new_cgs  = self._initial_cgs()
        snap1    = manager.bump_patch(new_cgs)
        snap2    = manager.bump_patch(new_cgs)
        snapshots = manager.all_snapshots()
        assert snapshots[1].is_child_of(snapshots[0])
        assert snapshots[2].is_child_of(snapshots[1])

    def test_find_by_version(self) -> None:
        manager  = SchemaVersionManager.initialise(self._initial_cgs())
        new_cgs  = self._initial_cgs()
        manager.bump_patch(new_cgs)
        snap = manager.find_by_version("0.1.1")
        assert snap is not None
        assert snap.version == "0.1.1"

    def test_validate_content_correct_hash(self) -> None:
        cgs     = self._initial_cgs()
        manager = SchemaVersionManager.initialise(cgs)
        assert manager.validate_content(cgs)

    def test_validate_content_wrong_content_fails(self) -> None:
        manager = SchemaVersionManager.initialise(self._initial_cgs())
        tampered = {"metadata": {"version": "0.1.0", "name": "TAMPERED"}}
        assert not manager.validate_content(tampered)

    def test_bump_on_uninitialised_raises(self) -> None:
        manager = SchemaVersionManager()
        with pytest.raises(SchemaVersionError, match="uninitialised"):
            manager.bump_patch({})


# ── SchemaSnapshot ────────────────────────────────────────────────────────────

class TestSchemaSnapshot:

    def test_genesis_snapshot_properties(self) -> None:
        snap = SchemaSnapshot.genesis(cgs_hash=HASH_A)
        assert snap.is_genesis
        assert snap.version == "0.1.0"
        assert snap.parent_version_hash is None
        assert snap.mutation_source == "genesis"

    def test_create_validates_source(self) -> None:
        with pytest.raises(ValueError, match="mutation_source"):
            SchemaSnapshot.create(
                version="0.1.0",
                cgs_hash="abc",
                mutation_source="invalid_source",
            )

    def test_create_validates_empty_hash(self) -> None:
        with pytest.raises(ValueError, match="cgs_hash"):
            SchemaSnapshot.create(version="0.1.0", cgs_hash="")

    def test_create_validates_version_format(self) -> None:
        with pytest.raises(ValueError):
            SchemaSnapshot.create(version="bad", cgs_hash=HASH_A)

    def test_is_child_of(self) -> None:
        parent = SchemaSnapshot.genesis(cgs_hash=HASH_A)
        child  = SchemaSnapshot.create(
            version="0.1.1",
            cgs_hash=HASH_B,
            parent_version_hash=HASH_A,
        )
        assert child.is_child_of(parent)
        assert not parent.is_child_of(child)

    def test_version_tuple(self) -> None:
        snap = SchemaSnapshot.create(version="1.2.3", cgs_hash=HASH_C)
        assert snap.version_tuple() == (1, 2, 3)
        assert snap.major == 1
        assert snap.minor == 2
        assert snap.patch == 3

    def test_short_hash(self) -> None:
        snap = SchemaSnapshot.create(
            version="0.1.0",
            cgs_hash="abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
        )
        assert snap.short_hash() == "abcdef12"

    def test_validate_version_string_valid(self) -> None:
        for v in ["0.0.0", "1.0.0", "0.1.0", "10.20.30"]:
            _validate_version_string(v)  # must not raise

    def test_validate_version_string_invalid(self) -> None:
        for v in ["1.0", "1.0.0.0", "a.b.c", "-1.0.0", ""]:
            with pytest.raises(ValueError):
                _validate_version_string(v)
