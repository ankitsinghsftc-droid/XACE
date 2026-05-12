"""
tests/test_complexity_classifier.py
=====================================
Tests for ComplexityClassifier and ClassificationInput.
"""

from __future__ import annotations

import pytest

from ..src.complexity_classifier import (
    ComplexityClassifier, ClassificationInput,
    TIER_S_TOKEN_CAP, TIER_M_TOKEN_CAP, TIER_L_TOKEN_CAP,
)
from ..src.model_descriptor import ComplexityTier


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _tier_s_input(**overrides) -> ClassificationInput:
    """Returns the minimal valid TIER_S input (all conditions satisfied)."""
    defaults = dict(
        intent_type             = "SetValue",
        confidence              = 0.95,
        is_structural           = False,
        needs_code_generation   = False,
        has_rule_creation       = False,
        resolved_path_count     = 1,
        estimated_prompt_tokens = 300,
        is_query                = False,
        is_diagnostic           = False,
        force_llm               = False,
        has_existing_path_hints = True,
        assistance_mode         = "COLLABORATIVE",
    )
    defaults.update(overrides)
    return ClassificationInput(**defaults)


# ── TIER_S Classification ─────────────────────────────────────────────────────

class TestTierSClassification:

    def setup_method(self) -> None:
        self.clf = ComplexityClassifier()

    def test_clean_set_value_is_tier_s(self) -> None:
        result = self.clf.classify(_tier_s_input())
        assert result.tier == ComplexityTier.S

    def test_modify_value_is_tier_s(self) -> None:
        result = self.clf.classify(_tier_s_input(intent_type="ModifyValue"))
        assert result.tier == ComplexityTier.S

    def test_scale_value_is_tier_s(self) -> None:
        result = self.clf.classify(_tier_s_input(intent_type="ScaleValue"))
        assert result.tier == ComplexityTier.S

    def test_tier_s_confidence_is_high(self) -> None:
        result = self.clf.classify(_tier_s_input())
        assert result.confidence >= 0.90

    def test_tier_s_reason_mentions_deterministic(self) -> None:
        result = self.clf.classify(_tier_s_input())
        assert any("deterministic" in r.lower() for r in result.reasons)


# ── Each TIER_S Condition Blocks Independently ────────────────────────────────

class TestTierSConditionBlocking:

    def setup_method(self) -> None:
        self.clf = ComplexityClassifier()

    def test_wrong_intent_type_blocks_tier_s(self) -> None:
        result = self.clf.classify(_tier_s_input(intent_type="CreateActor"))
        assert result.tier != ComplexityTier.S

    def test_low_confidence_blocks_tier_s(self) -> None:
        result = self.clf.classify(_tier_s_input(confidence=0.70))
        assert result.tier != ComplexityTier.S

    def test_confidence_exactly_at_threshold(self) -> None:
        # 0.85 is the minimum — exactly at threshold should pass
        result = self.clf.classify(_tier_s_input(confidence=0.85))
        assert result.tier == ComplexityTier.S

    def test_confidence_just_below_threshold_blocks(self) -> None:
        result = self.clf.classify(_tier_s_input(confidence=0.849))
        assert result.tier != ComplexityTier.S

    def test_is_structural_blocks_tier_s(self) -> None:
        result = self.clf.classify(_tier_s_input(is_structural=True))
        assert result.tier == ComplexityTier.XL   # structural → XL

    def test_needs_code_generation_blocks_tier_s(self) -> None:
        result = self.clf.classify(_tier_s_input(needs_code_generation=True))
        assert result.tier == ComplexityTier.XL

    def test_has_rule_creation_blocks_tier_s(self) -> None:
        result = self.clf.classify(_tier_s_input(has_rule_creation=True))
        assert result.tier == ComplexityTier.XL

    def test_zero_resolved_paths_blocks_tier_s(self) -> None:
        result = self.clf.classify(_tier_s_input(resolved_path_count=0))
        assert result.tier != ComplexityTier.S

    def test_two_resolved_paths_blocks_tier_s(self) -> None:
        result = self.clf.classify(_tier_s_input(resolved_path_count=2))
        assert result.tier != ComplexityTier.S

    def test_is_query_blocks_tier_s(self) -> None:
        result = self.clf.classify(_tier_s_input(is_query=True))
        assert result.tier != ComplexityTier.S

    def test_no_path_hints_blocks_tier_s(self) -> None:
        result = self.clf.classify(_tier_s_input(has_existing_path_hints=False))
        assert result.tier != ComplexityTier.S

    def test_large_prompt_blocks_tier_s(self) -> None:
        result = self.clf.classify(_tier_s_input(
            estimated_prompt_tokens=TIER_S_TOKEN_CAP + 1
        ))
        assert result.tier != ComplexityTier.S

    def test_exactly_at_tier_s_token_cap_passes(self) -> None:
        result = self.clf.classify(_tier_s_input(
            estimated_prompt_tokens=TIER_S_TOKEN_CAP
        ))
        assert result.tier == ComplexityTier.S

    def test_force_llm_overrides_tier_s(self) -> None:
        result = self.clf.classify(_tier_s_input(force_llm=True))
        assert result.tier != ComplexityTier.S


# ── TIER_XL Classification ────────────────────────────────────────────────────

class TestTierXLClassification:

    def setup_method(self) -> None:
        self.clf = ComplexityClassifier()

    def test_code_generation_is_tier_xl(self) -> None:
        result = self.clf.classify(ClassificationInput(
            intent_type           = "CreateSystem",
            confidence            = 0.9,
            needs_code_generation = True,
        ))
        assert result.tier == ComplexityTier.XL

    def test_structural_intent_is_tier_xl(self) -> None:
        for intent in ["CreateActor", "RemoveActor", "AddComponent",
                       "CreateSystem", "DefineRule"]:
            result = self.clf.classify(ClassificationInput(
                intent_type  = intent,
                confidence   = 0.9,
                is_structural = True,
            ))
            assert result.tier == ComplexityTier.XL, \
                f"Expected XL for {intent}, got {result.tier}"

    def test_rule_creation_is_tier_xl(self) -> None:
        result = self.clf.classify(ClassificationInput(
            intent_type      = "DefineRule",
            confidence       = 0.9,
            has_rule_creation = True,
        ))
        assert result.tier == ComplexityTier.XL

    def test_large_context_is_tier_xl(self) -> None:
        result = self.clf.classify(ClassificationInput(
            intent_type             = "SetValue",
            confidence              = 0.9,
            estimated_prompt_tokens = TIER_L_TOKEN_CAP + 1,
        ))
        assert result.tier == ComplexityTier.XL

    def test_xl_confidence_is_high(self) -> None:
        result = self.clf.classify(ClassificationInput(
            intent_type           = "CreateActor",
            needs_code_generation = True,
        ))
        assert result.confidence >= 0.90


# ── TIER_M Classification ─────────────────────────────────────────────────────

class TestTierMClassification:

    def setup_method(self) -> None:
        self.clf = ComplexityClassifier()

    def test_small_non_structural_without_path_is_tier_m(self) -> None:
        result = self.clf.classify(ClassificationInput(
            intent_type             = "SetValue",
            confidence              = 0.75,   # below 0.85 → not TIER_S
            estimated_prompt_tokens = 500,    # above TIER_S cap
            is_structural           = False,
            has_existing_path_hints = False,
        ))
        assert result.tier == ComplexityTier.M

    def test_prompt_below_tier_m_cap_is_tier_m(self) -> None:
        result = self.clf.classify(ClassificationInput(
            intent_type             = "ModifyValue",
            confidence              = 0.60,   # low confidence → not TIER_S
            estimated_prompt_tokens = TIER_M_TOKEN_CAP,
            is_structural           = False,
        ))
        assert result.tier == ComplexityTier.M


# ── TIER_L Classification ─────────────────────────────────────────────────────

class TestTierLClassification:

    def setup_method(self) -> None:
        self.clf = ComplexityClassifier()

    def test_diagnostic_is_tier_l(self) -> None:
        result = self.clf.classify(ClassificationInput(
            intent_type   = "DebugIssue",
            confidence    = 0.9,
            is_diagnostic = True,
        ))
        assert result.tier == ComplexityTier.L

    def test_query_explain_intent_is_tier_l(self) -> None:
        result = self.clf.classify(ClassificationInput(
            intent_type = "QueryExplain",
            confidence  = 0.9,
            is_query    = True,
        ))
        assert result.tier == ComplexityTier.L

    def test_medium_prompt_defaults_to_tier_l(self) -> None:
        result = self.clf.classify(ClassificationInput(
            intent_type             = "SetValue",
            confidence              = 0.9,
            estimated_prompt_tokens = TIER_M_TOKEN_CAP + 100,
            resolved_path_count     = 1,
            has_existing_path_hints = True,
            is_structural           = False,
        ))
        # Tokens exceed TIER_M cap and below TIER_L cap → TIER_L default
        assert result.tier == ComplexityTier.L

    def test_unknown_intent_defaults_to_tier_l(self) -> None:
        result = self.clf.classify(ClassificationInput(
            intent_type = "Unknown",
            confidence  = 0.2,
        ))
        # Unknown + low confidence → not TIER_S, falls to TIER_L
        assert result.tier in (ComplexityTier.L, ComplexityTier.M)

    def test_force_llm_gives_tier_l(self) -> None:
        # force_llm with a TIER_S-eligible intent → TIER_L
        result = self.clf.classify(_tier_s_input(force_llm=True))
        assert result.tier == ComplexityTier.L


# ── ClassificationInput ───────────────────────────────────────────────────────

class TestClassificationInput:

    def test_from_dict(self) -> None:
        inp = ClassificationInput.from_dict({
            "intent_type": "SetValue",
            "confidence":  0.9,
            "is_structural": False,
        })
        assert inp.intent_type == "SetValue"
        assert inp.confidence  == 0.9
        assert inp.is_structural == False

    def test_from_dict_ignores_unknown_keys(self) -> None:
        # Should not raise on extra keys
        inp = ClassificationInput.from_dict({
            "intent_type": "SetValue",
            "unknown_key": "ignored",
        })
        assert inp.intent_type == "SetValue"

    def test_defaults_are_safe(self) -> None:
        inp = ClassificationInput()
        assert inp.intent_type == "Unknown"
        assert inp.confidence  == 0.0
        # Defaults must never accidentally classify as TIER_S
        result = ComplexityClassifier().classify(inp)
        assert result.tier != ComplexityTier.S

    def test_tier_s_conditions_list(self) -> None:
        clf = ComplexityClassifier()
        conditions = clf.tier_s_conditions()
        assert len(conditions) == 9
        assert any("confidence" in c for c in conditions)
        assert any("resolved_path_count" in c for c in conditions)