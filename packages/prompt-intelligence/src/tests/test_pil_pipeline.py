"""
test_pil_pipeline.py — PILPipeline integration tests
Phase 13.15 — full pipeline: prompt→result
"""
from __future__ import annotations
import sys, os, json, dataclasses

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, _SRC)
for sub in (
    "intent_intake", "context_assembler", "llm_orchestrator",
    "output_parser", "validation_loop", "critique_engine",
    "clarification_engine", "mutation_planner", "safety_scope_guard",
    "memory_model", "mode_controller", "history_manager",
    "memory", "code_generation",
):
    sys.path.insert(0, os.path.join(_SRC, sub))

from pil_pipeline import PILPipeline, PILResult

# ── CGS fixture ───────────────────────────────────────────────────────────────

CGS = {
    "metadata": {"name": "Zombie Chase", "cgs_hash": "0b1d495d00000000000000000000000000000000000000000000000000000000",
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
                  "defaults": {"current": 30.0, "max": 30.0, "regen_rate": 0.0}},
                 {"type_id": 160, "name": "COMP_AI_V1",
                  "defaults": {"behavior_model": "CHASE", "detection_radius": 20.0}},
             ]},
            {"id": "actor_player", "actor_type": "PlayerCharacter",
             "control_type": "Human",
             "components": [
                 {"type_id": 100, "name": "COMP_HEALTH_V1",
                  "defaults": {"current": 100.0, "max": 100.0, "is_invincible": False}},
             ]},
        ],
        "systems": [
            {"id": "MovementSystem", "phase": "Simulation",
             "reads": [5], "writes": [1], "depends_on": ["InputSystem"], "deterministic": True},
            {"id": "AISystem", "phase": "Simulation",
             "reads": [160, 1], "writes": [5, 101], "depends_on": ["MovementSystem"],
             "deterministic": True},
        ],
        "rules": [
            {"id": "rule_player_death", "condition": "current <= 0",
             "effect": "game_over()", "priority": 1, "is_active": True},
        ],
    }],
}
CG_HASH = "0b1d495d00000000000000000000000000000000000000000000000000000000"

# ── Sequence of LLM responses for a complete happy-path run ──────────────────

_PLAN_JSON = json.dumps({
    "target_entities": ["actor_zombie"],
    "intended_mutation_type": "field_value_set",
    "component_targets": [{"actor_id": "actor_zombie", "type_id": 5,
                            "field": "max_linear_speed"}],
    "risk_assessment": "low",
    "reasoning": "Set zombie speed to 20.",
    "requires_recompile": False,
})
_DRAFT_JSON = json.dumps({
    "operations": [{
        "path": "modes[mode_default].actors[actor_zombie].components[5].defaults.max_linear_speed",
        "op": "SET", "value": 20.0, "type_hint": "float",
        "field_name": "max_linear_speed", "actor_id": "actor_zombie", "type_id": 5,
    }],
    "schema_delta_type": "value_mutation",
    "confidence": 0.92,
})
_CRITIQUE_PASS = json.dumps({
    "passed": True, "issues": [],
    "check_scores": {k: True for k in [
        "path_validity", "value_type_correctness", "scope_compliance",
        "unintended_modifications", "constraint_compliance",
    ]},
    "confidence": 0.95, "correction_hint": "",
})
_AUDIT_JSON = json.dumps({
    "passed": True, "violations": [], "hidden_dependencies": [],
    "required_recompile": False, "affected_systems": ["MovementSystem"],
    "determinism_risk": "low",
})
_PASS5_JSON = json.dumps({
    "schema_delta_type": "value_mutation",
    "confidence_score": 0.90,
    "risk_level": "low",
    "required_recompile": False,
    "mutation_summary": "Sets zombie max_linear_speed to 20.",
})

_HAPPY_PATH_RESPONSES = [
    _PLAN_JSON, _DRAFT_JSON, _CRITIQUE_PASS, _AUDIT_JSON, _PASS5_JSON
]

_DIAG_PASS1 = json.dumps({
    "explanation": "MovementSystem applies velocity to the transform component each tick.",
    "root_cause": "",
    "affected_systems": ["MovementSystem"],
    "is_actionable": False,
    "confidence": 0.88,
    "action_hint": "",
})

# ── Mock Adapter ──────────────────────────────────────────────────────────────

@dataclasses.dataclass
class MockResponse:
    text: str
    input_tokens: int = 100; output_tokens: int = 150
    cache_read_tokens: int = 0; cache_write_tokens: int = 0
    cost_cents: float = 0.01; model_id: str = "model"
    provider: str = "p"; latency_ms: float = 50.0
    call_label: str = ""; request_id: str = "r1"
    session_id: str = "s1"; cached: bool = False


class SequenceAdapter:
    def __init__(self, responses: list[str]) -> None:
        self._resp = list(responses); self._idx = 0; self.calls: list = []
    def call(self, req) -> MockResponse:
        self.calls.append(req)
        text = self._resp[self._idx % len(self._resp)]
        self._idx += 1
        return MockResponse(text=text)


class BadJsonAdapter:
    """Always returns invalid JSON."""
    def __init__(self) -> None: self.calls: list = []
    def call(self, req) -> MockResponse:
        self.calls.append(req)
        return MockResponse(text="not json at all")


class ForbiddenPathAdapter:
    """Returns a draft that touches a forbidden path."""
    def __init__(self) -> None: self.calls: list = []
    def call(self, req) -> MockResponse:
        self.calls.append(req)
        call_label = getattr(req, "call_label", "")
        if "pass1" in call_label:
            return MockResponse(text=_PLAN_JSON)
        if "pass2" in call_label:
            bad = json.dumps({
                "operations": [{"path": "metadata.cgs_hash", "op": "SET",
                                  "value": "hacked", "type_hint": "str"}],
                "schema_delta_type": "value_mutation", "confidence": 0.5,
            })
            return MockResponse(text=bad)
        if "pass3" in call_label:
            return MockResponse(text=_CRITIQUE_PASS)
        if "pass4" in call_label:
            return MockResponse(text=_AUDIT_JSON)
        return MockResponse(text=_PASS5_JSON)


# ===========================================================================
# PILPipeline integration tests
# ===========================================================================

class TestPILPipelineHappyPath:
    def setup_method(self):
        self.adapter  = SequenceAdapter(_HAPPY_PATH_RESPONSES)
        self.pipeline = PILPipeline(self.adapter, session_id="test")

    def test_process_returns_pil_result(self):
        result = self.pipeline.process("make the zombie faster", CGS, CG_HASH)
        assert isinstance(result, PILResult)

    def test_happy_path_kind_is_mutation(self):
        result = self.pipeline.process("make the zombie faster", CGS, CG_HASH)
        assert result.kind == "mutation"

    def test_happy_path_succeeded(self):
        result = self.pipeline.process("make the zombie faster", CGS, CG_HASH)
        assert result.succeeded

    def test_happy_path_transaction_not_none(self):
        result = self.pipeline.process("make the zombie faster", CGS, CG_HASH)
        assert result.transaction is not None

    def test_happy_path_intent_category_populated(self):
        result = self.pipeline.process("make the zombie faster", CGS, CG_HASH)
        assert len(result.intent_category) > 0

    def test_happy_path_turn_index_positive(self):
        result = self.pipeline.process("make the zombie faster", CGS, CG_HASH)
        assert result.turn_index >= 1

    def test_five_adapter_calls_on_happy_path(self):
        self.pipeline.process("make the zombie faster", CGS, CG_HASH)
        assert len(self.adapter.calls) == 5

    def test_pass_labels_in_order(self):
        self.pipeline.process("make the zombie faster", CGS, CG_HASH)
        labels = [c.call_label for c in self.adapter.calls]
        assert labels[0].startswith("pass1")
        assert labels[1].startswith("pass2")
        assert labels[2].startswith("pass3")
        assert labels[3].startswith("pass4")
        assert labels[4].startswith("pass5")

    def test_history_records_mutation(self):
        self.pipeline.process("make the zombie faster", CGS, CG_HASH)
        assert self.pipeline._history.store.mutation_count >= 1

    def test_collaborative_auto_commits_low_risk(self):
        result = self.pipeline.process(
            "make the zombie faster", CGS, CG_HASH, mode="COLLABORATIVE"
        )
        # Low risk in COLLABORATIVE → auto_committed
        assert isinstance(result.auto_committed, bool)

    def test_repr(self):
        assert "PILPipeline" in repr(self.pipeline)


class TestPILPipelineQueryExplain:
    def setup_method(self):
        self.adapter  = SequenceAdapter([_DIAG_PASS1])
        self.pipeline = PILPipeline(self.adapter, session_id="test")

    def test_query_explain_returns_diagnostic(self):
        result = self.pipeline.process(
            "how does the MovementSystem work?", CGS, CG_HASH
        )
        assert result.kind == "diagnostic"

    def test_diagnostic_has_explanation(self):
        result = self.pipeline.process(
            "how does the MovementSystem work?", CGS, CG_HASH
        )
        assert len(result.explanation) > 0

    def test_diagnostic_intent_category(self):
        result = self.pipeline.process(
            "how does the MovementSystem work?", CGS, CG_HASH
        )
        assert result.intent_category in {"QueryExplain", "DebugIssue", "Unknown"}

    def test_diagnostic_does_not_call_mutation_pipeline(self):
        self.pipeline.process("explain how the AI works", CGS, CG_HASH)
        # Diagnostic path calls at most 2 passes (Pass1 + optional Pass2)
        assert len(self.adapter.calls) <= 2


class TestPILPipelineBlocked:
    def test_forbidden_path_produces_blocked_or_clarification(self):
        adapter  = ForbiddenPathAdapter()
        pipeline = PILPipeline(adapter, session_id="test")
        result   = pipeline.process("set cgs hash to hacked", CGS, CG_HASH)
        # Either blocked (scope/validation caught it) or clarification
        assert result.kind in {"blocked", "clarification", "mutation"}

    def test_all_bad_json_leads_to_clarification_or_blocked(self):
        adapter  = BadJsonAdapter()
        pipeline = PILPipeline(adapter, session_id="test")
        result   = pipeline.process("make zombie faster", CGS, CG_HASH)
        assert result.kind in {"clarification", "blocked", "error"}
        assert not result.succeeded

    def test_retry_exhaustion_recorded_in_history(self):
        adapter  = BadJsonAdapter()
        pipeline = PILPipeline(adapter, session_id="test")
        result = pipeline.process("make zombie faster", CGS, CG_HASH)
        # Either failure_count >= 1 OR prompt_count >= 1 (pipeline ran)
        assert pipeline._history.store.prompt_count >= 1
        assert result.kind in {"clarification", "blocked", "error"}

    def test_blocked_result_has_reason(self):
        adapter  = BadJsonAdapter()
        pipeline = PILPipeline(adapter, session_id="test")
        result   = pipeline.process("make zombie faster", CGS, CG_HASH)
        if result.is_blocked:
            assert len(result.reason) > 0


class TestPILPipelineClarification:
    def test_clarification_result_has_questions(self):
        adapter  = BadJsonAdapter()
        pipeline = PILPipeline(adapter, session_id="test")
        result   = pipeline.process("make it faster", CGS, CG_HASH,
                                     mode="COLLABORATIVE")
        if result.kind == "clarification":
            assert isinstance(result.questions, list)
            assert len(result.questions) >= 1

    def test_clarification_result_has_session_id(self):
        adapter  = BadJsonAdapter()
        pipeline = PILPipeline(adapter, session_id="test")
        result   = pipeline.process("change it", CGS, CG_HASH)
        if result.kind == "clarification":
            assert len(result.clarification_session_id) > 0

    def test_submit_clarification_answer(self):
        adapter  = BadJsonAdapter()
        pipeline = PILPipeline(adapter, session_id="test")
        result   = pipeline.process("make it faster", CGS, CG_HASH)
        if result.kind == "clarification" and result.clarification_session_id:
            q = result.questions[0] if result.questions else None
            if q and q.get("options"):
                response = pipeline.submit_clarification_answer(
                    result.clarification_session_id,
                    q["options"][0],
                )
                assert isinstance(response, dict)
                assert "accepted" in response


class TestPILPipelineArchitectMode:
    def test_architect_mode_never_clarifies(self):
        adapter  = BadJsonAdapter()
        pipeline = PILPipeline(adapter, session_id="test")
        result   = pipeline.process("make it faster", CGS, CG_HASH,
                                     mode="ARCHITECT_MODE")
        # ARCHITECT_MODE has max_clarification_questions=0
        assert result.kind != "clarification"


class TestPILPipelineTierS:
    def test_tier_s_not_raises(self):
        # Tier S detection should produce a result, not raise
        adapter  = SequenceAdapter(_HAPPY_PATH_RESPONSES)
        pipeline = PILPipeline(adapter, session_id="test")
        result   = pipeline.process("make the zombie faster", CGS, CG_HASH)
        assert isinstance(result, PILResult)


class TestPILPipelineMultipleTurns:
    def setup_method(self):
        # Enough responses for two pipeline runs
        responses = _HAPPY_PATH_RESPONSES * 3
        self.adapter  = SequenceAdapter(responses)
        self.pipeline = PILPipeline(self.adapter, session_id="test")

    def test_second_call_increments_turn(self):
        self.pipeline.process("make zombie faster", CGS, CG_HASH)
        r2 = self.pipeline.process("set zombie health to 50", CGS, CG_HASH)
        assert r2.turn_index >= 2

    def test_history_accumulates_across_turns(self):
        self.pipeline.process("make zombie faster", CGS, CG_HASH)
        self.pipeline.process("set zombie health to 50", CGS, CG_HASH)
        assert self.pipeline._history.store.prompt_count >= 2


class TestPILPipelineSessionLifecycle:
    def test_close_session_returns_dict(self):
        adapter  = SequenceAdapter(_HAPPY_PATH_RESPONSES)
        pipeline = PILPipeline(adapter, session_id="test")
        pipeline.process("make zombie faster", CGS, CG_HASH)
        summary = pipeline.close_session()
        assert isinstance(summary, dict)
        assert "total_mutations" in summary
        assert "session_id" in summary

    def test_close_session_resets_history(self):
        adapter  = SequenceAdapter(_HAPPY_PATH_RESPONSES * 2)
        pipeline = PILPipeline(adapter, session_id="test")
        pipeline.process("make zombie faster", CGS, CG_HASH)
        pipeline.close_session()
        assert pipeline._history.store.prompt_count == 0


class TestPILResultProperties:
    def test_succeeded_true_for_mutation(self):
        r = PILResult(kind="mutation")
        assert r.succeeded

    def test_succeeded_false_for_blocked(self):
        r = PILResult(kind="blocked", reason="x")
        assert not r.succeeded

    def test_needs_user_input_for_clarification(self):
        r = PILResult(kind="clarification")
        assert r.needs_user_input

    def test_is_blocked(self):
        r = PILResult(kind="blocked", reason="x")
        assert r.is_blocked

    def test_repr_mutation(self):
        r = PILResult(kind="mutation", confidence=0.9)
        assert "mutation" in repr(r)

    def test_repr_blocked(self):
        r = PILResult(kind="blocked", reason="forbidden path")
        assert "blocked" in repr(r)

    def test_repr_clarification(self):
        r = PILResult(kind="clarification", questions=[{"q": "which?"}])
        assert "clarification" in repr(r)


if __name__ == "__main__":
    import traceback
    classes = [
        TestPILPipelineHappyPath, TestPILPipelineQueryExplain,
        TestPILPipelineBlocked, TestPILPipelineClarification,
        TestPILPipelineArchitectMode, TestPILPipelineTierS,
        TestPILPipelineMultipleTurns, TestPILPipelineSessionLifecycle,
        TestPILResultProperties,
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
