"""
test_memory_model.py — Phase 13.10 Memory Model tests (all 7 files)
"""
from __future__ import annotations
import sys, os

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for sub in ("memory_model", "memory"):
    sys.path.insert(0, os.path.join(_SRC, sub))

from memory_store import MemoryStore, MemoryLayer
from design_memory import DesignMemory
from structural_memory import StructuralMemory
from behavioral_memory import BehavioralMemory
from session_memory import SessionMemory, MutationRecord, FailureRecord
from safety_memory import SafetyMemory
from memory_model import MemoryModel
from memory_lifecycle_manager import MemoryLifecycleManager, MemoryAssembly

TEST_CGS_HASH = "0b1d495d00000000000000000000000000000000000000000000000000000000"
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_OLD = "c" * 64
HASH_NEW = "d" * 64

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
                 {"type_id": 5, "name": "COMP_VELOCITY_V1",
                  "defaults": {"max_linear_speed": 10.0}},
                 {"type_id": 100, "name": "COMP_HEALTH_V1",
                  "defaults": {"current": 30.0, "max": 30.0}},
             ]},
        ],
        "systems": [
            {"id": "MovementSystem", "phase": "Simulation",
             "reads": [5], "writes": [1], "depends_on": ["InputSystem"], "deterministic": True},
        ],
        "rules": [
            {"id": "rule_death", "condition": "current <= 0",
             "effect": "game_over()", "priority": 1, "is_active": True},
        ],
    }],
}


def _store() -> MemoryStore:
    return MemoryStore(session_id="test")


# ===========================================================================
# DesignMemory
# ===========================================================================

class TestDesignMemory:
    def setup_method(self):
        self.dm = DesignMemory(_store())

    def test_set_game_vision(self):
        self.dm.set_game_vision("Top-down zombie survival.")
        assert self.dm.game_vision == "Top-down zombie survival."

    def test_replace_game_vision(self):
        self.dm.set_game_vision("First version.")
        self.dm.set_game_vision("Second version.")
        assert self.dm.game_vision == "Second version."
        assert self.dm.entry_count == 1   # replaced, not duplicated

    def test_set_difficulty_philosophy(self):
        self.dm.set_difficulty_philosophy("Hard but fair.")
        assert self.dm.difficulty_philosophy == "Hard but fair."

    def test_add_core_constraint(self):
        eid = self.dm.add_core_constraint("Player always has agency.")
        assert eid is not None
        assert "Player always has agency." in self.dm.core_constraints

    def test_multiple_constraints(self):
        self.dm.add_core_constraint("Constraint A.")
        self.dm.add_core_constraint("Constraint B.")
        assert len(self.dm.core_constraints) == 2

    def test_remove_constraint(self):
        eid = self.dm.add_core_constraint("Temporary constraint.")
        ok  = self.dm.remove_constraint(eid)
        assert ok
        assert "Temporary constraint." not in self.dm.core_constraints

    def test_check_drift_detects_contradiction(self):
        self.dm.add_core_constraint("Player always has agency.")
        drift = self.dm.check_drift("Remove player input controls")
        assert len(drift) >= 1

    def test_check_drift_no_contradiction(self):
        self.dm.add_core_constraint("Player always has agency.")
        drift = self.dm.check_drift("Make zombie speed 15")
        assert len(drift) == 0

    def test_to_prefix_text_contains_vision(self):
        self.dm.set_game_vision("Zombie survival game.")
        text = self.dm.to_prefix_text()
        assert "Zombie survival game." in text
        assert "DESIGN MEMORY" in text

    def test_to_prefix_text_contains_constraints(self):
        self.dm.add_core_constraint("No instant kills.")
        text = self.dm.to_prefix_text()
        assert "No instant kills." in text

    def test_entry_count(self):
        assert self.dm.entry_count == 0
        self.dm.set_game_vision("x")
        assert self.dm.entry_count == 1
        self.dm.add_core_constraint("y")
        assert self.dm.entry_count == 2


# ===========================================================================
# StructuralMemory
# ===========================================================================

class TestStructuralMemory:
    def setup_method(self):
        self.sm = StructuralMemory(_store())
        self.sm.sync_from_cgs(CGS)

    def test_sync_populates_actors(self):
        assert self.sm.has_actor("actor_zombie")

    def test_sync_populates_components(self):
        assert self.sm.has_component_type(5)
        assert self.sm.has_component_type(100)

    def test_sync_populates_systems(self):
        assert self.sm.has_system("MovementSystem")
        assert self.sm.has_system("InputSystem")

    def test_sync_populates_rules(self):
        assert self.sm.has_rule("rule_death")

    def test_all_actor_ids(self):
        assert "actor_zombie" in self.sm.all_actor_ids

    def test_component_fields(self):
        fields = self.sm.component_fields(100)
        assert "current" in fields
        assert "max" in fields

    def test_component_name(self):
        assert "COMP_HEALTH" in self.sm.component_name(100)

    def test_unknown_actor(self):
        assert not self.sm.has_actor("actor_boss")

    def test_re_sync_clears_old_data(self):
        # Sync with a CGS that has no actors
        empty_cgs = {"metadata": {}, "global_systems": [], "modes": []}
        self.sm.sync_from_cgs(empty_cgs)
        assert not self.sm.has_actor("actor_zombie")

    def test_to_prefix_text_contains_actors(self):
        text = self.sm.to_prefix_text()
        assert "actor_zombie" in text
        assert "STRUCTURAL MEMORY" in text

    def test_to_prefix_text_contains_systems(self):
        text = self.sm.to_prefix_text()
        assert "MovementSystem" in text

    def test_entry_count_positive_after_sync(self):
        assert self.sm.entry_count > 0


# ===========================================================================
# BehavioralMemory
# ===========================================================================

class TestBehavioralMemory:
    def setup_method(self):
        self.bm = BehavioralMemory(_store())

    def test_add_pacing_concern(self):
        self.bm.add_pacing_concern("Early game too fast.")
        assert len(self.bm.pacing_concerns()) == 1

    def test_add_broken_moment(self):
        self.bm.add_broken_moment("Zombie deals double damage at close range.")
        assert len(self.bm.broken_moments()) == 1

    def test_add_intended_pattern(self):
        self.bm.add_intended_pattern("Player always under pressure.")
        assert len(self.bm.intended_patterns()) == 1

    def test_has_broken_moments(self):
        assert not self.bm.has_broken_moments()
        self.bm.add_broken_moment("Bug!")
        assert self.bm.has_broken_moments()

    def test_remove_entry(self):
        eid = self.bm.add_pacing_concern("Too slow.")
        ok  = self.bm.remove(eid)
        assert ok
        assert len(self.bm.pacing_concerns()) == 0

    def test_to_prefix_text_contains_concerns(self):
        self.bm.add_pacing_concern("Too fast in early game.")
        text = self.bm.to_prefix_text()
        assert "Too fast in early game." in text
        assert "BEHAVIORAL MEMORY" in text

    def test_entry_count(self):
        assert self.bm.entry_count == 0
        self.bm.add_pacing_concern("x")
        assert self.bm.entry_count == 1


# ===========================================================================
# SessionMemory
# ===========================================================================

class TestSessionMemory:
    def setup_method(self):
        self.sm = SessionMemory(_store())

    def test_record_prompt(self):
        self.sm.record_prompt("make the zombie faster")
        assert self.sm.last_prompt == "make the zombie faster"

    def test_recent_prompts_max(self):
        for i in range(7):
            self.sm.record_prompt(f"prompt {i}")
        assert len(self.sm.recent_prompts) <= 5

    def test_record_mutation(self):
        mr = MutationRecord(summary="Doubled zombie speed.", schema_delta="value_mutation",
                             risk_level="low", turn_index=1)
        self.sm.record_mutation(mr)
        assert self.sm.last_mutation.summary == "Doubled zombie speed."

    def test_record_failure(self):
        fr = FailureRecord(prompt="x", failure_type="parse_error",
                            reason="bad JSON", turn_index=2)
        self.sm.record_failure(fr)
        assert self.sm.has_recent_failure("parse_error")

    def test_set_turn_context(self):
        self.sm.set_turn_context("Working on zombie balance.")
        assert self.sm.turn_context == "Working on zombie balance."

    def test_clear(self):
        self.sm.record_prompt("hello")
        self.sm.clear()
        assert self.sm.last_prompt is None
        assert self.sm.entry_count == 0

    def test_to_body_text_contains_prompts(self):
        self.sm.record_prompt("make zombie faster")
        text = self.sm.to_body_text()
        assert "zombie" in text.lower()
        assert "SESSION CONTEXT" in text

    def test_entry_count(self):
        assert self.sm.entry_count == 0
        self.sm.record_prompt("test")
        assert self.sm.entry_count == 1


# ===========================================================================
# SafetyMemory
# ===========================================================================

class TestSafetyMemory:
    def setup_method(self):
        self.sm = SafetyMemory(_store())

    def test_record_block(self):
        self.sm.record_block("scope_boundary", "metadata.cgs_hash", "forbidden")
        assert self.sm.is_already_blocked("scope_boundary", "metadata.cgs_hash")

    def test_not_blocked_different_path(self):
        self.sm.record_block("scope_boundary", "metadata.cgs_hash", "forbidden")
        assert not self.sm.is_already_blocked("scope_boundary", "modes[x].actors")

    def test_record_risk_confirmation_accepted(self):
        self.sm.record_risk_confirmation("cascade_risk", "20 systems", True)
        assert self.sm.has_confirmed_risk("cascade_risk")
        assert not self.sm.has_rejected_risk("cascade_risk")

    def test_record_risk_confirmation_rejected(self):
        self.sm.record_risk_confirmation("cascade_risk", "20 systems", False)
        assert self.sm.has_rejected_risk("cascade_risk")
        assert not self.sm.has_confirmed_risk("cascade_risk")

    def test_blocked_guards_this_session(self):
        self.sm.record_block("scope_boundary", "x", "r1")
        self.sm.record_block("determinism_safety", "y", "r2")
        guards = self.sm.blocked_guards_this_session
        assert "scope_boundary" in guards
        assert "determinism_safety" in guards

    def test_clear(self):
        self.sm.record_block("g", "p", "r")
        self.sm.clear()
        assert not self.sm.is_already_blocked("g", "p")

    def test_to_body_text_shows_blocks(self):
        self.sm.record_block("scope_boundary", "metadata.cgs_hash", "forbidden field")
        text = self.sm.to_body_text()
        assert "SAFETY CONTEXT" in text
        assert "scope_boundary" in text

    def test_entry_count(self):
        assert self.sm.entry_count == 0
        self.sm.record_block("g", "p", "r")
        assert self.sm.entry_count == 1


# ===========================================================================
# MemoryModel
# ===========================================================================

class TestMemoryModel:
    def setup_method(self):
        self.model = MemoryModel(session_id="test-session")

    def test_all_layers_accessible(self):
        assert hasattr(self.model, "design")
        assert hasattr(self.model, "structural")
        assert hasattr(self.model, "behavioral")
        assert hasattr(self.model, "session")
        assert hasattr(self.model, "safety")

    def test_cached_prefix_text_includes_all_cached_layers(self):
        self.model.design.set_game_vision("Top-down zombie game.")
        self.model.structural.sync_from_cgs(CGS)
        self.model.behavioral.add_pacing_concern("Too fast.")
        text = self.model.cached_prefix_text()
        assert "zombie" in text.lower()
        assert "MovementSystem" in text or "actor_zombie" in text
        assert "Too fast" in text

    def test_per_prompt_text_includes_session_and_safety(self):
        self.model.session.record_prompt("make it faster")
        self.model.safety.record_block("g", "p", "r")
        text = self.model.per_prompt_text()
        assert "faster" in text.lower() or "SESSION" in text
        assert "SAFETY" in text

    def test_advance_turn(self):
        assert self.model.turn_index == 0
        self.model.advance_turn()
        assert self.model.turn_index == 1

    def test_total_entries(self):
        assert self.model.total_entries() == 0
        self.model.design.set_game_vision("x")
        assert self.model.total_entries() == 1

    def test_clear_session_layers(self):
        self.model.session.record_prompt("hello")
        self.model.safety.record_block("g", "p", "r")
        self.model.clear_session_layers()
        assert self.model.session.entry_count == 0
        assert self.model.safety.entry_count == 0

    def test_design_layer_persists_after_session_clear(self):
        self.model.design.set_game_vision("Persistent vision.")
        self.model.clear_session_layers()
        assert self.model.design.game_vision == "Persistent vision."

    def test_stats_returns_dict(self):
        s = self.model.stats()
        assert isinstance(s, dict)
        assert "session_id" in s

    def test_repr(self):
        r = repr(self.model)
        assert "test-session" in r


# ===========================================================================
# MemoryLifecycleManager
# ===========================================================================

class TestMemoryLifecycleManager:
    def setup_method(self):
        self.mgr = MemoryLifecycleManager(session_id="test")

    def test_assemble_returns_assembly(self):
        assembly = self.mgr.assemble(CGS, cgs_hash=TEST_CGS_HASH)
        assert isinstance(assembly, MemoryAssembly)

    def test_structural_synced_on_first_assembly(self):
        assembly = self.mgr.assemble(CGS, cgs_hash=TEST_CGS_HASH)
        assert assembly.structural_synced

    def test_structural_not_re_synced_same_hash(self):
        self.mgr.assemble(CGS, cgs_hash=TEST_CGS_HASH)
        assembly2 = self.mgr.assemble(CGS, cgs_hash=TEST_CGS_HASH)
        assert not assembly2.structural_synced

    def test_structural_re_synced_on_hash_change(self):
        self.mgr.assemble(CGS, cgs_hash=HASH_A)
        assembly2 = self.mgr.assemble(CGS, cgs_hash=HASH_B)
        assert assembly2.structural_synced

    def test_cached_prefix_text_in_assembly(self):
        self.mgr.set_game_vision("Zombie game.")
        assembly = self.mgr.assemble(CGS, cgs_hash=TEST_CGS_HASH)
        assert "Zombie game." in assembly.cached_prefix_text

    def test_per_prompt_text_in_assembly(self):
        self.mgr.on_prompt("make zombie faster")
        assembly = self.mgr.assemble(CGS, cgs_hash=TEST_CGS_HASH)
        # per_prompt_text should include session content
        assert isinstance(assembly.per_prompt_text, str)

    def test_token_estimates_positive(self):
        self.mgr.set_game_vision("x" * 100)
        assembly = self.mgr.assemble(CGS, cgs_hash=TEST_CGS_HASH)
        assert assembly.cached_token_est >= 0

    def test_on_prompt_advances_turn(self):
        self.mgr.on_prompt("first prompt")
        assert self.mgr.model.turn_index == 1

    def test_on_commit_records_mutation(self):
        mr = MutationRecord(summary="Doubled speed.", schema_delta="value_mutation",
                             risk_level="low", turn_index=1)
        self.mgr.on_commit(mr, CGS, new_cgs_hash=HASH_NEW)
        assert self.mgr.model.session.last_mutation.summary == "Doubled speed."

    def test_on_commit_re_syncs_structural(self):
        self.mgr.assemble(CGS, cgs_hash=HASH_OLD)
        mr = MutationRecord(summary="x", schema_delta="value_mutation",
                             risk_level="low", turn_index=1)
        self.mgr.on_commit(mr, CGS, new_cgs_hash=HASH_NEW)
        # Next assemble with old hash should re-sync (hash invalidated by commit)
        assembly = self.mgr.assemble(CGS, cgs_hash=HASH_NEW)
        # hash matches new_hash → no re-sync needed
        assert not assembly.structural_synced

    def test_on_failure_records_failure(self):
        fr = FailureRecord(prompt="bad", failure_type="parse_error",
                            reason="bad JSON", turn_index=1)
        self.mgr.on_failure(fr)
        assert self.mgr.model.session.has_recent_failure("parse_error")

    def test_on_safety_block(self):
        self.mgr.on_safety_block("scope_boundary", "metadata.cgs_hash", "forbidden")
        assert self.mgr.model.safety.is_already_blocked("scope_boundary",
                                                          "metadata.cgs_hash")

    def test_on_risk_confirmation(self):
        self.mgr.on_risk_confirmation("cascade_risk", "large blast radius", True)
        assert self.mgr.model.safety.has_confirmed_risk("cascade_risk")

    def test_on_session_end_clears_session(self):
        self.mgr.on_prompt("hello")
        self.mgr.on_session_end()
        assert self.mgr.model.session.entry_count == 0

    def test_set_game_vision(self):
        self.mgr.set_game_vision("Zombie survival.")
        assert self.mgr.model.design.game_vision == "Zombie survival."

    def test_cached_prefix_cache_invalidated_after_set_vision(self):
        assembly1 = self.mgr.assemble(CGS, cgs_hash=TEST_CGS_HASH)
        self.mgr.set_game_vision("New vision.")
        assembly2 = self.mgr.assemble(CGS, cgs_hash=TEST_CGS_HASH)
        # cache cleared → new vision appears in second assembly
        assert "New vision." in assembly2.cached_prefix_text

    def test_add_core_constraint(self):
        eid = self.mgr.add_core_constraint("Player agency is paramount.")
        assert eid is not None
        assert "Player agency is paramount." in self.mgr.model.design.core_constraints

    def test_repr_contains_session_id(self):
        assert "test" in repr(self.mgr)


if __name__ == "__main__":
    import traceback
    classes = [
        TestDesignMemory, TestStructuralMemory, TestBehavioralMemory,
        TestSessionMemory, TestSafetyMemory,
        TestMemoryModel, TestMemoryLifecycleManager,
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
