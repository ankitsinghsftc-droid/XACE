"""
tests/test_diff_migration.py
==============================
Tests for the diff and migration pipeline:
    SchemaDiffEngine, SchemaDiff, MigrationRuleGenerator, MigrationPlan

Coverage:
    - Diff accuracy for actor add/remove/modify
    - Component-level field diffs
    - System add/remove diffs
    - Breaking vs non-breaking change detection
    - MigrationPlan rule ordering (safe application order)
    - Backward compatibility: identical CGS produces empty diff
    - Determinism: same pair of CGS dicts always produces identical diff (D11)
"""

from __future__ import annotations

import pytest
from typing import Any

from ..diff_migration.schema_diff_engine import (
    SchemaDiffEngine,
    SchemaDiff,
    ActorDiff,
    ComponentChange,
    FieldChange,
    ADDED, REMOVED, MODIFIED,
)
from ..diff_migration.migration_rule_generator import (
    MigrationRuleGenerator,
    MigrationPlan,
    MigrationRule,
    _RULE_ORDER,
)

TEST_CGS_HASH = "a" * 64


# ── CGS Builder Helpers ───────────────────────────────────────────────────────

def _cgs(
    modes: list[dict] | None = None,
    global_systems: list[dict] | None = None,
) -> dict[str, Any]:
    return {
        "metadata": {"version": "0.1.0", "cgs_hash": TEST_CGS_HASH},
        "global_systems": global_systems or [],
        "modes": modes or [],
    }


def _mode(
    mode_id: str = "mode_default",
    actors:  list[dict] | None = None,
    systems: list[dict] | None = None,
    rules:   list[dict] | None = None,
) -> dict[str, Any]:
    return {
        "id":      mode_id,
        "actors":  actors  or [],
        "systems": systems or [],
        "rules":   rules   or [],
    }


def _actor(
    actor_id:   str = "actor_player",
    components: list[dict] | None = None,
) -> dict[str, Any]:
    return {"id": actor_id, "actor_type": "PLAYER", "components": components or []}


def _comp(type_id: int, defaults: dict | None = None) -> dict[str, Any]:
    return {"type_id": type_id, "defaults": defaults or {}}


def _sys(sys_id: str, phase: str = "Simulation") -> dict[str, Any]:
    return {"id": sys_id, "phase": phase, "reads": [], "writes": [],
            "depends_on": [], "deterministic": True}


def _diff(old: dict, new: dict) -> SchemaDiff:
    return SchemaDiffEngine.compute(
        old_cgs=old, new_cgs=new,
        from_version="0.1.0", from_hash="b" * 64,
        to_version="0.2.0",   to_hash="c" * 64,
    )


# ── SchemaDiffEngine ──────────────────────────────────────────────────────────

class TestSchemaDiffEngine:

    # ── Identical CGS ─────────────────────────────────────────────────────────

    def test_identical_cgs_produces_empty_diff(self) -> None:
        cgs  = _cgs(modes=[_mode(actors=[_actor()])])
        diff = _diff(cgs, cgs)
        assert diff.is_empty
        assert not diff.is_breaking

    def test_empty_cgs_diff_is_empty(self) -> None:
        empty = _cgs()
        diff  = _diff(empty, empty)
        assert diff.is_empty

    # ── Actor diffs ───────────────────────────────────────────────────────────

    def test_actor_added(self) -> None:
        old  = _cgs(modes=[_mode(actors=[])])
        new  = _cgs(modes=[_mode(actors=[_actor("actor_zombie")])])
        diff = _diff(old, new)
        added = diff.actor_diffs_by_kind(ADDED)
        assert len(added) == 1
        assert added[0].actor_id == "actor_zombie"
        assert not diff.is_breaking   # adding an actor is non-breaking

    def test_actor_removed(self) -> None:
        old  = _cgs(modes=[_mode(actors=[_actor("actor_zombie")])])
        new  = _cgs(modes=[_mode(actors=[])])
        diff = _diff(old, new)
        removed = diff.actor_diffs_by_kind(REMOVED)
        assert len(removed) == 1
        assert removed[0].actor_id == "actor_zombie"
        assert diff.is_breaking       # removing an actor IS breaking

    def test_multiple_actors_sorted_by_id(self) -> None:
        old  = _cgs(modes=[_mode(actors=[])])
        new  = _cgs(modes=[_mode(actors=[
            _actor("actor_zombie"),
            _actor("actor_archer"),
        ])])
        diff = _diff(old, new)
        added_ids = [d.actor_id for d in diff.actor_diffs_by_kind(ADDED)]
        assert added_ids == sorted(added_ids)  # D11

    # ── Component diffs within actor ──────────────────────────────────────────

    def test_component_added_to_actor(self) -> None:
        old = _cgs(modes=[_mode(actors=[_actor(components=[_comp(100)])])])
        new = _cgs(modes=[_mode(actors=[_actor(components=[_comp(100), _comp(160)])])])
        diff = _diff(old, new)
        modified = diff.actor_diffs_by_kind(MODIFIED)
        assert len(modified) == 1
        comp_changes = modified[0].component_changes
        added = [c for c in comp_changes if c.change_kind == ADDED]
        assert any(c.type_id == 160 for c in added)
        assert not diff.is_breaking   # adding a component is non-breaking

    def test_component_removed_from_actor(self) -> None:
        old = _cgs(modes=[_mode(actors=[_actor(components=[_comp(100), _comp(160)])])])
        new = _cgs(modes=[_mode(actors=[_actor(components=[_comp(100)])])])
        diff = _diff(old, new)
        modified = diff.actor_diffs_by_kind(MODIFIED)
        assert len(modified) == 1
        removed_comps = [
            c for c in modified[0].component_changes if c.change_kind == REMOVED
        ]
        assert any(c.type_id == 160 for c in removed_comps)
        assert diff.is_breaking       # removing a component IS breaking

    # ── Field diffs within component ──────────────────────────────────────────

    def test_field_value_changed(self) -> None:
        old = _cgs(modes=[_mode(actors=[
            _actor(components=[_comp(100, {"current": 80})])
        ])])
        new = _cgs(modes=[_mode(actors=[
            _actor(components=[_comp(100, {"current": 100})])
        ])])
        diff = _diff(old, new)
        modified = diff.actor_diffs_by_kind(MODIFIED)
        assert len(modified) == 1
        comp_mod = [c for c in modified[0].component_changes if c.change_kind == MODIFIED]
        assert len(comp_mod) == 1
        field_changes = comp_mod[0].field_changes
        current_change = next((f for f in field_changes if f.field_name == "current"), None)
        assert current_change is not None
        assert current_change.old_value == 80
        assert current_change.new_value == 100

    def test_field_added_to_component(self) -> None:
        old = _cgs(modes=[_mode(actors=[_actor(components=[_comp(100, {})])])])
        new = _cgs(modes=[_mode(actors=[_actor(components=[_comp(100, {"max": 100})])])])
        diff = _diff(old, new)
        modified = diff.actor_diffs_by_kind(MODIFIED)
        comp_mod  = [c for c in modified[0].component_changes if c.change_kind == MODIFIED]
        assert any(fc.field_name == "max" for fc in comp_mod[0].field_changes)

    def test_field_removed_is_breaking(self) -> None:
        old = _cgs(modes=[_mode(actors=[_actor(components=[_comp(100, {"current": 80, "max": 100})])])])
        new = _cgs(modes=[_mode(actors=[_actor(components=[_comp(100, {"current": 80})])])])
        diff = _diff(old, new)
        assert diff.is_breaking

    # ── System diffs ──────────────────────────────────────────────────────────

    def test_system_added(self) -> None:
        old  = _cgs()
        new  = _cgs(global_systems=[_sys("sys_hunger")])
        diff = _diff(old, new)
        added = diff.system_diffs_by_kind(ADDED)
        assert any(s.system_id == "sys_hunger" for s in added)
        assert not diff.is_breaking   # system changes never break saves

    def test_system_removed(self) -> None:
        old  = _cgs(global_systems=[_sys("sys_hunger")])
        new  = _cgs()
        diff = _diff(old, new)
        removed = diff.system_diffs_by_kind(REMOVED)
        assert any(s.system_id == "sys_hunger" for s in removed)
        assert not diff.is_breaking

    # ── Diff metadata ─────────────────────────────────────────────────────────

    def test_diff_from_to_versions(self) -> None:
        diff = SchemaDiffEngine.compute(
            old_cgs=_cgs(), new_cgs=_cgs(),
            from_version="0.1.0", from_hash="old",
            to_version="0.2.0",   to_hash="new",
        )
        assert diff.from_version == "0.1.0"
        assert diff.to_version   == "0.2.0"
        assert diff.from_hash    == "old"
        assert diff.to_hash      == "new"

    def test_summary_non_empty(self) -> None:
        diff = _diff(_cgs(), _cgs())
        assert len(diff.summary()) > 0

    # ── Determinism (D11) ─────────────────────────────────────────────────────

    def test_diff_is_deterministic(self) -> None:
        old = _cgs(modes=[_mode(actors=[_actor("actor_a"), _actor("actor_b")])])
        new = _cgs(modes=[_mode(actors=[_actor("actor_b"), _actor("actor_c")])])
        diff1 = _diff(old, new)
        diff2 = _diff(old, new)
        ids1 = [(d.actor_id, d.change_kind) for d in diff1.actor_diffs]
        ids2 = [(d.actor_id, d.change_kind) for d in diff2.actor_diffs]
        assert ids1 == ids2  # D11


# ── MigrationRuleGenerator ────────────────────────────────────────────────────

class TestMigrationRuleGenerator:

    # ── Empty diff ────────────────────────────────────────────────────────────

    def test_empty_diff_produces_empty_plan(self) -> None:
        cgs  = _cgs()
        diff = _diff(cgs, cgs)
        plan = MigrationRuleGenerator.generate(diff)
        assert plan.rule_count == 0
        assert not plan.is_breaking

    # ── Actor rules ───────────────────────────────────────────────────────────

    def test_added_actor_produces_add_actor_rule(self) -> None:
        old  = _cgs(modes=[_mode(actors=[])])
        new  = _cgs(modes=[_mode(actors=[_actor("actor_zombie")])])
        plan = MigrationRuleGenerator.generate(_diff(old, new))
        add_rules = plan.rules_of_type("add_actor")
        assert len(add_rules) == 1
        assert add_rules[0].params["actor_id"] == "actor_zombie"
        assert not add_rules[0].is_breaking

    def test_removed_actor_produces_tombstone_rule(self) -> None:
        old  = _cgs(modes=[_mode(actors=[_actor("actor_zombie")])])
        new  = _cgs(modes=[_mode(actors=[])])
        plan = MigrationRuleGenerator.generate(_diff(old, new))
        tomb_rules = plan.rules_of_type("tombstone_actor")
        assert len(tomb_rules) == 1
        assert tomb_rules[0].is_breaking
        assert not tomb_rules[0].is_reversible
        assert plan.is_breaking
        assert plan.requires_designer_review

    # ── Component rules ───────────────────────────────────────────────────────

    def test_added_component_produces_add_component_rule(self) -> None:
        old  = _cgs(modes=[_mode(actors=[_actor(components=[_comp(100)])])])
        new  = _cgs(modes=[_mode(actors=[_actor(components=[_comp(100), _comp(160)])])])
        plan = MigrationRuleGenerator.generate(_diff(old, new))
        add_comp = plan.rules_of_type("add_component")
        assert len(add_comp) == 1
        assert add_comp[0].params["type_id"] == 160
        assert not add_comp[0].is_breaking

    def test_removed_component_produces_remove_component_rule(self) -> None:
        old  = _cgs(modes=[_mode(actors=[_actor(components=[_comp(100), _comp(160)])])])
        new  = _cgs(modes=[_mode(actors=[_actor(components=[_comp(100)])])])
        plan = MigrationRuleGenerator.generate(_diff(old, new))
        rem_comp = plan.rules_of_type("remove_component")
        assert len(rem_comp) == 1
        assert rem_comp[0].is_breaking

    # ── Field rules ───────────────────────────────────────────────────────────

    def test_added_field_produces_add_field_rule(self) -> None:
        old  = _cgs(modes=[_mode(actors=[_actor(components=[_comp(100, {})])])])
        new  = _cgs(modes=[_mode(actors=[_actor(components=[_comp(100, {"max": 100})])])])
        plan = MigrationRuleGenerator.generate(_diff(old, new))
        add_fields = plan.rules_of_type("add_field")
        assert any(r.params["field_name"] == "max" for r in add_fields)
        assert all(not r.is_breaking for r in add_fields)

    def test_removed_field_produces_remove_field_rule(self) -> None:
        old  = _cgs(modes=[_mode(actors=[_actor(components=[_comp(100, {"current": 80, "max": 100})])])])
        new  = _cgs(modes=[_mode(actors=[_actor(components=[_comp(100, {"current": 80})])])])
        plan = MigrationRuleGenerator.generate(_diff(old, new))
        rem_fields = plan.rules_of_type("remove_field")
        assert any(r.params["field_name"] == "max" for r in rem_fields)
        assert all(r.is_breaking for r in rem_fields)

    def test_changed_field_produces_modify_field_rule(self) -> None:
        old  = _cgs(modes=[_mode(actors=[_actor(components=[_comp(100, {"current": 80})])])])
        new  = _cgs(modes=[_mode(actors=[_actor(components=[_comp(100, {"current": 100})])])])
        plan = MigrationRuleGenerator.generate(_diff(old, new))
        mod_fields = plan.rules_of_type("modify_field")
        assert len(mod_fields) >= 1
        r = mod_fields[0]
        assert r.params["old_value"] == 80
        assert r.params["new_value"] == 100
        assert not r.is_breaking

    # ── System rules ──────────────────────────────────────────────────────────

    def test_added_system_produces_add_system_rule(self) -> None:
        old  = _cgs()
        new  = _cgs(global_systems=[_sys("sys_hunger")])
        plan = MigrationRuleGenerator.generate(_diff(old, new))
        add_sys = plan.rules_of_type("add_system")
        assert len(add_sys) == 1
        assert not add_sys[0].is_breaking

    def test_removed_system_produces_remove_system_rule(self) -> None:
        old  = _cgs(global_systems=[_sys("sys_hunger")])
        new  = _cgs()
        plan = MigrationRuleGenerator.generate(_diff(old, new))
        rem_sys = plan.rules_of_type("remove_system")
        assert len(rem_sys) == 1
        assert not rem_sys[0].is_breaking

    # ── Rule ordering ─────────────────────────────────────────────────────────

    def test_rules_applied_in_safe_order(self) -> None:
        """
        Tombstone and remove rules must come before add rules.
        Validates _RULE_ORDER is respected.
        """
        # A complex change: remove one actor, add another, add component to third
        old = _cgs(modes=[_mode(actors=[
            _actor("actor_gone"),
            _actor("actor_kept", components=[_comp(100)]),
        ])])
        new = _cgs(modes=[_mode(actors=[
            _actor("actor_new"),
            _actor("actor_kept", components=[_comp(100), _comp(160)]),
        ])])
        plan = MigrationRuleGenerator.generate(_diff(old, new))

        rule_ranks = [_RULE_ORDER.get(r.rule_type, 99) for r in plan.rules]
        assert rule_ranks == sorted(rule_ranks), (
            f"Rules are not in safe application order: "
            f"{[(r.rule_type, _RULE_ORDER.get(r.rule_type)) for r in plan.rules]}"
        )

    def test_within_same_rank_rules_sorted_by_target_path(self) -> None:
        """Same-rank rules must be sorted by target_path for D11."""
        old = _cgs(modes=[_mode(actors=[])])
        new = _cgs(modes=[_mode(actors=[
            _actor("actor_z"),
            _actor("actor_a"),
        ])])
        plan = MigrationRuleGenerator.generate(_diff(old, new))
        add_actor_rules = plan.rules_of_type("add_actor")
        paths = [r.target_path for r in add_actor_rules]
        assert paths == sorted(paths)

    # ── Plan metadata ─────────────────────────────────────────────────────────

    def test_plan_has_unique_ids(self) -> None:
        old  = _cgs(modes=[_mode(actors=[_actor("a"), _actor("b")])])
        new  = _cgs(modes=[_mode(actors=[_actor("c"), _actor("d")])])
        plan = MigrationRuleGenerator.generate(_diff(old, new))
        rule_ids = [r.rule_id for r in plan.rules]
        assert len(rule_ids) == len(set(rule_ids))  # all unique

    def test_plan_from_to_versions(self) -> None:
        diff = SchemaDiffEngine.compute(
            old_cgs=_cgs(), new_cgs=_cgs(),
            from_version="0.1.0", from_hash="old",
            to_version="0.2.0",   to_hash="new",
        )
        plan = MigrationRuleGenerator.generate(diff)
        assert plan.from_version == "0.1.0"
        assert plan.to_version   == "0.2.0"

    def test_breaking_rules_list(self) -> None:
        old  = _cgs(modes=[_mode(actors=[_actor("actor_a")])])
        new  = _cgs(modes=[_mode(actors=[])])
        plan = MigrationRuleGenerator.generate(_diff(old, new))
        assert len(plan.breaking_rules()) > 0
        assert all(r.is_breaking for r in plan.breaking_rules())

    def test_plan_summary_non_empty(self) -> None:
        old  = _cgs(modes=[_mode(actors=[_actor("a")])])
        new  = _cgs(modes=[_mode(actors=[_actor("b")])])
        plan = MigrationRuleGenerator.generate(_diff(old, new))
        assert len(plan.summary()) > 0

    # ── Backward compatibility ────────────────────────────────────────────────

    def test_non_breaking_changes_no_designer_review(self) -> None:
        """Adding actors and components never requires designer review."""
        old  = _cgs(modes=[_mode(actors=[])])
        new  = _cgs(modes=[_mode(actors=[
            _actor("actor_new", components=[_comp(100)])
        ])])
        plan = MigrationRuleGenerator.generate(_diff(old, new))
        assert not plan.requires_designer_review
        assert not plan.is_breaking

    def test_reversible_rules_have_flag_set(self) -> None:
        old  = _cgs(modes=[_mode(actors=[])])
        new  = _cgs(modes=[_mode(actors=[_actor("actor_a")])])
        plan = MigrationRuleGenerator.generate(_diff(old, new))
        for r in plan.rules_of_type("add_actor"):
            assert r.is_reversible

    def test_tombstone_rules_not_reversible(self) -> None:
        old  = _cgs(modes=[_mode(actors=[_actor("actor_gone")])])
        new  = _cgs(modes=[_mode(actors=[])])
        plan = MigrationRuleGenerator.generate(_diff(old, new))
        for r in plan.rules_of_type("tombstone_actor"):
            assert not r.is_reversible
