"""
intent_classifier.py — PILIntentClassifier
============================================
Classifies a normalized designer prompt into one of 9 PIL intent categories.

## This is NOT GDE's IntentClassifier

    GDE's IntentClassifier (packages/gde/src/prompt_interpretation/)
        → 15 granular DSL categories (SetValue, CreateActor, DefineRule, ...)
        → Answers: "what CGS operation does this require?"
        → Output: IntentObject

    PIL's PILIntentClassifier (this file)
        → 9 high-level pipeline-routing categories
        → Answers: "which PIL pipeline path does this prompt take?"
        → Output: PILIntentCategory + confidence score

    These run independently. PIL classifies first for pipeline routing;
    GDE re-classifies later for DSL operation selection. They are not
    interchangeable. Do not merge them.

## 9 Categories and Their Pipeline Paths

    CreateFeature      → 5-pass mutation pipeline, TIER_XL (structural)
    ModifyFeature      → 5-pass mutation pipeline, TIER_L or TIER_S
    RemoveFeature      → 5-pass mutation pipeline, TIER_XL (structural + destructive)
    QueryExplain       → diagnostic_orchestrator 2-pass (II7, read-only)
    DebugIssue         → diagnostic_orchestrator 2-pass (II7, read-only)
    BalanceAdjustment  → 5-pass pipeline, may shortcut to TIER_S via GDE
    StructuralChange   → 5-pass pipeline, TIER_XL
    WorldDesign        → 5-pass pipeline, TIER_L (broad multi-entity context)
    Unknown            → ClarificationEngine before any pipeline

## Classification Strategy

    Layer 1 — Structural pattern matching (high confidence, first-match wins)
    Layer 2 — Keyword scoring (accumulate signals, pick winner above threshold)
    Layer 3 — Fallback to Unknown with clarification required

    All layers are deterministic and LLM-free. Same input → same output.
    This classifier runs sub-millisecond; it is safe to call on keystrokes.

## Confidence Interpretation

    ≥ 0.85  High — proceed without clarification
    0.65–0.84  Medium — proceed with hint shown to user (COLLABORATIVE)
    0.40–0.64  Low — flag requires_clarification in FULLY_ASSISTED/COLLABORATIVE
    < 0.40   Very low → Unknown treatment
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from intent_envelope import PILIntentCategory


# ── Thresholds ────────────────────────────────────────────────────────────────

CONFIDENCE_HIGH       = 0.85   # no clarification
CONFIDENCE_MEDIUM     = 0.65   # clarification depends on mode
CONFIDENCE_MIN        = 0.40   # below this → Unknown treatment


# ── Structural Patterns ───────────────────────────────────────────────────────
# Ordered — first match wins. Patterns are compiled once at module load.

_STRUCTURAL_PATTERNS: list[tuple[re.Pattern, str, float]] = [

    # ── QueryExplain: question-word starters (highest priority) ───────────────
    (re.compile(r'^(?:what|how|why|which|when|where|who|show me|explain|describe|tell me|list)\b', re.I),
     PILIntentCategory.QUERY_EXPLAIN, 0.88),

    (re.compile(r'\bwhat (?:is|are|does|will)\b', re.I),
     PILIntentCategory.QUERY_EXPLAIN, 0.87),

    # ── DebugIssue: bug/broken language ───────────────────────────────────────
    (re.compile(r'\b(?:bug|broken|not working|doesn\'t work|wrong|glitch|crash|error|fix|debug|investigate|why (?:is|isn\'t|does|doesn\'t))\b', re.I),
     PILIntentCategory.DEBUG_ISSUE, 0.85),

    # ── BalanceAdjustment: explicit numeric tuning ────────────────────────────
    (re.compile(r'\b(?:set|change)\b.+\bto\b\s+\d', re.I),
     PILIntentCategory.BALANCE_ADJUSTMENT, 0.92),

    (re.compile(r'\b(?:double|triple|halve|increase|decrease|reduce|boost|nerf)\b.+\b(?:by|to)\b', re.I),
     PILIntentCategory.BALANCE_ADJUSTMENT, 0.88),

    (re.compile(r'\b(?:faster|slower|stronger|weaker|higher|lower)\b', re.I),
     PILIntentCategory.BALANCE_ADJUSTMENT, 0.72),

    (re.compile(r'\b(?:more|less)\b.{1,30}\b(?:health|speed|damage|armor|power|range|detection|aggression)\b', re.I),
     PILIntentCategory.BALANCE_ADJUSTMENT, 0.72),

    # ── RemoveFeature: explicit removal ───────────────────────────────────────
    (re.compile(r'\b(?:remove|delete|get rid of|destroy|eliminate|disable|turn off)\b.+\b(?:actor|enemy|player|npc|system|rule|mechanic|feature|component)\b', re.I),
     PILIntentCategory.REMOVE_FEATURE, 0.90),

    # ── CreateFeature: explicit creation ──────────────────────────────────────
    (re.compile(r'\b(?:add|create|make|build|introduce|spawn)\b.+\b(?:new|a|an)\b.+\b(?:actor|enemy|player|npc|system|rule|mechanic|feature|component|ability)\b', re.I),
     PILIntentCategory.CREATE_FEATURE, 0.88),

    (re.compile(r'\b(?:add|create|build)\b.+\b(?:actor|enemy|boss|npc|system|mechanic)\b', re.I),
     PILIntentCategory.CREATE_FEATURE, 0.82),

    # ── StructuralChange: architecture-level language ─────────────────────────
    (re.compile(r'\b(?:restructure|refactor|redesign|rearchitect|overhaul|split|merge|reorganize)\b', re.I),
     PILIntentCategory.STRUCTURAL_CHANGE, 0.86),

    (re.compile(r'\b(?:new mode|add mode|create mode|add (?:a )?(?:new )?game mode|add (?:a )?level)\b', re.I),
     PILIntentCategory.STRUCTURAL_CHANGE, 0.84),

    # ── WorldDesign: high-level design intent — must come BEFORE ModifyFeature ─
    (re.compile(r'\b(?:feel like|feel more|feel (?:like )?(?:a|an)|make it (?:a|an)|make the game|should feel|vibe|atmosphere|tone|genre|style)\b', re.I),
     PILIntentCategory.WORLD_DESIGN, 0.82),

    (re.compile(r'\b(?:like (?:a|an) (?:horror|shooter|platformer|rpg|strategy|puzzle|racing|survival|roguelike|adventure))\b', re.I),
     PILIntentCategory.WORLD_DESIGN, 0.87),

    # ── BalanceAdjustment: standalone scale words (no by/to required) ─────────
    (re.compile(r'\b(?:halve|double|triple)\b', re.I),
     PILIntentCategory.BALANCE_ADJUSTMENT, 0.82),
    (re.compile(r'\b(?:modify|change|update|tweak|adjust|tune|edit|alter|revise)\b', re.I),
     PILIntentCategory.MODIFY_FEATURE, 0.75),

    (re.compile(r'\b(?:make (?:it|the|them|him|her))\b', re.I),
     PILIntentCategory.MODIFY_FEATURE, 0.68),
]


# ── Keyword Signals ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _Signal:
    keyword: str
    category: str
    score: float

_KEYWORD_SIGNALS: list[_Signal] = [
    # CreateFeature
    _Signal("add",         PILIntentCategory.CREATE_FEATURE,     0.30),
    _Signal("new",         PILIntentCategory.CREATE_FEATURE,     0.35),
    _Signal("create",      PILIntentCategory.CREATE_FEATURE,     0.40),
    _Signal("introduce",   PILIntentCategory.CREATE_FEATURE,     0.40),
    _Signal("spawn",       PILIntentCategory.CREATE_FEATURE,     0.35),
    _Signal("boss",        PILIntentCategory.CREATE_FEATURE,     0.30),
    _Signal("npc",         PILIntentCategory.CREATE_FEATURE,     0.30),

    # ModifyFeature
    _Signal("modify",      PILIntentCategory.MODIFY_FEATURE,     0.40),
    _Signal("change",      PILIntentCategory.MODIFY_FEATURE,     0.30),
    _Signal("update",      PILIntentCategory.MODIFY_FEATURE,     0.30),
    _Signal("adjust",      PILIntentCategory.MODIFY_FEATURE,     0.35),
    _Signal("tweak",       PILIntentCategory.MODIFY_FEATURE,     0.40),
    _Signal("tune",        PILIntentCategory.MODIFY_FEATURE,     0.35),

    # RemoveFeature
    _Signal("remove",      PILIntentCategory.REMOVE_FEATURE,     0.40),
    _Signal("delete",      PILIntentCategory.REMOVE_FEATURE,     0.45),
    _Signal("get rid",     PILIntentCategory.REMOVE_FEATURE,     0.45),
    _Signal("disable",     PILIntentCategory.REMOVE_FEATURE,     0.35),
    _Signal("turn off",    PILIntentCategory.REMOVE_FEATURE,     0.40),

    # QueryExplain
    _Signal("what",        PILIntentCategory.QUERY_EXPLAIN,      0.35),
    _Signal("how",         PILIntentCategory.QUERY_EXPLAIN,      0.35),
    _Signal("why",         PILIntentCategory.QUERY_EXPLAIN,      0.40),
    _Signal("explain",     PILIntentCategory.QUERY_EXPLAIN,      0.50),
    _Signal("show",        PILIntentCategory.QUERY_EXPLAIN,      0.30),
    _Signal("list",        PILIntentCategory.QUERY_EXPLAIN,      0.35),
    _Signal("describe",    PILIntentCategory.QUERY_EXPLAIN,      0.45),

    # DebugIssue
    _Signal("bug",         PILIntentCategory.DEBUG_ISSUE,        0.55),
    _Signal("broken",      PILIntentCategory.DEBUG_ISSUE,        0.55),
    _Signal("fix",         PILIntentCategory.DEBUG_ISSUE,        0.40),
    _Signal("error",       PILIntentCategory.DEBUG_ISSUE,        0.45),
    _Signal("crash",       PILIntentCategory.DEBUG_ISSUE,        0.50),
    _Signal("glitch",      PILIntentCategory.DEBUG_ISSUE,        0.50),
    _Signal("wrong",       PILIntentCategory.DEBUG_ISSUE,        0.35),
    _Signal("debug",       PILIntentCategory.DEBUG_ISSUE,        0.55),

    # BalanceAdjustment
    _Signal("faster",      PILIntentCategory.BALANCE_ADJUSTMENT, 0.45),
    _Signal("slower",      PILIntentCategory.BALANCE_ADJUSTMENT, 0.45),
    _Signal("stronger",    PILIntentCategory.BALANCE_ADJUSTMENT, 0.40),
    _Signal("weaker",      PILIntentCategory.BALANCE_ADJUSTMENT, 0.40),
    _Signal("health",      PILIntentCategory.BALANCE_ADJUSTMENT, 0.25),
    _Signal("damage",      PILIntentCategory.BALANCE_ADJUSTMENT, 0.25),
    _Signal("speed",       PILIntentCategory.BALANCE_ADJUSTMENT, 0.30),
    _Signal("balance",     PILIntentCategory.BALANCE_ADJUSTMENT, 0.45),
    _Signal("nerf",        PILIntentCategory.BALANCE_ADJUSTMENT, 0.50),
    _Signal("buff",        PILIntentCategory.BALANCE_ADJUSTMENT, 0.50),
    _Signal("overpowered", PILIntentCategory.BALANCE_ADJUSTMENT, 0.50),
    _Signal("set",         PILIntentCategory.BALANCE_ADJUSTMENT, 0.20),
    _Signal("double",      PILIntentCategory.BALANCE_ADJUSTMENT, 0.40),
    _Signal("halve",       PILIntentCategory.BALANCE_ADJUSTMENT, 0.40),
    _Signal("triple",      PILIntentCategory.BALANCE_ADJUSTMENT, 0.40),

    # StructuralChange
    _Signal("mode",        PILIntentCategory.STRUCTURAL_CHANGE,  0.30),
    _Signal("system",      PILIntentCategory.STRUCTURAL_CHANGE,  0.30),
    _Signal("architecture", PILIntentCategory.STRUCTURAL_CHANGE, 0.45),
    _Signal("restructure", PILIntentCategory.STRUCTURAL_CHANGE,  0.50),
    _Signal("overhaul",    PILIntentCategory.STRUCTURAL_CHANGE,  0.50),

    # WorldDesign
    _Signal("feel",        PILIntentCategory.WORLD_DESIGN,       0.35),
    _Signal("vibe",        PILIntentCategory.WORLD_DESIGN,       0.45),
    _Signal("atmosphere",  PILIntentCategory.WORLD_DESIGN,       0.45),
    _Signal("genre",       PILIntentCategory.WORLD_DESIGN,       0.45),
    _Signal("horror",      PILIntentCategory.WORLD_DESIGN,       0.40),
    _Signal("shooter",     PILIntentCategory.WORLD_DESIGN,       0.40),
    _Signal("platformer",  PILIntentCategory.WORLD_DESIGN,       0.40),
    _Signal("rpg",         PILIntentCategory.WORLD_DESIGN,       0.40),
    _Signal("survival",    PILIntentCategory.WORLD_DESIGN,       0.35),
]


# ── Classification Result ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class PILClassificationResult:
    """
    Intermediate result from PILIntentClassifier.classify_normalized().

    Attributes
    ----------
    category : str
        One of PILIntentCategory constants.
    confidence : float
        Classification confidence [0.0–1.0].
    requires_clarification : bool
        True when confidence is below CONFIDENCE_MEDIUM.
    matched_layer : str
        Which layer produced this result: "structural" | "keyword" | "fallback".
    """
    category:               str
    confidence:             float
    requires_clarification: bool
    matched_layer:          str


# ── PIL Intent Classifier ─────────────────────────────────────────────────────

class PILIntentClassifier:
    """
    Classifies normalized designer prompts into PIL intent categories.

    Stateless, deterministic, LLM-free, sub-millisecond.

    Usage
    -----
        classifier = PILIntentClassifier()
        result = classifier.classify_normalized("make the zombie faster")
        # PILClassificationResult(category='BalanceAdjustment', conf=0.72, ...)
    """

    def classify_normalized(self, normalized_text: str) -> PILClassificationResult:
        """
        Classifies a pre-normalized prompt text.

        Parameters
        ----------
        normalized_text : str
            Output of PromptNormalizer.normalize().text — already trimmed
            and quote-normalized.

        Returns
        -------
        PILClassificationResult
            Always returns a result. Falls back to UNKNOWN with
            requires_clarification=True on total failure.
        """
        if not normalized_text or not normalized_text.strip():
            return PILClassificationResult(
                category               = PILIntentCategory.UNKNOWN,
                confidence             = 0.0,
                requires_clarification = True,
                matched_layer          = "fallback",
            )

        text = normalized_text.strip()

        # ── Layer 1: Structural pattern matching ──────────────────────────────
        pattern_result = self._match_structural(text)
        if pattern_result:
            cat, conf = pattern_result
            return PILClassificationResult(
                category               = cat,
                confidence             = conf,
                requires_clarification = conf < CONFIDENCE_MEDIUM,
                matched_layer          = "structural",
            )

        # ── Layer 2: Keyword scoring ──────────────────────────────────────────
        scored_cat, score = self._keyword_score(text)
        if scored_cat and score >= CONFIDENCE_MIN:
            return PILClassificationResult(
                category               = scored_cat,
                confidence             = score,
                requires_clarification = score < CONFIDENCE_MEDIUM,
                matched_layer          = "keyword",
            )

        # ── Layer 3: Fallback ─────────────────────────────────────────────────
        return PILClassificationResult(
            category               = PILIntentCategory.UNKNOWN,
            confidence             = 0.0,
            requires_clarification = True,
            matched_layer          = "fallback",
        )

    def batch_classify(self, texts: list[str]) -> list[PILClassificationResult]:
        """Classifies a list of normalized texts. Each is independent."""
        return [self.classify_normalized(t) for t in texts]

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _match_structural(text: str) -> tuple[str, float] | None:
        """Returns (category, confidence) for the first matching structural pattern."""
        for pattern, category, conf in _STRUCTURAL_PATTERNS:
            if pattern.search(text):
                return category, conf
        return None

    @staticmethod
    def _keyword_score(text: str) -> tuple[str | None, float]:
        """
        Accumulates keyword scores per category.
        Returns (best_category, capped_score) or (None, 0.0).
        """
        text_lower = text.lower()
        scores: dict[str, float] = {}

        for sig in _KEYWORD_SIGNALS:
            if sig.keyword in text_lower:
                scores[sig.category] = scores.get(sig.category, 0.0) + sig.score

        if not scores:
            return None, 0.0

        best = max(scores, key=lambda k: scores[k])
        return best, min(scores[best], 0.92)   # cap to avoid overconfidence