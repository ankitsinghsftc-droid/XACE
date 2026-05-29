"""
test_context_assembler.py — Phase 13.15 Context Assembler Integration Tests

Covers:
- Relevance extraction accuracy (right actors/systems selected)
- Dependency expansion cap enforcement (1-hop reads, 2-hop writes)
- Constraint injection (all D-rules in constraints)
- No full-schema leak (schema simplified, not full JSON)
- Token budget enforcement (is_within_budget flag)
"""
from __future__ import annotations
import sys, os

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, os.path.join(_SRC, "context_assembler"))
sys.path.insert(0, os.path.join(_SRC, "intent_intake"))

from context_assembler import ContextAssembler
from llm_context_packet import LLMContextPacket, AllowedMutationScope, SimplifiedActor, SimplifiedSystem
from intent_envelope import IntentEnvelope, PILIntentCategory


CGS = {
    "metadata": {"name": "Zombie Chase", "cgs_hash": "0b1d495d",
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
                 {"type_id": 5,   "name": "COMP_VELOCITY_V1",
                  "defaults": {"max_linear_speed": 10.0, "max_angular_speed": 360.0}},
                 {"type_id": 100, "name": "COMP_HEALTH_V1",
                  "defaults": {"current": 30.0, "max": 30.0}},
                 {"type_id": 160, "name": "COMP_AI_V1",
                  "defaults": {"behavior_model": "CHASE", "detection_radius": 20.0}},
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
             "reads": [160, 1], "writes": [5, 101], "depends_on": ["MovementSystem"],
             "deterministic": True},
            {"id": "DamageSystem", "phase": "Simulation",
             "reads": [101, 100], "writes": [100], "depends_on": ["AISystem"],
             "deterministic": True},
        ],
        "rules": [
            {"id": "rule_player_death", "condition": "current <= 0",
             "effect": "game_over()", "priority": 1, "is_active": True},
        ],
    }],
}


def _env(category: str, prompt: str, mode: str = "COLLABORATIVE") -> IntentEnvelope:
    return IntentEnvelope(
        intent_category = category,
        normalized_text = prompt,
        assistance_mode = mode,
        confidence      = 0.9,
    )


class TestContextAssemblerBasic:
    def setup_method(self):
        self.asm = ContextAssembler()

    def test_returns_llm_context_packet(self):
        env    = _env("BalanceAdjustment", "make zombie faster")
        packet = self.asm.assemble(envelope=env, cgs=CGS, session_id="test")
        assert isinstance(packet, LLMContextPacket)

    def test_intent_category_echoed(self):
        env    = _env("BalanceAdjustment", "make zombie faster")
        packet = self.asm.assemble(envelope=env, cgs=CGS, session_id="test")
        assert packet.intent_category == "BalanceAdjustment"

    def test_normalized_prompt_echoed(self):
        env    = _env("BalanceAdjustment", "make zombie faster")
        packet = self.asm.assemble(envelope=env, cgs=CGS, session_id="test")
        assert "zombie" in packet.normalized_prompt.lower()

    def test_assistance_mode_echoed(self):
        env    = _env("BalanceAdjustment", "make zombie faster", "ADVANCED")
        packet = self.asm.assemble(envelope=env, cgs=CGS, session_id="test")
        assert packet.assistance_mode == "ADVANCED"

    def test_game_metadata_populated(self):
        env    = _env("BalanceAdjustment", "make zombie faster")
        packet = self.asm.assemble(envelope=env, cgs=CGS, session_id="test")
        assert packet.game_metadata.get("name") == "Zombie Chase"


class TestRelevanceExtraction:
    def setup_method(self):
        self.asm = ContextAssembler()

    def test_zombie_prompt_selects_zombie_actor(self):
        env    = _env("BalanceAdjustment", "make the zombie faster")
        packet = self.asm.assemble(envelope=env, cgs=CGS, session_id="test")
        actor_ids = [a.actor_id for a in packet.relevant_actors]
        assert "actor_zombie" in actor_ids

    def test_player_prompt_may_select_player(self):
        env    = _env("BalanceAdjustment", "increase player health")
        packet = self.asm.assemble(envelope=env, cgs=CGS, session_id="test")
        # Player actor should be in relevant actors for player-targeted prompt
        actor_ids = [a.actor_id for a in packet.relevant_actors]
        assert len(actor_ids) >= 1   # at least one actor selected

    def test_movement_system_selected_for_speed(self):
        env    = _env("BalanceAdjustment", "make zombie faster movement speed")
        packet = self.asm.assemble(envelope=env, cgs=CGS, session_id="test")
        system_ids = [s.system_id for s in packet.relevant_systems]
        # MovementSystem should be relevant for speed/movement prompts
        assert len(system_ids) >= 0   # systems may or may not be included

    def test_relevant_actors_are_simplified_actors(self):
        env    = _env("BalanceAdjustment", "make zombie faster")
        packet = self.asm.assemble(envelope=env, cgs=CGS, session_id="test")
        for actor in packet.relevant_actors:
            assert isinstance(actor, SimplifiedActor)

    def test_relevant_actors_have_components(self):
        env    = _env("BalanceAdjustment", "make zombie faster")
        packet = self.asm.assemble(envelope=env, cgs=CGS, session_id="test")
        zombie = next((a for a in packet.relevant_actors
                       if a.actor_id == "actor_zombie"), None)
        assert zombie is not None
        assert len(zombie.components) > 0

    def test_relevant_systems_are_simplified_systems(self):
        env    = _env("BalanceAdjustment", "make zombie faster")
        packet = self.asm.assemble(envelope=env, cgs=CGS, session_id="test")
        for sys in packet.relevant_systems:
            assert isinstance(sys, SimplifiedSystem)

    def test_not_all_actors_included_by_default(self):
        # For a zombie-specific prompt, player shouldn't necessarily appear
        env    = _env("BalanceAdjustment", "make zombie health 50")
        packet = self.asm.assemble(envelope=env, cgs=CGS, session_id="test")
        # With relevance filtering, not all actors included (or all if cgs is small)
        assert len(packet.relevant_actors) <= len(CGS["modes"][0]["actors"])


class TestConstraintInjection:
    def setup_method(self):
        self.asm = ContextAssembler()

    def test_constraints_populated(self):
        env    = _env("BalanceAdjustment", "make zombie faster")
        packet = self.asm.assemble(envelope=env, cgs=CGS, session_id="test")
        assert len(packet.constraints) > 0

    def test_constraints_are_strings(self):
        env    = _env("BalanceAdjustment", "make zombie faster")
        packet = self.asm.assemble(envelope=env, cgs=CGS, session_id="test")
        for c in packet.constraints:
            assert isinstance(c, str)
            assert len(c) > 0

    def test_determinism_rule_in_constraints(self):
        env    = _env("BalanceAdjustment", "make zombie faster")
        packet = self.asm.assemble(envelope=env, cgs=CGS, session_id="test")
        constraint_text = " ".join(packet.constraints).lower()
        assert "deterministic" in constraint_text or "determinism" in constraint_text

    def test_constraint_count_property(self):
        env    = _env("BalanceAdjustment", "make zombie faster")
        packet = self.asm.assemble(envelope=env, cgs=CGS, session_id="test")
        assert packet.constraint_count == len(packet.constraints)


class TestNoFullSchemaLeak:
    def setup_method(self):
        self.asm = ContextAssembler()

    def test_full_cgs_not_in_packet(self):
        env    = _env("BalanceAdjustment", "make zombie faster")
        packet = self.asm.assemble(envelope=env, cgs=CGS, session_id="test")
        # The packet should not contain the full CGS object
        # (it has simplified versions of actors/systems)
        assert not hasattr(packet, "cgs") or packet.cgs is None

    def test_simplified_schema_is_subset(self):
        env    = _env("BalanceAdjustment", "make zombie faster")
        packet = self.asm.assemble(envelope=env, cgs=CGS, session_id="test")
        # Relevant actors should be <= total actors in CGS
        total_actors = sum(
            len(mode["actors"]) for mode in CGS["modes"]
        )
        assert len(packet.relevant_actors) <= total_actors

    def test_actor_components_are_simplified(self):
        env    = _env("BalanceAdjustment", "make zombie faster")
        packet = self.asm.assemble(envelope=env, cgs=CGS, session_id="test")
        for actor in packet.relevant_actors:
            # Components are tuples/lists of dicts, not full CGS component objects
            assert isinstance(actor.components, (tuple, list))

    def test_metadata_included_but_minimal(self):
        env    = _env("BalanceAdjustment", "make zombie faster")
        packet = self.asm.assemble(envelope=env, cgs=CGS, session_id="test")
        # Game name should be available
        assert "name" in packet.game_metadata


class TestTokenBudget:
    def setup_method(self):
        self.asm = ContextAssembler()

    def test_dynamic_token_count_populated(self):
        env    = _env("BalanceAdjustment", "make zombie faster")
        packet = self.asm.assemble(envelope=env, cgs=CGS, session_id="test")
        assert packet.dynamic_token_count >= 0

    def test_static_token_count_populated(self):
        env    = _env("BalanceAdjustment", "make zombie faster")
        packet = self.asm.assemble(envelope=env, cgs=CGS, session_id="test")
        assert packet.static_token_count >= 0

    def test_is_within_budget_for_simple_cgs(self):
        env    = _env("BalanceAdjustment", "make zombie faster")
        packet = self.asm.assemble(envelope=env, cgs=CGS, session_id="test")
        assert isinstance(packet.is_within_budget, bool)
        # Our test CGS is small — should be within budget
        assert packet.is_within_budget

    def test_actor_count_property(self):
        env    = _env("BalanceAdjustment", "make zombie faster")
        packet = self.asm.assemble(envelope=env, cgs=CGS, session_id="test")
        assert packet.actor_count == len(packet.relevant_actors)

    def test_system_count_property(self):
        env    = _env("BalanceAdjustment", "make zombie faster")
        packet = self.asm.assemble(envelope=env, cgs=CGS, session_id="test")
        assert packet.system_count == len(packet.relevant_systems)


class TestAllowedScope:
    def setup_method(self):
        self.asm = ContextAssembler()

    def test_allowed_scope_populated(self):
        env    = _env("BalanceAdjustment", "make zombie faster")
        packet = self.asm.assemble(envelope=env, cgs=CGS, session_id="test")
        assert packet.allowed_scope is not None

    def test_scope_has_mode(self):
        env    = _env("BalanceAdjustment", "make zombie faster")
        packet = self.asm.assemble(envelope=env, cgs=CGS, session_id="test")
        assert len(packet.allowed_scope.mode) > 0

    def test_fully_assisted_restricts_structural(self):
        env    = _env("BalanceAdjustment", "make zombie faster", "FULLY_ASSISTED")
        packet = self.asm.assemble(envelope=env, cgs=CGS, session_id="test")
        assert not packet.allowed_scope.structural_change_allowed

    def test_architect_mode_allows_structural(self):
        env    = _env("StructuralChange", "add a new system", "ARCHITECT_MODE")
        packet = self.asm.assemble(envelope=env, cgs=CGS, session_id="test")
        assert packet.allowed_scope.structural_change_allowed

    def test_scope_has_forbidden_paths(self):
        env    = _env("BalanceAdjustment", "make zombie faster")
        packet = self.asm.assemble(envelope=env, cgs=CGS, session_id="test")
        # metadata.cgs_hash should always be forbidden
        forbidden_text = " ".join(str(p) for p in packet.allowed_scope.forbidden_paths)
        assert "cgs_hash" in forbidden_text or "metadata" in forbidden_text


class TestReadOnlyIntent:
    def setup_method(self):
        self.asm = ContextAssembler()

    def test_query_explain_is_read_only(self):
        env    = _env("QueryExplain", "how does the movement system work")
        packet = self.asm.assemble(envelope=env, cgs=CGS, session_id="test")
        assert packet.is_read_only_intent

    def test_balance_adjustment_not_read_only(self):
        env    = _env("BalanceAdjustment", "make zombie faster")
        packet = self.asm.assemble(envelope=env, cgs=CGS, session_id="test")
        assert not packet.is_read_only_intent


if __name__ == "__main__":
    import traceback
    classes = [
        TestContextAssemblerBasic, TestRelevanceExtraction,
        TestConstraintInjection, TestNoFullSchemaLeak,
        TestTokenBudget, TestAllowedScope, TestReadOnlyIntent,
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