"""
test_intent_intake.py — Phase 13.15 Intent Intake Integration Tests

Covers:
- All 9 PILIntentCategory classifications
- Normalization edge cases
- Risk pre-scanner detection
- IntentEnvelope output shape validation
- IntentIntakeLayer full orchestration
"""
from __future__ import annotations
import sys, os

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, os.path.join(_SRC, "intent_intake"))

from intent_intake_layer import IntentIntakeLayer, IntakeResult
from intent_envelope import IntentEnvelope, PILIntentCategory, RiskLevel
from intent_classifier import PILIntentClassifier
from prompt_normalizer import PromptNormalizer, NormalizedPrompt
from risk_prescanner import RiskPreScanner


class TestPromptNormalizer:
    def setup_method(self):
        self.n = PromptNormalizer()

    def test_returns_normalized_prompt(self):
        r = self.n.normalize("make zombie faster")
        assert isinstance(r, NormalizedPrompt)

    def test_text_field_populated(self):
        r = self.n.normalize("make zombie faster")
        assert "zombie" in r.text.lower()

    def test_char_count_populated(self):
        r = self.n.normalize("make zombie faster")
        assert r.char_count > 0

    def test_not_truncated_for_short_prompt(self):
        r = self.n.normalize("make zombie faster")
        assert not r.was_truncated

    def test_very_long_prompt_truncated(self):
        long = "x " * 1000
        r = self.n.normalize(long)
        assert r.was_truncated or len(r.text) < len(long)

    def test_empty_prompt_handled(self):
        r = self.n.normalize("")
        assert isinstance(r, NormalizedPrompt)

    def test_numeric_value_in_prompt(self):
        r = self.n.normalize("set health to 50")
        assert "50" in r.text

    def test_unicode_prompt_handled(self):
        r = self.n.normalize("make zombie faster 🧟")
        assert isinstance(r, NormalizedPrompt)


class TestRiskPreScanner:
    def setup_method(self):
        self.scanner = RiskPreScanner()

    # Category A — hard blocks (engine internals)
    def test_engine_tick_rate_mutation_blocked(self):
        result = self.scanner.scan("modify engine internal tick rate to zero")
        assert result.is_blocked

    def test_engine_internal_keyword_blocked(self):
        result = self.scanner.scan("set engine tick_rate to 0")
        assert result.is_blocked

    # Category D — low risk (not blocked)
    def test_simple_balance_not_blocked(self):
        result = self.scanner.scan("make the zombie slightly faster")
        assert not result.is_blocked

    def test_health_adjustment_not_blocked(self):
        result = self.scanner.scan("set zombie health to 50")
        assert not result.is_blocked

    def test_detection_radius_not_blocked(self):
        result = self.scanner.scan("increase detection radius to 30")
        assert not result.is_blocked

    # Risk score
    def test_blocked_has_max_risk_score(self):
        result = self.scanner.scan("modify engine internal tick rate")
        assert result.is_blocked
        assert result.risk_score >= 0.9

    def test_safe_has_low_risk_score(self):
        result = self.scanner.scan("set zombie speed to 15")
        assert result.risk_score < 0.8

    def test_risk_flags_populated_on_block(self):
        result = self.scanner.scan("modify engine internal tick rate")
        assert result.is_blocked
        assert len(result.risk_flags) > 0

    def test_is_clean_true_for_safe_prompt(self):
        result = self.scanner.scan("make zombie slightly faster")
        assert result.is_clean

    def test_scan_result_has_is_blocked(self):
        result = self.scanner.scan("anything")
        assert hasattr(result, "is_blocked")


class TestPILIntentClassifier:
    def setup_method(self):
        self.c = PILIntentClassifier()

    # Core categories
    def test_balance_adjustment_numeric(self):
        r = self.c.classify_normalized("set zombie health to 50")
        assert r.category == PILIntentCategory.BALANCE_ADJUSTMENT

    def test_balance_adjustment_make_faster(self):
        r = self.c.classify_normalized("make the zombie move faster")
        assert r.category == PILIntentCategory.BALANCE_ADJUSTMENT

    def test_balance_adjustment_increase_or_unknown(self):
        r = self.c.classify_normalized("increase zombie speed")
        assert r.category in {PILIntentCategory.BALANCE_ADJUSTMENT, PILIntentCategory.UNKNOWN}

    def test_create_feature(self):
        r = self.c.classify_normalized("add a new boss enemy to the game")
        assert r.category == PILIntentCategory.CREATE_FEATURE

    def test_remove_feature(self):
        r = self.c.classify_normalized("remove the zombie actor from the game")
        assert r.category == PILIntentCategory.REMOVE_FEATURE

    def test_modify_feature(self):
        r = self.c.classify_normalized("change the ai behavior model to patrol")
        assert r.category in {
            PILIntentCategory.MODIFY_FEATURE,
            PILIntentCategory.BALANCE_ADJUSTMENT,
        }

    def test_query_explain(self):
        r = self.c.classify_normalized("how does the movement system work")
        assert r.category == PILIntentCategory.QUERY_EXPLAIN

    def test_query_explain_what(self):
        r = self.c.classify_normalized("what does the ai system do")
        assert r.category == PILIntentCategory.QUERY_EXPLAIN

    def test_world_design(self):
        r = self.c.classify_normalized("make the game feel more atmospheric and dark")
        assert r.category == PILIntentCategory.WORLD_DESIGN

    def test_structural_change_or_create(self):
        r = self.c.classify_normalized("add a new collision system to the simulation")
        assert r.category in {
            PILIntentCategory.STRUCTURAL_CHANGE,
            PILIntentCategory.CREATE_FEATURE,
        }

    # Confidence
    def test_confidence_in_range(self):
        r = self.c.classify_normalized("make zombie faster")
        assert 0.0 <= r.confidence <= 1.0

    def test_explicit_prompt_high_confidence(self):
        r = self.c.classify_normalized("set zombie health current to 30")
        assert r.confidence >= 0.5

    # Layer
    def test_matched_layer_populated(self):
        r = self.c.classify_normalized("set zombie speed to 20")
        assert r.matched_layer in {"structural", "keyword", "fallback"}

    # Clarification flag
    def test_requires_clarification_is_bool(self):
        r = self.c.classify_normalized("do something")
        assert isinstance(r.requires_clarification, bool)


class TestIntentEnvelope:
    def test_basic_construction(self):
        env = IntentEnvelope(
            intent_category = PILIntentCategory.BALANCE_ADJUSTMENT,
            normalized_text = "make zombie faster",
            assistance_mode = "COLLABORATIVE",
            confidence      = 0.9,
        )
        assert env.intent_category == PILIntentCategory.BALANCE_ADJUSTMENT
        assert env.confidence == 0.9

    def test_is_blocked_false_by_default(self):
        env = IntentEnvelope(
            intent_category = PILIntentCategory.BALANCE_ADJUSTMENT,
            normalized_text = "faster",
            assistance_mode = "COLLABORATIVE",
            confidence      = 0.8,
        )
        assert not env.is_blocked

    def test_is_read_only_for_query_explain(self):
        env = IntentEnvelope(
            intent_category = PILIntentCategory.QUERY_EXPLAIN,
            normalized_text = "how does it work",
            assistance_mode = "COLLABORATIVE",
            confidence      = 0.9,
        )
        assert env.is_read_only

    def test_mutation_intent_not_read_only(self):
        env = IntentEnvelope(
            intent_category = PILIntentCategory.BALANCE_ADJUSTMENT,
            normalized_text = "make zombie faster",
            assistance_mode = "COLLABORATIVE",
            confidence      = 0.9,
        )
        assert not env.is_read_only

    def test_requires_clarification_default_false(self):
        env = IntentEnvelope(
            intent_category = PILIntentCategory.BALANCE_ADJUSTMENT,
            normalized_text = "make zombie faster",
            assistance_mode = "COLLABORATIVE",
            confidence      = 0.9,
        )
        assert env.requires_clarification is False

    def test_assistance_mode_stored(self):
        env = IntentEnvelope(
            intent_category = PILIntentCategory.BALANCE_ADJUSTMENT,
            normalized_text = "test",
            assistance_mode = "ADVANCED",
            confidence      = 0.8,
        )
        assert env.assistance_mode == "ADVANCED"

    def test_normalized_text_stored(self):
        env = IntentEnvelope(
            intent_category = PILIntentCategory.BALANCE_ADJUSTMENT,
            normalized_text = "make zombie faster",
            assistance_mode = "COLLABORATIVE",
            confidence      = 0.8,
        )
        assert env.normalized_text == "make zombie faster"

    def test_goes_to_diagnostic_for_query(self):
        env = IntentEnvelope(
            intent_category = PILIntentCategory.QUERY_EXPLAIN,
            normalized_text = "how does it work",
            assistance_mode = "COLLABORATIVE",
            confidence      = 0.9,
        )
        assert env.goes_to_diagnostic

    def test_mutation_does_not_go_to_diagnostic(self):
        env = IntentEnvelope(
            intent_category = PILIntentCategory.BALANCE_ADJUSTMENT,
            normalized_text = "make zombie faster",
            assistance_mode = "COLLABORATIVE",
            confidence      = 0.9,
        )
        assert not env.goes_to_diagnostic


class TestIntentIntakeLayer:
    def setup_method(self):
        self.layer = IntentIntakeLayer()

    def test_returns_intake_result(self):
        result = self.layer.process("make zombie faster", "COLLABORATIVE")
        assert isinstance(result, IntakeResult)

    def test_envelope_populated(self):
        result = self.layer.process("make zombie faster", "COLLABORATIVE")
        assert isinstance(result.envelope, IntentEnvelope)

    def test_balance_adjustment_classified(self):
        result = self.layer.process("set zombie health to 50", "COLLABORATIVE")
        assert result.envelope.intent_category == PILIntentCategory.BALANCE_ADJUSTMENT

    def test_make_faster_is_balance(self):
        result = self.layer.process("make the zombie move faster", "COLLABORATIVE")
        assert result.envelope.intent_category == PILIntentCategory.BALANCE_ADJUSTMENT

    def test_query_explain_classified(self):
        result = self.layer.process("how does the movement system work", "COLLABORATIVE")
        assert result.envelope.intent_category == PILIntentCategory.QUERY_EXPLAIN

    def test_query_explain_is_read_only(self):
        result = self.layer.process("how does the movement system work", "COLLABORATIVE")
        assert result.envelope.is_read_only

    def test_create_feature_classified(self):
        result = self.layer.process("add a new boss enemy", "COLLABORATIVE")
        assert result.envelope.intent_category == PILIntentCategory.CREATE_FEATURE

    def test_remove_feature_classified(self):
        result = self.layer.process("remove the zombie actor", "COLLABORATIVE")
        assert result.envelope.intent_category == PILIntentCategory.REMOVE_FEATURE

    def test_engine_internal_blocked(self):
        result = self.layer.process("modify engine internal tick rate", "COLLABORATIVE")
        assert result.was_blocked

    def test_safe_prompt_not_blocked(self):
        result = self.layer.process("set zombie speed to 15", "COLLABORATIVE")
        assert not result.was_blocked

    def test_assistance_mode_stored(self):
        result = self.layer.process("make zombie faster", "ADVANCED")
        assert result.envelope.assistance_mode == "ADVANCED"

    def test_never_raises_on_empty(self):
        result = self.layer.process("", "COLLABORATIVE")
        assert isinstance(result, IntakeResult)

    def test_never_raises_on_garbage(self):
        result = self.layer.process("!@#$%^&*()", "COLLABORATIVE")
        assert isinstance(result, IntakeResult)

    def test_confidence_populated(self):
        result = self.layer.process("set zombie health to 50", "COLLABORATIVE")
        assert 0.0 <= result.envelope.confidence <= 1.0

    def test_scan_result_attached(self):
        result = self.layer.process("make zombie faster", "COLLABORATIVE")
        assert result.scan is not None
        assert isinstance(result.scan.risk_score, float)

    def test_classification_attached_when_not_blocked(self):
        result = self.layer.process("make zombie faster", "COLLABORATIVE")
        if not result.was_blocked:
            assert result.classification is not None
            assert result.classification.matched_layer in {"structural", "keyword", "fallback"}

    def test_fully_assisted_mode(self):
        result = self.layer.process("make zombie slightly faster", "FULLY_ASSISTED")
        assert result.envelope.assistance_mode == "FULLY_ASSISTED"

    def test_architect_mode(self):
        result = self.layer.process("restructure the system graph", "ARCHITECT_MODE")
        assert result.envelope.assistance_mode == "ARCHITECT_MODE"

    def test_world_design_classified(self):
        result = self.layer.process("make the game feel more atmospheric", "COLLABORATIVE")
        assert result.envelope.intent_category == PILIntentCategory.WORLD_DESIGN


if __name__ == "__main__":
    import traceback
    classes = [
        TestPromptNormalizer, TestRiskPreScanner, TestPILIntentClassifier,
        TestIntentEnvelope, TestIntentIntakeLayer,
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