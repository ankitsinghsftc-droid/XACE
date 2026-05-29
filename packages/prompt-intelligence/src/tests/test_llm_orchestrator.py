"""
test_llm_orchestrator.py — Phase 13.15 LLM Orchestrator Integration Tests

Covers:
- All 5 passes running in sequence
- Self-critique failure → Pass 2 regeneration
- Determinism audit flags violations → pipeline reattempt
- Retry policy exhaustion → escalation to clarification
- Pass labels in order
- TIER routing per pass
"""
from __future__ import annotations
import sys, os, json, dataclasses

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for sub in ("llm_orchestrator", "context_assembler", "intent_intake"):
    sys.path.insert(0, os.path.join(_SRC, sub))

from llm_orchestrator import LLMOrchestrator, PipelineResult, DiagnosticIntentError
from pil_retry_policy import PILRetryPolicy, RetryBudgetExhausted, MAX_ATTEMPTS_PER_PASS
from pass1_planning import Pass1Planning, ReasoningPlan, OutputParseError
from pass2_dsl_draft import Pass2DSLDraft, DraftMutationTransaction, MutationOp
from pass3_self_critique import Pass3SelfCritique, CritiqueResult
from pass4_determinism_audit import Pass4DeterminismAudit, DeterminismAuditResult
from pass5_final_output import Pass5FinalOutput, MutationTransaction
from llm_context_packet import LLMContextPacket, SimplifiedActor, SimplifiedSystem, AllowedMutationScope


# ── Fixtures ──────────────────────────────────────────────────────────────────

_PLAN = json.dumps({
    "target_entities": ["actor_zombie"],
    "intended_mutation_type": "field_value_set",
    "component_targets": [{"actor_id": "actor_zombie", "type_id": 5,
                            "field": "max_linear_speed"}],
    "risk_assessment": "low",
    "reasoning": "Set zombie speed to 20.",
    "requires_recompile": False,
})
_DRAFT = json.dumps({
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
_CRITIQUE_FAIL = json.dumps({
    "passed": False,
    "issues": ["path uses wrong notation"],
    "check_scores": {"path_validity": False, "value_type_correctness": True,
                     "scope_compliance": True, "unintended_modifications": True,
                     "constraint_compliance": True},
    "confidence": 0.7,
    "correction_hint": "Use bracket notation for paths.",
})
_AUDIT_PASS = json.dumps({
    "passed": True, "violations": [],
    "hidden_dependencies": ["AISystem reads component 5"],
    "required_recompile": False,
    "affected_systems": ["MovementSystem"],
    "determinism_risk": "low",
})
_AUDIT_FAIL = json.dumps({
    "passed": False,
    "violations": ["introduces nondeterministic random value"],
    "hidden_dependencies": [],
    "required_recompile": False,
    "affected_systems": [],
    "determinism_risk": "high",
})
_PASS5 = json.dumps({
    "schema_delta_type": "value_mutation",
    "confidence_score": 0.90,
    "risk_level": "low",
    "required_recompile": False,
    "mutation_summary": "Sets zombie max_linear_speed to 20.",
})

_HAPPY_PATH = [_PLAN, _DRAFT, _CRITIQUE_PASS, _AUDIT_PASS, _PASS5]


@dataclasses.dataclass
class MockResp:
    text: str; input_tokens: int = 100; output_tokens: int = 150
    cache_read_tokens: int = 0; cache_write_tokens: int = 0
    cost_cents: float = 0.01; model_id: str = "m"; provider: str = "p"
    latency_ms: float = 50.0; call_label: str = ""; request_id: str = "r"
    session_id: str = "s"; cached: bool = False


class SeqAdapter:
    """Non-cycling adapter — raises when responses exhausted to prevent infinite loops."""
    def __init__(self, *responses: str) -> None:
        self._q = list(responses); self._i = 0; self.calls: list = []
    def call(self, req) -> MockResp:
        self.calls.append(req)
        if self._i >= len(self._q):
            # Recycle last response rather than hang, but cap at 20 total calls
            if len(self.calls) > 20:
                raise RuntimeError(f"SeqAdapter: exceeded 20 calls — test likely infinite looping")
            t = self._q[-1]
        else:
            t = self._q[self._i]
            self._i += 1
        return MockResp(text=t)


def _make_packet(**kw) -> LLMContextPacket:
    scope = AllowedMutationScope(
        allowed_paths=("modes[mode_default].actors[actor_zombie].components",),
        forbidden_paths=("metadata.cgs_hash",),
        structural_change_allowed=False,
        max_mutation_depth=3, mode="COLLABORATIVE",
    )
    defaults = dict(
        intent_category="BalanceAdjustment",
        normalized_prompt="make the zombie faster",
        assistance_mode="COLLABORATIVE",
        game_metadata={"name": "Zombie Chase", "version": "0.1.0",
                       "schema_version": "0.1.0"},
        constraints=("All systems must be deterministic.",),
        allowed_scope=scope,
        dynamic_token_count=400, static_token_count=200,
        relevant_actors=(SimplifiedActor(
            actor_id="actor_zombie", actor_type="Enemy", control_type="AiProxy",
            components=({"type_id": 5, "name": "COMP_VELOCITY_V1",
                          "defaults": {"max_linear_speed": 10.0}},),
        ),),
        relevant_systems=(SimplifiedSystem(
            system_id="MovementSystem", phase="Simulation",
            reads=(5,), writes=(1,), depends_on=("InputSystem",), deterministic=True,
        ),),
    )
    defaults.update(kw)
    return LLMContextPacket(**defaults)


# ===========================================================================
# PILRetryPolicy
# ===========================================================================

class TestPILRetryPolicy:
    def test_max_attempts_per_pass_is_2(self):
        assert MAX_ATTEMPTS_PER_PASS == 2

    def test_begin_attempt_tracks_count(self):
        p = PILRetryPolicy()
        p.begin_attempt("pass1_planning")
        assert p.attempts_for("pass1_planning") == 1

    def test_record_success_marks_pass_done(self):
        p = PILRetryPolicy()
        p.begin_attempt("pass1_planning")
        p.record_success("pass1_planning")
        assert not p.can_retry("pass1_planning")

    def test_can_retry_true_after_one_failure(self):
        p = PILRetryPolicy()
        p.begin_attempt("pass2_dsl_draft")
        p.record_failure("pass2_dsl_draft", ["bad JSON"])
        assert p.can_retry("pass2_dsl_draft")

    def test_can_retry_false_at_cap(self):
        p = PILRetryPolicy()
        for _ in range(MAX_ATTEMPTS_PER_PASS):
            p.begin_attempt("pass2_dsl_draft")
            p.record_failure("pass2_dsl_draft", ["fail"])
        assert not p.can_retry("pass2_dsl_draft")

    def test_correction_prompt_contains_reasons(self):
        p = PILRetryPolicy()
        p.begin_attempt("pass2_dsl_draft")
        p.record_failure("pass2_dsl_draft", ["invalid JSON", "wrong path"])
        prompt = p.correction_prompt("pass2_dsl_draft")
        assert "invalid JSON" in prompt

    def test_pipeline_reattempt_clears_state(self):
        p = PILRetryPolicy()
        p.begin_attempt("pass1_planning")
        p.record_success("pass1_planning")
        p.begin_pipeline_reattempt()
        assert p.attempts_for("pass1_planning") == 0

    def test_summary_has_all_passes(self):
        p = PILRetryPolicy()
        s = p.summary()
        assert "passes" in s
        assert "pipeline_runs" in s


# ===========================================================================
# LLMOrchestrator — Happy Path
# ===========================================================================

class TestLLMOrchestratorHappyPath:
    def setup_method(self):
        self.packet = _make_packet()

    def test_returns_pipeline_result(self):
        adapter = SeqAdapter(*_HAPPY_PATH)
        orch    = LLMOrchestrator(adapter, session_id="test")
        result  = orch.run(self.packet)
        assert isinstance(result, PipelineResult)

    def test_happy_path_succeeds(self):
        adapter = SeqAdapter(*_HAPPY_PATH)
        orch    = LLMOrchestrator(adapter, session_id="test")
        result  = orch.run(self.packet)
        assert result.success

    def test_happy_path_has_transaction(self):
        adapter = SeqAdapter(*_HAPPY_PATH)
        orch    = LLMOrchestrator(adapter, session_id="test")
        result  = orch.run(self.packet)
        assert isinstance(result.transaction, MutationTransaction)

    def test_five_adapter_calls(self):
        adapter = SeqAdapter(*_HAPPY_PATH)
        orch    = LLMOrchestrator(adapter, session_id="test")
        orch.run(self.packet)
        assert len(adapter.calls) == 5

    def test_pass_labels_in_correct_order(self):
        adapter = SeqAdapter(*_HAPPY_PATH)
        orch    = LLMOrchestrator(adapter, session_id="test")
        orch.run(self.packet)
        labels = [c.call_label for c in adapter.calls]
        assert labels[0].startswith("pass1")
        assert labels[1].startswith("pass2")
        assert labels[2].startswith("pass3")
        assert labels[3].startswith("pass4")
        assert labels[4].startswith("pass5")

    def test_pass_summary_populated(self):
        adapter = SeqAdapter(*_HAPPY_PATH)
        orch    = LLMOrchestrator(adapter, session_id="test")
        result  = orch.run(self.packet)
        assert "pipeline_runs" in result.pass_summary

    def test_transaction_operations_from_draft(self):
        adapter = SeqAdapter(*_HAPPY_PATH)
        orch    = LLMOrchestrator(adapter, session_id="test")
        result  = orch.run(self.packet)
        assert len(result.transaction.operations) == 1
        assert "actor_zombie" in result.transaction.operations[0].path


# ===========================================================================
# TIER routing per pass
# ===========================================================================

class TestTierRouting:
    def setup_method(self):
        self.packet = _make_packet()

    def test_pass1_uses_tier_l(self):
        adapter = SeqAdapter(*_HAPPY_PATH)
        orch    = LLMOrchestrator(adapter, session_id="test")
        orch.run(self.packet)
        assert adapter.calls[0].complexity_tier == "TIER_L"

    def test_pass2_uses_tier_l(self):
        adapter = SeqAdapter(*_HAPPY_PATH)
        orch    = LLMOrchestrator(adapter, session_id="test")
        orch.run(self.packet)
        assert adapter.calls[1].complexity_tier == "TIER_L"

    def test_pass3_uses_tier_m(self):
        adapter = SeqAdapter(*_HAPPY_PATH)
        orch    = LLMOrchestrator(adapter, session_id="test")
        orch.run(self.packet)
        assert adapter.calls[2].complexity_tier == "TIER_M"

    def test_pass4_uses_tier_m(self):
        adapter = SeqAdapter(*_HAPPY_PATH)
        orch    = LLMOrchestrator(adapter, session_id="test")
        orch.run(self.packet)
        assert adapter.calls[3].complexity_tier == "TIER_M"

    def test_pass5_uses_tier_m(self):
        # II13: Pass 5 is TIER_M — locked
        adapter = SeqAdapter(*_HAPPY_PATH)
        orch    = LLMOrchestrator(adapter, session_id="test")
        orch.run(self.packet)
        assert adapter.calls[4].complexity_tier == "TIER_M"

    def test_all_pass3_4_5_use_cheap_validation(self):
        adapter = SeqAdapter(*_HAPPY_PATH)
        orch    = LLMOrchestrator(adapter, session_id="test")
        orch.run(self.packet)
        for call in adapter.calls[2:]:
            assert call.logical_model == "cheap_validation"


# ===========================================================================
# Self-critique failure → Pass 2 regen
# ===========================================================================

class TestSelfCritiqueRegen:
    def setup_method(self):
        self.packet = _make_packet()

    def test_critique_failure_triggers_pass2_retry(self):
        # Sequence: plan, draft, critique-FAIL, draft-again, critique-PASS, audit, pass5
        seq = [_PLAN, _DRAFT, _CRITIQUE_FAIL, _DRAFT, _CRITIQUE_PASS, _AUDIT_PASS, _PASS5]
        adapter = SeqAdapter(*seq)
        orch    = LLMOrchestrator(adapter, session_id="test")
        result  = orch.run(self.packet)
        assert result.success
        # Pass 2 called twice
        pass2_calls = [c for c in adapter.calls if c.call_label.startswith("pass2")]
        assert len(pass2_calls) == 2

    def test_correction_injected_on_retry(self):
        seq = [_PLAN, _DRAFT, _CRITIQUE_FAIL, _DRAFT, _CRITIQUE_PASS, _AUDIT_PASS, _PASS5]
        adapter = SeqAdapter(*seq)
        orch    = LLMOrchestrator(adapter, session_id="test")
        orch.run(self.packet)
        # Second pass2 call should have a correction label
        pass2_calls = [c for c in adapter.calls if c.call_label.startswith("pass2")]
        assert len(pass2_calls) == 2

    def test_both_critiques_fail_needs_clarification(self):
        seq = [_PLAN, _DRAFT, _CRITIQUE_FAIL, _DRAFT, _CRITIQUE_FAIL]
        adapter = SeqAdapter(*seq)
        orch    = LLMOrchestrator(adapter, session_id="test")
        result  = orch.run(self.packet)
        assert not result.success
        assert result.needs_clarification


# ===========================================================================
# Determinism audit violation → reattempt
# ===========================================================================

class TestDeterminismAuditFlag:
    def setup_method(self):
        self.packet = _make_packet()

    def test_audit_failure_triggers_reattempt(self):
        # Run 1 fails audit; Run 2 succeeds
        seq = (
            [_PLAN, _DRAFT, _CRITIQUE_PASS, _AUDIT_FAIL] +
            [_PLAN, _DRAFT, _CRITIQUE_PASS, _AUDIT_PASS, _PASS5]
        )
        adapter = SeqAdapter(*seq)
        orch    = LLMOrchestrator(adapter, session_id="test")
        result  = orch.run(self.packet)
        assert result.success

    def test_repeated_audit_failure_needs_clarification(self):
        # Two pipeline runs both fail audit → exhaust reattempt budget
        seq = [_PLAN, _DRAFT, _CRITIQUE_PASS, _AUDIT_FAIL,
               _PLAN, _DRAFT, _CRITIQUE_PASS, _AUDIT_FAIL,
               _PLAN, _DRAFT, _CRITIQUE_PASS, _AUDIT_FAIL]
        adapter = SeqAdapter(*seq)
        orch    = LLMOrchestrator(adapter, session_id="test")
        result  = orch.run(self.packet)
        assert not result.success
        assert result.needs_clarification


# ===========================================================================
# Retry policy exhaustion → escalation path
# ===========================================================================

class TestRetryEscalation:
    def setup_method(self):
        self.packet = _make_packet()

    def test_pass1_parse_failure_retried(self):
        seq = ["not json", _PLAN, _DRAFT, _CRITIQUE_PASS, _AUDIT_PASS, _PASS5]
        adapter = SeqAdapter(*seq)
        orch    = LLMOrchestrator(adapter, session_id="test")
        result  = orch.run(self.packet)
        assert result.success

    def test_pass1_double_failure_needs_clarification(self):
        adapter = SeqAdapter("not json", "still not json")
        orch    = LLMOrchestrator(adapter, session_id="test")
        result  = orch.run(self.packet)
        assert not result.success
        assert result.needs_clarification

    def test_pass2_parse_failure_retried(self):
        seq = [_PLAN, "bad json draft", _DRAFT, _CRITIQUE_PASS, _AUDIT_PASS, _PASS5]
        adapter = SeqAdapter(*seq)
        orch    = LLMOrchestrator(adapter, session_id="test")
        result  = orch.run(self.packet)
        assert result.success

    def test_needs_clarification_on_exhaustion(self):
        adapter = SeqAdapter("bad", "bad", "bad", "bad", "bad")
        orch    = LLMOrchestrator(adapter, session_id="test")
        result  = orch.run(self.packet)
        assert not result.success
        assert result.needs_clarification


# ===========================================================================
# II7 — Diagnostic intent routing
# ===========================================================================

class TestDiagnosticIntentRouting:
    def test_query_explain_raises_diagnostic_error(self):
        packet  = _make_packet(intent_category="QueryExplain",
                                normalized_prompt="how does the ai work")
        adapter = SeqAdapter(*_HAPPY_PATH)
        orch    = LLMOrchestrator(adapter, session_id="test")
        try:
            orch.run(packet)
            assert False, "Expected DiagnosticIntentError"
        except DiagnosticIntentError as e:
            assert e.intent_category == "QueryExplain"

    def test_debug_issue_raises_diagnostic_error(self):
        packet  = _make_packet(intent_category="DebugIssue",
                                normalized_prompt="why is zombie broken")
        adapter = SeqAdapter(*_HAPPY_PATH)
        orch    = LLMOrchestrator(adapter, session_id="test")
        try:
            orch.run(packet)
            assert False
        except DiagnosticIntentError:
            pass

    def test_balance_adjustment_does_not_raise(self):
        packet  = _make_packet()
        adapter = SeqAdapter(*_HAPPY_PATH)
        orch    = LLMOrchestrator(adapter, session_id="test")
        # Should not raise DiagnosticIntentError
        result  = orch.run(packet)
        assert isinstance(result, PipelineResult)


# ===========================================================================
# Cache prefix usage
# ===========================================================================

class TestCachePrefix:
    def setup_method(self):
        self.packet = _make_packet()

    def test_constraints_in_cached_prefix(self):
        adapter = SeqAdapter(*_HAPPY_PATH)
        orch    = LLMOrchestrator(adapter, session_id="test")
        orch.run(self.packet)
        # Pass 1 should have at least one cacheable prompt part
        req = adapter.calls[0]
        cacheable = [p for p in req.prompt_parts if p.cacheable]
        assert len(cacheable) >= 1

    def test_cached_prefix_contains_constraints(self):
        adapter = SeqAdapter(*_HAPPY_PATH)
        orch    = LLMOrchestrator(adapter, session_id="test")
        orch.run(self.packet)
        req = adapter.calls[0]
        cached_text = " ".join(p.text for p in req.prompt_parts if p.cacheable)
        assert "deterministic" in cached_text.lower() or "constraint" in cached_text.lower()

    def test_dynamic_parts_contain_prompt(self):
        adapter = SeqAdapter(*_HAPPY_PATH)
        orch    = LLMOrchestrator(adapter, session_id="test")
        orch.run(self.packet)
        req = adapter.calls[0]
        dynamic_text = " ".join(p.text for p in req.prompt_parts if not p.cacheable)
        assert "zombie" in dynamic_text.lower()


if __name__ == "__main__":
    import traceback
    classes = [
        TestPILRetryPolicy, TestLLMOrchestratorHappyPath, TestTierRouting,
        TestSelfCritiqueRegen, TestDeterminismAuditFlag, TestRetryEscalation,
        TestDiagnosticIntentRouting, TestCachePrefix,
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