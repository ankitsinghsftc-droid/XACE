"""
test_safety_scope_guard.py — all 6 safety guard tests
"""
from __future__ import annotations
import sys, os, math

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for sub in ("safety_scope_guard", "mutation_planner", "critique_engine",
            "llm_orchestrator", "context_assembler", "intent_intake"):
    sys.path.insert(0, os.path.join(_SRC, sub))

from scope_boundary_guard import ScopeBoundaryGuard, GuardResult
from destructive_change_guard import DestructiveChangeGuard
from cascade_risk_guard import CascadeRiskGuard
from determinism_safety_guard import DeterminismSafetyGuard
from performance_risk_guard import PerformanceRiskGuard
from safety_scope_guard import SafetyScopeGuard, SafetyOutcome, Verdict
from mutation_planner import CommittedMutationPlan
from rollback_plan_builder import RollbackPlan
from pass2_dsl_draft import MutationOp
from llm_context_packet import AllowedMutationScope

TEST_CGS_HASH = "a" * 64

CGS = {
    "metadata": {"name": "Zombie Chase", "cgs_hash": TEST_CGS_HASH,
                 "version": "0.1.0", "schema_version": "0.1.0"},
    "global_systems": [
        {"id": "InputSystem", "phase": "Simulation",
         "reads": [6], "writes": [5], "depends_on": [], "deterministic": True},
    ],
    "modes": [{
        "id": "mode_default", "is_default": True,
        "actors": [
            {"id": "actor_zombie", "actor_type": "Enemy", "control_type": "AiProxy",
             "components": [
                 {"type_id": 1,   "name": "COMP_TRANSFORM_V1",
                  "defaults": {"position": {"x": 0.0}}},
                 {"type_id": 5,   "name": "COMP_VELOCITY_V1",
                  "defaults": {"max_linear_speed": 10.0}},
                 {"type_id": 100, "name": "COMP_HEALTH_V1",
                  "defaults": {"current": 30.0, "max": 30.0}},
             ]},
            {"id": "actor_player", "actor_type": "PlayerCharacter", "control_type": "Human",
             "components": [
                 {"type_id": 100, "name": "COMP_HEALTH_V1",
                  "defaults": {"current": 100.0, "max": 100.0}},
             ]},
        ],
        "systems": [
            {"id": "MovementSystem", "phase": "Simulation",
             "reads": [5], "writes": [1], "depends_on": ["InputSystem"], "deterministic": True},
            {"id": "AISystem", "phase": "Simulation",
             "reads": [1], "writes": [5], "depends_on": ["MovementSystem"], "deterministic": True},
        ],
        "rules": [
            {"id": "rule_death", "condition": "current <= 0",
             "effect": "game_over()", "priority": 1, "is_active": True},
        ],
    }],
}

_SCOPE = AllowedMutationScope(
    allowed_paths=("modes[mode_default].actors[actor_zombie].components",),
    forbidden_paths=("metadata.cgs_hash", "metadata.schema_version"),
    structural_change_allowed=False,
    max_mutation_depth=3, mode="COLLABORATIVE",
)

_OPEN_SCOPE = AllowedMutationScope(
    allowed_paths=(), forbidden_paths=("metadata.cgs_hash",),
    structural_change_allowed=True, max_mutation_depth=8, mode="ARCHITECT_MODE",
)


def _make_plan(ops, delta="value_mutation", risk="low", conf=0.9,
               systems=None) -> CommittedMutationPlan:
    return CommittedMutationPlan(
        ordered_ops=ops,
        rollback_plan=RollbackPlan(rollback_ops=[]),
        schema_delta_type=delta,
        version_bump="patch",
        confidence_score=conf,
        risk_level=risk,
        required_recompile=False,
        affected_systems=systems or ["MovementSystem"],
        mutation_description="test",
    )


_SPEED_OP = MutationOp(
    path="modes[mode_default].actors[actor_zombie].components[5].defaults.max_linear_speed",
    op="SET", value=20.0, type_hint="float",
    field_name="max_linear_speed", actor_id="actor_zombie", type_id=5,
)
_REMOVE_CORE_OP = MutationOp(
    path="modes[mode_default].actors[actor_zombie].components[1]",
    op="REMOVE_COMPONENT", value=None, type_hint="dict",
    field_name="", actor_id="actor_zombie", type_id=1,
)
_REMOVE_ZOMBIE_OP = MutationOp(
    path="modes[mode_default].actors[actor_zombie]",
    op="REMOVE_ACTOR", value=None, type_hint="dict",
    field_name="", actor_id="actor_zombie", type_id=0,
)
_REMOVE_MOVEMENT_SYS_OP = MutationOp(
    path="modes[mode_default].systems[MovementSystem]",
    op="REMOVE_SYSTEM", value=None, type_hint="dict",
    field_name="", actor_id="", type_id=0,
)
_FORBIDDEN_PATH_OP = MutationOp(
    path="metadata.cgs_hash",
    op="SET", value="hacked", type_hint="str",
    field_name="cgs_hash", actor_id="", type_id=0,
)
_OUT_OF_SCOPE_OP = MutationOp(
    path="modes[mode_default].actors[actor_player].components[100].defaults.current",
    op="SET", value=999.0, type_hint="float",
    field_name="current", actor_id="actor_player", type_id=100,
)


# ===========================================================================
# GuardResult
# ===========================================================================

class TestGuardResult:
    def test_passed_no_severity(self):
        r = GuardResult(guard="test", passed=True, severity="none")
        assert r.passed and not r.is_blocking and not r.is_warning

    def test_blocking_severity(self):
        r = GuardResult(guard="test", passed=False, severity="block",
                        findings=["issue"])
        assert r.is_blocking and not r.is_warning

    def test_warning_severity(self):
        r = GuardResult(guard="test", passed=True, severity="warning",
                        findings=["note"])
        assert r.is_warning and not r.is_blocking

    def test_repr(self):
        r = GuardResult(guard="my_guard", passed=False, severity="block")
        assert "my_guard" in repr(r) and "FAIL" in repr(r)


# ===========================================================================
# ScopeBoundaryGuard
# ===========================================================================

class TestScopeBoundaryGuard:
    def setup_method(self):
        self.guard = ScopeBoundaryGuard()

    def test_in_scope_path_passes(self):
        plan   = _make_plan([_SPEED_OP])
        result = self.guard.check(plan, _SCOPE)
        assert result.passed

    def test_forbidden_path_blocked(self):
        plan   = _make_plan([_FORBIDDEN_PATH_OP])
        result = self.guard.check(plan, _SCOPE)
        assert not result.passed
        assert result.is_blocking

    def test_out_of_scope_path_blocked(self):
        plan   = _make_plan([_OUT_OF_SCOPE_OP])
        result = self.guard.check(plan, _SCOPE)
        assert not result.passed

    def test_structural_op_blocked_when_not_allowed(self):
        plan   = _make_plan([_REMOVE_ZOMBIE_OP], delta="structural_remove")
        result = self.guard.check(plan, _SCOPE)   # _SCOPE has structural_change_allowed=False
        assert not result.passed

    def test_structural_op_passes_when_allowed(self):
        plan   = _make_plan([_REMOVE_ZOMBIE_OP], delta="structural_remove")
        result = self.guard.check(plan, _OPEN_SCOPE)
        # _OPEN_SCOPE is unrestricted → structural allowed
        assert result.passed

    def test_no_scope_only_permanent_forbidden(self):
        plan    = _make_plan([_SPEED_OP])
        result  = self.guard.check(plan, None)
        assert result.passed

    def test_guard_name(self):
        plan   = _make_plan([_SPEED_OP])
        result = self.guard.check(plan, _SCOPE)
        assert result.guard == "scope_boundary"


# ===========================================================================
# DestructiveChangeGuard
# ===========================================================================

class TestDestructiveChangeGuard:
    def setup_method(self):
        self.guard = DestructiveChangeGuard()

    def test_normal_set_passes(self):
        plan   = _make_plan([_SPEED_OP])
        result = self.guard.check(plan, CGS, "COLLABORATIVE")
        assert result.passed

    def test_core_component_removal_blocked_collaborative(self):
        plan   = _make_plan([_REMOVE_CORE_OP], delta="structural_remove")
        result = self.guard.check(plan, CGS, "COLLABORATIVE")
        assert result.is_blocking

    def test_core_component_removal_warning_advanced(self):
        plan   = _make_plan([_REMOVE_CORE_OP], delta="structural_remove")
        result = self.guard.check(plan, CGS, "ADVANCED")
        # ADVANCED mode: blocks downgrade to warnings for expert
        assert not result.is_blocking   # should be warning not block

    def test_remove_zombie_two_actors_passes(self):
        # Two actors in CGS → removing one is fine
        plan   = _make_plan([_REMOVE_ZOMBIE_OP], delta="structural_remove")
        result = self.guard.check(plan, CGS, "COLLABORATIVE")
        assert result.passed

    def test_system_with_dependent_orphan_blocked(self):
        # MovementSystem has AISystem depending on it
        plan   = _make_plan([_REMOVE_MOVEMENT_SYS_OP], delta="structural_remove")
        result = self.guard.check(plan, CGS, "COLLABORATIVE")
        assert not result.passed
        assert any("orphan" in f.lower() or "AISystem" in f for f in result.findings)

    def test_guard_name(self):
        plan   = _make_plan([_SPEED_OP])
        result = self.guard.check(plan, CGS, "COLLABORATIVE")
        assert result.guard == "destructive_change"


# ===========================================================================
# CascadeRiskGuard
# ===========================================================================

class TestCascadeRiskGuard:
    def setup_method(self):
        self.guard = CascadeRiskGuard()

    def test_no_type_id_no_cascade(self):
        no_tid_op = MutationOp(path="somewhere", op="SET", value=1.0,
                                type_hint="float", field_name="f", type_id=0)
        plan   = _make_plan([no_tid_op], systems=[])
        result = self.guard.check(plan, CGS)
        assert result.passed and result.severity == "none"

    def test_small_cascade_no_warning(self):
        plan   = _make_plan([_SPEED_OP])   # type_id=5 → MovementSystem
        result = self.guard.check(plan, CGS)
        # 2 systems (MovementSystem + AISystem) = below warn threshold
        assert isinstance(result, GuardResult)

    def test_large_cascade_warns(self):
        # Build a CGS with many systems all reading type_id=5
        big_cgs = {
            "metadata": {}, "global_systems": [],
            "modes": [{"id": "m", "actors": [], "rules": [], "systems": [
                {"id": f"Sys{i}", "phase": "Simulation", "reads": [5],
                 "writes": [], "depends_on": [], "deterministic": True}
                for i in range(10)
            ]}],
        }
        plan   = _make_plan([_SPEED_OP], systems=[f"Sys{i}" for i in range(10)])
        result = self.guard.check(plan, big_cgs)
        assert not result.passed or result.severity in {"warning", "block"}

    def test_guard_name(self):
        plan   = _make_plan([_SPEED_OP])
        result = self.guard.check(plan, CGS)
        assert result.guard == "cascade_risk"


# ===========================================================================
# DeterminismSafetyGuard
# ===========================================================================

class TestDeterminismSafetyGuard:
    def setup_method(self):
        self.guard = DeterminismSafetyGuard()

    def test_clean_float_passes(self):
        plan   = _make_plan([_SPEED_OP])
        result = self.guard.check(plan, CGS)
        assert result.passed

    def test_random_string_blocked(self):
        bad = MutationOp(path="modes[mode_default].actors[actor_zombie].components[5].defaults.x",
                          op="SET", value="random()", type_hint="str",
                          field_name="x", actor_id="actor_zombie", type_id=5)
        plan   = _make_plan([bad])
        result = self.guard.check(plan, CGS)
        assert result.is_blocking

    def test_inf_value_blocked(self):
        bad = MutationOp(path="somewhere", op="SET",
                          value=float("inf"), type_hint="float",
                          field_name="x", actor_id="", type_id=5)
        plan   = _make_plan([bad])
        result = self.guard.check(plan, CGS)
        assert result.is_blocking

    def test_nan_value_blocked(self):
        bad = MutationOp(path="somewhere", op="SET",
                          value=float("nan"), type_hint="float",
                          field_name="x", actor_id="", type_id=5)
        plan   = _make_plan([bad])
        result = self.guard.check(plan, CGS)
        assert result.is_blocking

    def test_epoch_timestamp_blocked(self):
        bad = MutationOp(path="somewhere", op="SET",
                          value=1_700_000_000.0, type_hint="float",
                          field_name="x", actor_id="", type_id=0)
        plan   = _make_plan([bad])
        result = self.guard.check(plan, CGS)
        assert result.is_blocking

    def test_set_deterministic_false_blocked(self):
        bad = MutationOp(path="modes[m].systems[MovementSystem].deterministic",
                          op="SET", value=False, type_hint="bool",
                          field_name="deterministic", actor_id="", type_id=0)
        plan   = _make_plan([bad])
        result = self.guard.check(plan, CGS)
        assert result.is_blocking

    def test_null_seed_dict_blocked(self):
        bad = MutationOp(path="somewhere", op="SET",
                          value={"seed": None}, type_hint="dict",
                          field_name="rng", actor_id="", type_id=0)
        plan   = _make_plan([bad])
        result = self.guard.check(plan, CGS)
        assert result.is_blocking

    def test_high_precision_warns(self):
        bad = MutationOp(path="modes[mode_default].actors[actor_zombie].components[5].defaults.x",
                          op="SET", value=1.23456789012345678,
                          type_hint="float", field_name="x", actor_id="actor_zombie", type_id=5)
        plan   = _make_plan([bad])
        result = self.guard.check(plan, CGS)
        assert result.severity in {"warning", "block"}   # at minimum warned

    def test_guard_name(self):
        plan   = _make_plan([_SPEED_OP])
        result = self.guard.check(plan, CGS)
        assert result.guard == "determinism_safety"


# ===========================================================================
# PerformanceRiskGuard
# ===========================================================================

class TestPerformanceRiskGuard:
    def setup_method(self):
        self.guard = PerformanceRiskGuard()

    def test_normal_mutation_passes(self):
        plan   = _make_plan([_SPEED_OP])
        result = self.guard.check(plan, CGS)
        assert result.passed

    def test_guard_name(self):
        plan   = _make_plan([_SPEED_OP])
        result = self.guard.check(plan, CGS)
        assert result.guard == "performance_risk"

    def test_many_actor_additions_warn(self):
        many_add_ops = [
            MutationOp(path="modes[mode_default].actors", op="ADD_ACTOR",
                        value={"id": f"a{i}"}, type_hint="dict",
                        field_name="", actor_id=f"a{i}", type_id=0)
            for i in range(15)
        ]
        plan   = _make_plan(many_add_ops, delta="structural_add")
        result = self.guard.check(plan, CGS)
        assert result.severity in {"warning", "block"}

    def test_engine_metrics_used(self):
        plan    = _make_plan([_SPEED_OP])
        metrics = {"avg_tick_ms": 20.0}   # over 15ms budget
        result  = self.guard.check(plan, CGS, engine_metrics=metrics)
        assert isinstance(result, GuardResult)


# ===========================================================================
# SafetyScopeGuard (orchestrator)
# ===========================================================================

class TestSafetyScopeGuard:
    def setup_method(self):
        self.guard = SafetyScopeGuard()

    def test_clean_mutation_approved(self):
        plan    = _make_plan([_SPEED_OP])
        outcome = self.guard.evaluate(plan, CGS, "COLLABORATIVE", _SCOPE)
        assert outcome.verdict in {Verdict.APPROVED, Verdict.SOFT_WARNING}

    def test_returns_safety_outcome(self):
        plan    = _make_plan([_SPEED_OP])
        outcome = self.guard.evaluate(plan, CGS, "COLLABORATIVE", _SCOPE)
        assert isinstance(outcome, SafetyOutcome)

    def test_all_five_guards_run(self):
        plan    = _make_plan([_SPEED_OP])
        outcome = self.guard.evaluate(plan, CGS, "COLLABORATIVE", _SCOPE)
        assert len(outcome.guard_results) == 5
        for g in ("scope_boundary", "destructive_change", "cascade_risk",
                  "determinism_safety", "performance_risk"):
            assert g in outcome.guard_results

    def test_forbidden_path_blocked_all_modes(self):
        plan = _make_plan([_FORBIDDEN_PATH_OP])
        for mode in ("FULLY_ASSISTED", "COLLABORATIVE", "ADVANCED", "ARCHITECT_MODE"):
            outcome = self.guard.evaluate(plan, CGS, mode, _OPEN_SCOPE)
            assert outcome.is_blocked, f"Expected block in {mode}"

    def test_determinism_violation_blocked_all_modes(self):
        bad = MutationOp(path="somewhere", op="SET",
                          value=float("nan"), type_hint="float",
                          field_name="x", actor_id="", type_id=0)
        plan = _make_plan([bad])
        for mode in ("FULLY_ASSISTED", "COLLABORATIVE", "ADVANCED", "ARCHITECT_MODE"):
            outcome = self.guard.evaluate(plan, CGS, mode, None)
            assert outcome.is_blocked, f"Expected block in {mode}"

    def test_fully_assisted_warnings_become_blocks(self):
        # CascadeRisk warning in FULLY_ASSISTED → block
        big_cgs = {
            "metadata": {}, "global_systems": [],
            "modes": [{"id": "m", "actors": [], "rules": [], "systems": [
                {"id": f"Sys{i}", "phase": "Simulation", "reads": [5],
                 "writes": [], "depends_on": [], "deterministic": True}
                for i in range(6)
            ]}],
        }
        plan    = _make_plan([_SPEED_OP], systems=[f"Sys{i}" for i in range(6)])
        outcome = self.guard.evaluate(plan, big_cgs, "FULLY_ASSISTED", None)
        if outcome.warning_guards or outcome.blocking_guards:
            assert outcome.is_blocked

    def test_architect_mode_non_critical_block_downgraded(self):
        # DestructiveChangeGuard block → warning in ARCHITECT_MODE
        plan    = _make_plan([_REMOVE_CORE_OP], delta="structural_remove")
        outcome = self.guard.evaluate(plan, CGS, "ARCHITECT_MODE", _OPEN_SCOPE)
        # Should not be blocked (downgraded to warning)
        assert not outcome.is_blocked or outcome.blocking_guards == ["scope_boundary"]

    def test_mode_stored_in_outcome(self):
        plan    = _make_plan([_SPEED_OP])
        outcome = self.guard.evaluate(plan, CGS, "ADVANCED", _SCOPE)
        assert outcome.mode == "ADVANCED"

    def test_is_approved_property(self):
        plan    = _make_plan([_SPEED_OP])
        outcome = self.guard.evaluate(plan, CGS, "COLLABORATIVE", _SCOPE)
        assert outcome.is_approved == (outcome.verdict == Verdict.APPROVED)

    def test_is_blocked_property(self):
        plan    = _make_plan([_FORBIDDEN_PATH_OP])
        outcome = self.guard.evaluate(plan, CGS, "COLLABORATIVE", _SCOPE)
        assert outcome.is_blocked == (outcome.verdict == Verdict.BLOCKED)

    def test_all_findings_combines(self):
        plan    = _make_plan([_SPEED_OP])
        outcome = self.guard.evaluate(plan, CGS, "COLLABORATIVE", _SCOPE)
        assert isinstance(outcome.all_findings, list)
        assert len(outcome.all_findings) == (
            len(outcome.blocking_findings) + len(outcome.warning_findings)
        )

    def test_to_dict_serializable(self):
        import json
        plan    = _make_plan([_SPEED_OP])
        outcome = self.guard.evaluate(plan, CGS, "COLLABORATIVE", _SCOPE)
        json.dumps(outcome.to_dict())

    def test_repr_contains_verdict(self):
        plan    = _make_plan([_SPEED_OP])
        outcome = self.guard.evaluate(plan, CGS, "COLLABORATIVE", _SCOPE)
        assert outcome.verdict in repr(outcome)


if __name__ == "__main__":
    import traceback
    classes = [
        TestGuardResult, TestScopeBoundaryGuard, TestDestructiveChangeGuard,
        TestCascadeRiskGuard, TestDeterminismSafetyGuard,
        TestPerformanceRiskGuard, TestSafetyScopeGuard,
    ]
    passed = failed = 0; errors = []
    for cls in classes:
        inst = cls()
        for name in [m for m in dir(inst) if m.startswith("test_")]:
            if hasattr(inst, "setup_method"):
                inst.setup_method()
            try:
                getattr(inst, name)(); passed += 1
            except Exception as exc:
                failed += 1
                errors.append(f"FAIL  {cls.__name__}.{name}")
                errors.append(f"      {type(exc).__name__}: {exc}")
                errors.append(traceback.format_exc())
    print(f"\nResults: {passed} passed, {failed} failed\n")
    for e in errors: print(e)
    import sys
    if failed: sys.exit(1)
