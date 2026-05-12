"""
complexity_classifier.py — ComplexityClassifier
=================================================
Classifies a PIL call into a ComplexityTier before any model is selected.

## Why a Classifier?
Without classification, every prompt — including "set zombie health to 80"
— routes to the same expensive 5-pass premium model pipeline. Classification
enforces Inference Invariant II2: TIER_S intents route to the deterministic
Phase 12 GDE path with zero LLM calls.

## Dependency Design
ComplexityClassifier operates on ClassificationInput, NOT on
GDE's IntentObject or PIL's LLMContextPacket directly.
This keeps packages/inference/ free of imports from packages/gde/
or packages/prompt-intelligence/ (which would create a circular
dependency: PIL imports inference, inference would import PIL).

PIL fills ClassificationInput from IntentObject before calling the
classifier. The mapping is trivial — see ClassificationInput below.

## Four Tiers

    TIER_S — Deterministic shortcut. Zero LLM calls.
              Phase 12 GDE handles the mutation entirely.
              Conditions (ALL must be true):
                - intent is SetValue or ModifyValue or ScaleValue
                - confidence >= 0.85
                - no structural changes (no ADD_ACTOR, ADD_RULE, etc.)
                - no code generation needed
                - no rule creation
                - exactly 1 target field resolved
                - estimated_prompt_tokens <= TIER_S_TOKEN_CAP (512)
                - not a query or diagnostic
                - not explicitly flagged as needing LLM

    TIER_M — Cheap/fast model (Haiku 4.5, DeepSeek V4 Flash, MiniMax M2.5).
              Validation-shaped: self-critique, balance adjustments,
              simple schema queries, single-field mutations that are
              too ambiguous for TIER_S.
              estimated_prompt_tokens <= TIER_M_TOKEN_CAP (4096)
              and no structural changes and no code generation.

    TIER_L — Standard model (Sonnet 4.6, DeepSeek V4 Pro, GLM-5.1).
              All non-structural mutations that exceed TIER_M thresholds,
              moderate-complexity design changes, multi-field mutations.

    TIER_XL — Premium model (Opus 4.7, GPT-5.5).
               Structural changes (ADD_ACTOR, ADD_SYSTEM, ADD_RULE),
               code generation required, architectural queries,
               large context (estimated_prompt_tokens > TIER_L_TOKEN_CAP).

## Deterministic Classification
The classifier is entirely rule-based — no LLM, no randomness.
Same ClassificationInput always produces the same ComplexityTier.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .model_descriptor import ComplexityTier


# ── Token Thresholds ──────────────────────────────────────────────────────────

TIER_S_TOKEN_CAP =   512    # trivial prompts only
TIER_M_TOKEN_CAP = 4_096    # small-context cheap model
TIER_L_TOKEN_CAP = 16_000   # standard model upper bound; above goes XL


# ── GDE Intent Type Constants (mirrored — no import from GDE) ─────────────────
# These match GDEIntentType in packages/gde — kept in sync manually.

_VALUE_MUTATION_INTENTS = frozenset({
    "SetValue", "ModifyValue", "ScaleValue",
})
_STRUCTURAL_INTENTS = frozenset({
    "CreateActor", "RemoveActor",
    "AddComponent", "RemoveComponent",
    "CreateSystem", "RemoveSystem",
    "DefineRule", "RemoveRule",
})
_QUERY_INTENTS = frozenset({
    "QueryValue", "QueryExplain",
})
_DIAGNOSTIC_INTENTS = frozenset({
    "DebugIssue",    # goes through diagnostic_orchestrator, 2-pass
})


# ── Classification Input ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class ClassificationInput:
    """
    Provider-agnostic description of one PIL call to be classified.

    PIL fills this from IntentObject + LLMContextPacket before calling
    ComplexityClassifier. inference/ package never imports GDE directly.

    Attributes
    ----------
    intent_type : str
        GDEIntentType string: "SetValue", "CreateActor", etc. "Unknown" = fallback to TIER_L.
    confidence : float
        Intent classification confidence [0.0–1.0].
    is_structural : bool
        True if the intent creates or removes schema nodes.
    needs_code_generation : bool
        True when the mutation requires a new Rust system to be generated.
    has_rule_creation : bool
        True if the intent is DefineRule.
    resolved_path_count : int
        Number of concrete CGS paths resolved for this call.
        0 = still ambiguous; 1 = clean single target; >1 = multi-path.
    estimated_prompt_tokens : int
        Pre-flight token estimate from TokenEstimator.
        0 = not yet estimated (treated as unknown → conservative tier).
    is_query : bool
        True for QueryValue or QueryExplain intents.
    is_diagnostic : bool
        True for DebugIssue intents (replay divergence, explain, etc.).
    force_llm : bool
        If True, skip TIER_S regardless of other signals.
        Set by mode_controller when user is in ADVANCED mode and
        explicitly invoked a full-pipeline run.
    assistance_mode : str
        Current mode: FULLY_ASSISTED|COLLABORATIVE|ADVANCED|ARCHITECT_MODE.
        ARCHITECT_MODE always bypasses TIER_S classification.
    has_existing_path_hints : bool
        True when ScopeResolver found at least one concrete path hint.
    """

    intent_type:              str   = "Unknown"
    confidence:               float = 0.0
    is_structural:            bool  = False
    needs_code_generation:    bool  = False
    has_rule_creation:        bool  = False
    resolved_path_count:      int   = 0
    estimated_prompt_tokens:  int   = 0
    is_query:                 bool  = False
    is_diagnostic:            bool  = False
    force_llm:                bool  = False
    assistance_mode:          str   = "COLLABORATIVE"
    has_existing_path_hints:  bool  = False

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ClassificationInput":
        """Constructs from a plain dict (for tests and PIL bridge)."""
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ── Classification Result ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class ClassificationResult:
    """
    Output of ComplexityClassifier.classify().

    Attributes
    ----------
    tier : str
        The assigned ComplexityTier.
    reasons : tuple[str, ...]
        Human-readable explanation of why this tier was chosen.
        Used in telemetry and ARCHITECT_MODE debug panel.
    confidence : float
        Classifier's confidence in the tier assignment [0.0–1.0].
        High confidence → route without further question.
        Low confidence → model_router may choose a more conservative tier.
    """

    tier:       str
    reasons:    tuple[str, ...]
    confidence: float = 1.0

    def __repr__(self) -> str:
        return f"ClassificationResult({self.tier}, conf={self.confidence:.2f})"


# ── Complexity Classifier ─────────────────────────────────────────────────────

class ComplexityClassifier:
    """
    Classifies a PIL call into a ComplexityTier.

    Stateless — one instance shared across all InferenceAdapter calls.
    Deterministic — same ClassificationInput always → same tier.

    Usage
    -----
        classifier = ComplexityClassifier()

        result = classifier.classify(ClassificationInput(
            intent_type             = "SetValue",
            confidence              = 0.95,
            is_structural           = False,
            needs_code_generation   = False,
            has_rule_creation       = False,
            resolved_path_count     = 1,
            estimated_prompt_tokens = 380,
            is_query                = False,
            is_diagnostic           = False,
            has_existing_path_hints = True,
        ))
        print(result.tier)   # "TIER_S"

        # From PIL, before dispatching:
        if result.tier == ComplexityTier.S:
            return gde_orchestrator.process_intent(intent)  # no LLM
    """

    def classify(self, inp: ClassificationInput) -> ClassificationResult:
        """
        Classifies one call and returns a ClassificationResult.

        Evaluation order:
            1. Hard overrides (force_llm, ARCHITECT_MODE) → skip TIER_S
            2. Diagnostic check → TIER_L (2-pass diagnostic_orchestrator)
            3. Code generation → TIER_XL
            4. Structural changes → TIER_XL
            5. Rule creation → TIER_XL
            6. TIER_S eligibility check (all conditions)
            7. Token cap routing → TIER_M or TIER_L
            8. Fallback → TIER_L
        """
        reasons: list[str] = []

        # ── Step 1: Hard overrides ────────────────────────────────────────────
        if inp.force_llm:
            reasons.append("force_llm=True: caller explicitly requested full LLM pipeline.")
            return ClassificationResult(
                tier=ComplexityTier.L, reasons=tuple(reasons), confidence=0.95
            )

        # ── Step 2: Diagnostic → 2-pass path, TIER_L (diagnostic_orchestrator) ──
        if inp.is_diagnostic or inp.intent_type in _DIAGNOSTIC_INTENTS:
            reasons.append(
                f"Diagnostic intent '{inp.intent_type}' routes through "
                f"diagnostic_orchestrator (2-pass explain→suggest), not the "
                f"5-pass mutation pipeline. TIER_L appropriate."
            )
            return ClassificationResult(
                tier=ComplexityTier.L, reasons=tuple(reasons), confidence=0.95
            )

        # ── Step 3: Code generation → TIER_XL ────────────────────────────────
        if inp.needs_code_generation:
            reasons.append(
                "Code generation required (Rust ISystem generation via "
                "code_generation_engine). Needs TIER_XL: code_gen capability."
            )
            return ClassificationResult(
                tier=ComplexityTier.XL, reasons=tuple(reasons), confidence=1.0
            )

        # ── Step 4: Structural changes → TIER_XL ─────────────────────────────
        if inp.is_structural or inp.intent_type in _STRUCTURAL_INTENTS:
            reasons.append(
                f"Structural intent '{inp.intent_type}' (adds/removes schema nodes). "
                f"Requires TIER_XL for reliable planning pass."
            )
            return ClassificationResult(
                tier=ComplexityTier.XL, reasons=tuple(reasons), confidence=0.95
            )

        # ── Step 5: Rule creation → TIER_XL ──────────────────────────────────
        if inp.has_rule_creation:
            reasons.append(
                "Rule creation detected. Condition/effect expression generation "
                "requires TIER_XL to correctly write deterministic rule syntax."
            )
            return ClassificationResult(
                tier=ComplexityTier.XL, reasons=tuple(reasons), confidence=0.92
            )

        # ── Step 6: Large context → TIER_XL before checking TIER_S ──────────
        if (
            inp.estimated_prompt_tokens > TIER_L_TOKEN_CAP
            and inp.estimated_prompt_tokens > 0
        ):
            reasons.append(
                f"Estimated prompt tokens ({inp.estimated_prompt_tokens}) exceeds "
                f"TIER_L cap ({TIER_L_TOKEN_CAP}). TIER_XL has largest context window."
            )
            return ClassificationResult(
                tier=ComplexityTier.XL, reasons=tuple(reasons), confidence=0.90
            )

        # ── Step 7: TIER_S eligibility — all conditions must pass ─────────────
        tier_s_result = self._check_tier_s(inp)
        if tier_s_result is not None:
            return tier_s_result

        # ── Step 8: Token cap → TIER_M ───────────────────────────────────────
        if (
            inp.estimated_prompt_tokens <= TIER_M_TOKEN_CAP
            and inp.estimated_prompt_tokens > 0
            and not inp.is_structural
            and not inp.needs_code_generation
        ):
            reasons.append(
                f"Small prompt ({inp.estimated_prompt_tokens} tokens ≤ {TIER_M_TOKEN_CAP}), "
                f"no structural changes, no code generation → TIER_M."
            )
            return ClassificationResult(
                tier=ComplexityTier.M, reasons=tuple(reasons), confidence=0.85
            )

        # ── Step 9: Default → TIER_L ─────────────────────────────────────────
        reasons.append(
            f"No TIER_S/M/XL condition matched. Defaulting to TIER_L "
            f"(standard_mutation model, 5-pass pipeline). "
            f"intent={inp.intent_type!r}, tokens={inp.estimated_prompt_tokens}, "
            f"confidence={inp.confidence:.2f}."
        )
        return ClassificationResult(
            tier=ComplexityTier.L, reasons=tuple(reasons), confidence=0.80
        )

    # ── TIER_S check ──────────────────────────────────────────────────────────

    @staticmethod
    def _check_tier_s(inp: ClassificationInput) -> ClassificationResult | None:
        """
        Returns a TIER_S result if ALL conditions pass, else None.
        ALL conditions must be true — one failure means at least TIER_M.
        """
        reasons: list[str] = []
        failures: list[str] = []

        # Must be a value mutation intent
        if inp.intent_type not in _VALUE_MUTATION_INTENTS:
            failures.append(
                f"intent_type '{inp.intent_type}' is not a value mutation "
                f"(SetValue/ModifyValue/ScaleValue)."
            )

        # High confidence required
        if inp.confidence < 0.85:
            failures.append(
                f"confidence {inp.confidence:.2f} < 0.85 threshold. "
                f"Ambiguous intent needs LLM clarification."
            )

        # No structural changes
        if inp.is_structural:
            failures.append("is_structural=True — structural changes are TIER_XL.")

        # No code generation
        if inp.needs_code_generation:
            failures.append("needs_code_generation=True — code gen is TIER_XL.")

        # No rule creation
        if inp.has_rule_creation:
            failures.append("has_rule_creation=True — rule creation is TIER_XL.")

        # Exactly one resolved path (unambiguous target)
        if inp.resolved_path_count != 1:
            failures.append(
                f"resolved_path_count={inp.resolved_path_count}, expected exactly 1. "
                f"Multiple paths require LLM disambiguation."
            )

        # Not a query
        if inp.is_query:
            failures.append("is_query=True — queries route through TIER_L explain path.")

        # Has at least one concrete path hint
        if not inp.has_existing_path_hints:
            failures.append(
                "has_existing_path_hints=False — no concrete CGS path resolved yet. "
                "Phase 12 GDE needs a path to mutate."
            )

        # Small enough prompt
        if inp.estimated_prompt_tokens > TIER_S_TOKEN_CAP:
            failures.append(
                f"estimated_prompt_tokens {inp.estimated_prompt_tokens} > "
                f"TIER_S cap {TIER_S_TOKEN_CAP}. Needs richer context → TIER_M+."
            )

        if failures:
            return None   # not eligible for TIER_S

        # All checks passed
        reasons.append(
            f"TIER_S: deterministic shortcut. "
            f"intent={inp.intent_type!r}, confidence={inp.confidence:.2f}, "
            f"path_count=1, tokens={inp.estimated_prompt_tokens}. "
            f"Phase 12 GDE handles this without LLM (Inference Invariant II2)."
        )
        return ClassificationResult(
            tier=ComplexityTier.S,
            reasons=tuple(reasons),
            confidence=0.97,
        )

    # ── Introspection ─────────────────────────────────────────────────────────

    def tier_s_conditions(self) -> list[str]:
        """Returns human-readable list of TIER_S conditions. Used in docs/UI."""
        return [
            f"intent_type in {{SetValue, ModifyValue, ScaleValue}}",
            f"confidence >= 0.85",
            f"is_structural = False",
            f"needs_code_generation = False",
            f"has_rule_creation = False",
            f"resolved_path_count = 1",
            f"is_query = False",
            f"has_existing_path_hints = True",
            f"estimated_prompt_tokens <= {TIER_S_TOKEN_CAP}",
        ]