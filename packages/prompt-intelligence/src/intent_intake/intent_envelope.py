"""
intent_envelope.py — IntentEnvelope + PILIntentCategory
==========================================================
Output struct of the PIL Intent Intake layer.

IntentEnvelope is produced by IntentIntakeLayer and consumed by every
downstream PIL submodule. It carries the PIL-level (high-level) intent
classification — the 9-category taxonomy that PIL uses to route a prompt
through the correct pipeline path.

## PIL vs GDE Intent Classification — Do Not Confuse These

    PIL IntentCategory (this file) — 9 broad categories
        Maps a designer's prompt to a pipeline path.
        Answers: "what KIND of thing does the user want to do?"
        Examples: CreateFeature, BalanceAdjustment, QueryExplain

    GDE GDEIntentType (packages/gde) — 15 granular DSL operations
        Maps a classified intent to a specific CGS mutation type.
        Answers: "what SPECIFIC operation does this require?"
        Examples: SetValue, CreateActor, DefineRule

    PIL classifies first → GDE refines further.
    A PIL StructuralChange maps to GDE CreateActor or AddComponent or
    CreateSystem depending on slot extraction. The levels are separate
    by design — PIL routing must not depend on GDE internals.

## IntentEnvelope Lifecycle

    raw prompt
        → PromptNormalizer.normalize()   → NormalizedPrompt
        → PILIntentClassifier.classify() → PILIntentCategory + confidence
        → RiskPreScanner.scan()          → risk_score, risk_flags
        → IntentEnvelope (assembled here by IntentIntakeLayer)
        → ContextAssembler              → LLMContextPacket
        → LLMOrchestrator (5-pass)      → MutationTransaction
        → ...

## Risk Score

    risk_score is in [0.0, 1.0]:
        0.0–0.29  SAFE      proceed automatically in all modes
        0.30–0.59 LOW       proceed with soft warning in FULLY_ASSISTED
        0.60–0.79 MODERATE  requires explicit confirmation in COLLABORATIVE
        0.80–1.0  HIGH      blocked unless ADVANCED/ARCHITECT_MODE confirms

## Immutability

    IntentEnvelope is frozen after construction. Downstream modules
    must not mutate it — they read from it to build their own outputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── PIL Intent Category ───────────────────────────────────────────────────────

class PILIntentCategory:
    """
    9-category PIL-level intent taxonomy.

    These are the routing categories PIL uses to select the correct
    pipeline path. They are coarser than GDE's GDEIntentType — each
    PIL category maps to one or more GDE intent types.

    Mapping to pipeline path:
        CREATE/MODIFY/REMOVE/STRUCTURAL  → 5-pass LLM mutation pipeline
        BALANCE_ADJUSTMENT               → TIER_M (cheap validation model)
        QUERY_EXPLAIN / DEBUG_ISSUE      → 2-pass diagnostic_orchestrator (II7)
        WORLD_DESIGN                     → TIER_L (multi-entity context needed)
        UNKNOWN                          → ClarificationEngine immediately
    """

    CREATE_FEATURE      = "CreateFeature"       # Add a new game element (actor, system, rule)
    MODIFY_FEATURE      = "ModifyFeature"       # Change an existing element's behaviour
    REMOVE_FEATURE      = "RemoveFeature"       # Delete an element entirely
    QUERY_EXPLAIN       = "QueryExplain"        # "How does X work?" / "Show me Y" — read-only
    DEBUG_ISSUE         = "DebugIssue"          # "Why is X broken?" — diagnostic 2-pass path
    BALANCE_ADJUSTMENT  = "BalanceAdjustment"   # Tune numeric values (speed, health, damage)
    STRUCTURAL_CHANGE   = "StructuralChange"    # Schema architecture changes (new system, mode)
    WORLD_DESIGN        = "WorldDesign"         # High-level design ("make it feel like a shooter")
    UNKNOWN             = "Unknown"             # Unclassifiable → ClarificationEngine

    @classmethod
    def all_categories(cls) -> frozenset[str]:
        return frozenset({
            cls.CREATE_FEATURE, cls.MODIFY_FEATURE, cls.REMOVE_FEATURE,
            cls.QUERY_EXPLAIN, cls.DEBUG_ISSUE, cls.BALANCE_ADJUSTMENT,
            cls.STRUCTURAL_CHANGE, cls.WORLD_DESIGN, cls.UNKNOWN,
        })

    @classmethod
    def is_read_only(cls, category: str) -> bool:
        """True if this category never produces a CGS mutation."""
        return category in {cls.QUERY_EXPLAIN, cls.DEBUG_ISSUE}

    @classmethod
    def is_structural(cls, category: str) -> bool:
        """True if this category involves schema architecture changes."""
        return category in {cls.CREATE_FEATURE, cls.REMOVE_FEATURE, cls.STRUCTURAL_CHANGE}

    @classmethod
    def requires_llm(cls, category: str) -> bool:
        """
        True if this category always requires at least one LLM call.
        BALANCE_ADJUSTMENT may route to TIER_S (GDE deterministic) when
        confidence is high and target is unambiguous — ComplexityClassifier
        makes the final call, this is just the general rule.
        """
        return category not in {cls.UNKNOWN}

    @classmethod
    def diagnostic_path(cls, category: str) -> bool:
        """True if this category routes through diagnostic_orchestrator (II7)."""
        return category in {cls.QUERY_EXPLAIN, cls.DEBUG_ISSUE}

    @classmethod
    def to_gde_hint(cls, category: str) -> list[str]:
        """
        Returns a list of likely GDEIntentType values for this category.
        Used by IntentIntakeLayer to prime the GDE classifier.
        This is a hint only — GDE's own classifier makes the binding decision.
        """
        _MAP: dict[str, list[str]] = {
            cls.CREATE_FEATURE:     ["CreateActor", "CreateSystem", "DefineRule"],
            cls.MODIFY_FEATURE:     ["ModifyValue", "SetValue", "ModifyRule"],
            cls.REMOVE_FEATURE:     ["RemoveActor", "RemoveComponent", "RemoveSystem", "RemoveRule"],
            cls.QUERY_EXPLAIN:      ["QueryExplain", "QueryValue"],
            cls.DEBUG_ISSUE:        ["QueryExplain"],
            cls.BALANCE_ADJUSTMENT: ["SetValue", "ScaleValue", "ModifyValue"],
            cls.STRUCTURAL_CHANGE:  ["CreateActor", "AddComponent", "CreateSystem"],
            cls.WORLD_DESIGN:       ["CreateActor", "DefineRule", "CreateSystem"],
            cls.UNKNOWN:            ["Unknown"],
        }
        return _MAP.get(category, ["Unknown"])


# ── Risk Level ────────────────────────────────────────────────────────────────

class RiskLevel:
    """Named risk thresholds used to interpret IntentEnvelope.risk_score."""
    SAFE     = "SAFE"       # 0.00–0.29
    LOW      = "LOW"        # 0.30–0.59
    MODERATE = "MODERATE"   # 0.60–0.79
    HIGH     = "HIGH"       # 0.80–1.00

    @classmethod
    def from_score(cls, score: float) -> str:
        if score < 0.30:
            return cls.SAFE
        if score < 0.60:
            return cls.LOW
        if score < 0.80:
            return cls.MODERATE
        return cls.HIGH


# ── Intent Envelope ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class IntentEnvelope:
    """
    Immutable output of the PIL Intent Intake layer.

    Produced by IntentIntakeLayer, consumed by ContextAssembler and
    all downstream PIL submodules. Carries the normalized prompt,
    PIL-level classification, and pre-scan risk assessment.

    Attributes
    ----------
    intent_category : str
        One of PILIntentCategory constants. Set by PILIntentClassifier.
    normalized_text : str
        Whitespace-trimmed, quote-normalized, control-char-stripped prompt.
        Language-detected and token-estimated. Set by PromptNormalizer.
    raw_text : str
        Original prompt before normalization. Preserved for audit/display.
    assistance_mode : str
        Current ModeController mode at intake time. Snapshot — does not
        update if mode changes during pipeline execution.
    confidence : float
        PILIntentClassifier confidence for intent_category [0.0–1.0].
    requires_clarification : bool
        True when confidence < mode threshold OR RiskPreScanner flags
        ambiguity. ClarificationEngine is invoked before the 5-pass pipeline.
    risk_score : float
        RiskPreScanner score [0.0–1.0]. See RiskLevel for interpretation.
    risk_flags : tuple[str, ...]
        Specific risk signals detected by RiskPreScanner.
        Examples: "engine_internal_mutation", "code_injection_attempt",
        "forbidden_scope", "destructive_without_confirmation".
    estimated_tokens : int
        Token estimate from PromptNormalizer. Used by ComplexityClassifier
        and ContextAssembler for budget pre-flight.
    detected_language : str
        ISO 639-1 language code ("en", "zh", "es", etc.).
        "en" default when detection is inconclusive.
    session_id : str | None
        Builder session identifier for provenance and telemetry.
    """

    intent_category:        str
    normalized_text:        str
    raw_text:               str             = ""
    assistance_mode:        str             = "COLLABORATIVE"
    confidence:             float           = 0.0
    requires_clarification: bool            = False
    risk_score:             float           = 0.0
    risk_flags:             tuple[str, ...] = field(default_factory=tuple)
    estimated_tokens:       int             = 0
    detected_language:      str             = "en"
    session_id:             str | None      = None

    # ── Convenience Properties ────────────────────────────────────────────────

    @property
    def risk_level(self) -> str:
        return RiskLevel.from_score(self.risk_score)

    @property
    def is_safe(self) -> bool:
        return self.risk_score < 0.30

    @property
    def is_blocked(self) -> bool:
        """True if risk is HIGH and mode doesn't allow override."""
        return self.risk_score >= 0.80 and self.assistance_mode not in {
            "ADVANCED", "ARCHITECT_MODE"
        }

    @property
    def is_read_only(self) -> bool:
        return PILIntentCategory.is_read_only(self.intent_category)

    @property
    def is_structural(self) -> bool:
        return PILIntentCategory.is_structural(self.intent_category)

    @property
    def goes_to_diagnostic(self) -> bool:
        """True if this envelope routes to diagnostic_orchestrator (II7)."""
        return PILIntentCategory.diagnostic_path(self.intent_category)

    @property
    def gde_intent_hints(self) -> list[str]:
        """Likely GDEIntentType values for this PIL category."""
        return PILIntentCategory.to_gde_hint(self.intent_category)

    @property
    def is_confident(self) -> bool:
        return self.confidence >= 0.70

    # ── Factories ─────────────────────────────────────────────────────────────

    @classmethod
    def unknown(
        cls,
        raw_text:       str,
        assistance_mode: str       = "COLLABORATIVE",
        session_id:     str | None = None,
    ) -> "IntentEnvelope":
        """Creates an UNKNOWN envelope for unclassifiable prompts."""
        return cls(
            intent_category        = PILIntentCategory.UNKNOWN,
            normalized_text        = raw_text.strip(),
            raw_text               = raw_text,
            assistance_mode        = assistance_mode,
            confidence             = 0.0,
            requires_clarification = True,
            risk_score             = 0.0,
            session_id             = session_id,
        )

    @classmethod
    def blocked(
        cls,
        raw_text:    str,
        risk_flags:  tuple[str, ...],
        session_id:  str | None = None,
    ) -> "IntentEnvelope":
        """Creates a HIGH-risk blocked envelope from RiskPreScanner."""
        return cls(
            intent_category        = PILIntentCategory.UNKNOWN,
            normalized_text        = raw_text.strip(),
            raw_text               = raw_text,
            confidence             = 0.0,
            requires_clarification = False,   # not ambiguous — blocked outright
            risk_score             = 1.0,
            risk_flags             = risk_flags,
            session_id             = session_id,
        )

    # ── Serialization ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Returns a JSON-serializable dict for telemetry and logging."""
        return {
            "intent_category":        self.intent_category,
            "normalized_text":        self.normalized_text[:200],   # cap for logs
            "assistance_mode":        self.assistance_mode,
            "confidence":             round(self.confidence, 3),
            "requires_clarification": self.requires_clarification,
            "risk_score":             round(self.risk_score, 3),
            "risk_level":             self.risk_level,
            "risk_flags":             list(self.risk_flags),
            "estimated_tokens":       self.estimated_tokens,
            "detected_language":      self.detected_language,
            "session_id":             self.session_id,
        }

    def __repr__(self) -> str:
        risk  = f" risk={self.risk_level}" if not self.is_safe else ""
        clarify = " [clarify]" if self.requires_clarification else ""
        return (
            f"IntentEnvelope({self.intent_category!r}, "
            f"conf={self.confidence:.2f}{risk}{clarify})"
        )