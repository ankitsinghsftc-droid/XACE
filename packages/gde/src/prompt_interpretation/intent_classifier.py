"""
intent_classifier.py — IntentClassifier
=========================================
Classifies a designer prompt into a GDEIntentType.

This is the GDE's lightweight, LLM-free intent classifier. It runs
synchronously before the PIL pipeline and serves two purposes:

    1. Fast routing: simple, high-confidence prompts (e.g. "set health to 80")
       are classified here and bypass the full 5-pass LLM pipeline.
    2. Context priming: even when the full PIL runs, the GDE intent provides
       initial scope hints that reduce the LLM context window size.

## Why No LLM Here?
The GDE intent classifier runs on every keystroke in the builder's prompt
input — it must be sub-millisecond. The PIL pipeline is invoked only when
the user submits a complete prompt. Keeping this classifier fast and
deterministic means the builder can show real-time intent previews.

## Classification Strategy
Three-layer pipeline (same structure as USMCClassifier for consistency):
    1. Structural pattern matching — detects "set X to Y", "add X", "remove X"
    2. Action-keyword scoring — weighted keyword signals per intent type
    3. Fallback — UNKNOWN with requires_clarification=True

The output is always deterministic: same input string always produces
the same IntentObject regardless of call order or history.
(History is the HistoryManager's job, not this classifier's.)

## Scope Extraction
The classifier performs lightweight scope extraction alongside classification:
    - Extracts mode hints ("in survival mode")
    - Extracts actor hints ("player", "zombie", "enemy")
    - Extracts component hints ("health", "speed", "damage")
This is intentionally shallow — the SlotExtractor does deep extraction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .intent_object import IntentObject, GDEIntentType


# ── Classification Signal ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class ClassificationSignal:
    """One keyword → intent mapping with score weight."""
    keyword:     str
    intent_type: str
    score:       float
    is_regex:    bool = False


# ── Structural Pattern Registry ───────────────────────────────────────────────
# Ordered — first match wins for structural patterns

_STRUCTURAL_PATTERNS: list[tuple[re.Pattern, str, float]] = [
    # SET patterns: "set X to Y", "change X to Y"
    (re.compile(r'\b(?:set|change|make)\b.+\bto\b', re.I),
     GDEIntentType.SET_VALUE, 0.9),

    # SCALE patterns: "double X", "halve X", "increase X by N%"
    (re.compile(r'\b(?:double|triple|halve|increase.+by|decrease.+by|scale)\b', re.I),
     GDEIntentType.SCALE_VALUE, 0.85),

    # CREATE ACTOR patterns
    (re.compile(r'\b(?:add|create|spawn|introduce)\b.+\b(?:actor|enemy|player|npc|character|entity|boss)\b', re.I),
     GDEIntentType.CREATE_ACTOR, 0.88),

    # REMOVE ACTOR patterns
    (re.compile(r'\b(?:remove|delete|destroy)\b.+\b(?:actor|enemy|player|npc|character|entity)\b', re.I),
     GDEIntentType.REMOVE_ACTOR, 0.88),

    # DEFINE RULE patterns
    (re.compile(r'\b(?:when|if|whenever)\b.+\b(?:then|should|must|will)\b', re.I),
     GDEIntentType.DEFINE_RULE, 0.82),
    (re.compile(r'\b(?:rule|condition|effect|trigger|on (?:death|damage|hit))\b', re.I),
     GDEIntentType.DEFINE_RULE, 0.75),

    # ADD COMPONENT patterns
    (re.compile(r'\b(?:add|give|attach)\b.+\b(?:component|health|armor|speed|ai|ability)\b', re.I),
     GDEIntentType.ADD_COMPONENT, 0.80),

    # CREATE SYSTEM patterns
    (re.compile(r'\b(?:add|create)\b.+\b(?:system|mechanic|feature)\b', re.I),
     GDEIntentType.CREATE_SYSTEM, 0.78),

    # QUERY patterns
    (re.compile(r'^(?:what|how|why|show|explain|tell me|describe|list)\b', re.I),
     GDEIntentType.QUERY_EXPLAIN, 0.80),
    (re.compile(r'\bwhat is\b.+\b(?:value|health|speed|damage)\b', re.I),
     GDEIntentType.QUERY_VALUE, 0.85),
]

# ── Keyword Signals ───────────────────────────────────────────────────────────

_KEYWORD_SIGNALS: list[ClassificationSignal] = [
    # ModifyValue
    ClassificationSignal("adjust",      GDEIntentType.MODIFY_VALUE,     0.45),
    ClassificationSignal("tweak",       GDEIntentType.MODIFY_VALUE,     0.5),
    ClassificationSignal("tune",        GDEIntentType.MODIFY_VALUE,     0.45),
    ClassificationSignal("update",      GDEIntentType.MODIFY_VALUE,     0.4),
    ClassificationSignal("modify",      GDEIntentType.MODIFY_VALUE,     0.5),

    # SetValue
    ClassificationSignal("set",         GDEIntentType.SET_VALUE,        0.4),
    ClassificationSignal("to",          GDEIntentType.SET_VALUE,        0.2),
    ClassificationSignal("equal",       GDEIntentType.SET_VALUE,        0.4),
    ClassificationSignal("value",       GDEIntentType.SET_VALUE,        0.3),

    # ScaleValue
    ClassificationSignal("faster",      GDEIntentType.SCALE_VALUE,      0.5),
    ClassificationSignal("slower",      GDEIntentType.SCALE_VALUE,      0.5),
    ClassificationSignal("stronger",    GDEIntentType.SCALE_VALUE,      0.45),
    ClassificationSignal("weaker",      GDEIntentType.SCALE_VALUE,      0.45),
    ClassificationSignal("more",        GDEIntentType.SCALE_VALUE,      0.25),
    ClassificationSignal("less",        GDEIntentType.SCALE_VALUE,      0.25),

    # CreateActor
    ClassificationSignal("add",         GDEIntentType.CREATE_ACTOR,     0.3),
    ClassificationSignal("new",         GDEIntentType.CREATE_ACTOR,     0.35),
    ClassificationSignal("zombie",      GDEIntentType.CREATE_ACTOR,     0.4),
    ClassificationSignal("enemy",       GDEIntentType.CREATE_ACTOR,     0.4),
    ClassificationSignal("boss",        GDEIntentType.CREATE_ACTOR,     0.45),
    ClassificationSignal("npc",         GDEIntentType.CREATE_ACTOR,     0.45),
    ClassificationSignal("character",   GDEIntentType.CREATE_ACTOR,     0.35),

    # RemoveActor
    ClassificationSignal("remove",      GDEIntentType.REMOVE_ACTOR,     0.4),
    ClassificationSignal("delete",      GDEIntentType.REMOVE_ACTOR,     0.5),
    ClassificationSignal("get rid",     GDEIntentType.REMOVE_ACTOR,     0.5),

    # DefineRule
    ClassificationSignal("when",        GDEIntentType.DEFINE_RULE,      0.4),
    ClassificationSignal("if",          GDEIntentType.DEFINE_RULE,      0.35),
    ClassificationSignal("whenever",    GDEIntentType.DEFINE_RULE,      0.45),
    ClassificationSignal("dies",        GDEIntentType.DEFINE_RULE,      0.4),
    ClassificationSignal("killed",      GDEIntentType.DEFINE_RULE,      0.4),
    ClassificationSignal("triggers",    GDEIntentType.DEFINE_RULE,      0.45),
    ClassificationSignal("fire",        GDEIntentType.DEFINE_RULE,      0.3),

    # Query
    ClassificationSignal("what",        GDEIntentType.QUERY_EXPLAIN,    0.4),
    ClassificationSignal("how",         GDEIntentType.QUERY_EXPLAIN,    0.4),
    ClassificationSignal("explain",     GDEIntentType.QUERY_EXPLAIN,    0.55),
    ClassificationSignal("show",        GDEIntentType.QUERY_EXPLAIN,    0.35),
    ClassificationSignal("list",        GDEIntentType.QUERY_EXPLAIN,    0.35),
]

# ── Scope Extraction Patterns ─────────────────────────────────────────────────

_ACTOR_NAME_PATTERNS = re.compile(
    r'\b(player|zombie|enemy|boss|npc|guard|merchant|archer|knight|ghost|dragon)\b', re.I
)
_COMPONENT_PATTERNS = re.compile(
    r'\b(health|speed|damage|armor|shield|detection|vision|range|movement|velocity|ai)\b', re.I
)
_MODE_PATTERNS = re.compile(
    r'\bin (?:the )?(\w+) mode\b', re.I
)
_NUMERIC_VALUE_PATTERN = re.compile(r'\b(\d+(?:\.\d+)?)\b')


# ── Intent Classifier ─────────────────────────────────────────────────────────

class IntentClassifier:
    """
    Classifies designer prompts into GDEIntentType.

    Deterministic — same input always produces the same output.
    LLM-free — uses only pattern matching and keyword scoring.
    Sub-millisecond — safe to call on every keystroke.

    Usage
    -----
        classifier = IntentClassifier()
        intent     = classifier.classify("make the zombie faster")
        # IntentObject(intent_type='ScaleValue', conf=0.72)
    """

    def classify(
        self,
        prompt:     str,
        session_id: str | None = None,
    ) -> IntentObject:
        """
        Classifies a prompt and returns a populated IntentObject.

        Always returns a result — never raises. Unknown/ambiguous prompts
        return IntentObject.unknown() with requires_clarification=True.
        """
        if not prompt or not prompt.strip():
            return IntentObject.unknown("", session_id)

        text = prompt.strip()

        # ── Layer 1: Structural pattern matching ──────────────────────────────
        pattern_result = self._match_structural(text)
        if pattern_result:
            intent_type, confidence = pattern_result
            scope  = self._extract_scope(text)
            intent = IntentObject(
                intent_type=intent_type,
                scope=scope,
                confidence=confidence,
                raw_prompt=text,
                session_id=session_id,
            )
            self._enrich_parameters(intent, text)
            return intent

        # ── Layer 2: Keyword scoring ──────────────────────────────────────────
        scored_type, score = self._keyword_score(text)
        if scored_type and score >= 0.4:
            scope  = self._extract_scope(text)
            intent = IntentObject(
                intent_type=scored_type,
                scope=scope,
                confidence=score,
                requires_clarification=score < 0.65,
                raw_prompt=text,
                session_id=session_id,
            )
            self._enrich_parameters(intent, text)
            return intent

        # ── Layer 3: Fallback ─────────────────────────────────────────────────
        intent = IntentObject.unknown(text, session_id)
        intent.clarification_questions.append(
            "I'm not sure what you'd like to change. "
            "Could you describe what you want to add, modify, or remove?"
        )
        return intent

    def batch_classify(
        self, prompts: list[str], session_id: str | None = None
    ) -> list[IntentObject]:
        """Classifies a list of prompts. Each gets an independent result."""
        return [self.classify(p, session_id) for p in prompts]

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _match_structural(text: str) -> tuple[str, float] | None:
        """Returns (intent_type, confidence) for the first matching pattern."""
        for pattern, intent_type, conf in _STRUCTURAL_PATTERNS:
            if pattern.search(text):
                return intent_type, conf
        return None

    @staticmethod
    def _keyword_score(text: str) -> tuple[str | None, float]:
        """
        Accumulates keyword scores per intent type.
        Returns (best_type, score) or (None, 0.0).
        """
        text_lower = text.lower()
        scores: dict[str, float] = {}

        for signal in _KEYWORD_SIGNALS:
            if signal.keyword in text_lower:
                scores[signal.intent_type] = (
                    scores.get(signal.intent_type, 0.0) + signal.score
                )

        if not scores:
            return None, 0.0

        best = max(scores, key=lambda k: scores[k])
        return best, min(scores[best], 0.92)

    @staticmethod
    def _extract_scope(text: str) -> dict[str, Any]:
        """
        Shallow scope extraction — identifies actor/component/mode hints.
        Returns a partial scope dict; SlotExtractor will complete it.
        """
        scope: dict[str, Any] = {}

        actor_match = _ACTOR_NAME_PATTERNS.search(text)
        if actor_match:
            scope["actor_hint"] = actor_match.group(1).lower()

        comp_matches = _COMPONENT_PATTERNS.findall(text)
        if comp_matches:
            scope["component_hints"] = [c.lower() for c in comp_matches]

        mode_match = _MODE_PATTERNS.search(text)
        if mode_match:
            scope["mode_hint"] = mode_match.group(1).lower()

        return scope

    @staticmethod
    def _enrich_parameters(intent: IntentObject, text: str) -> None:
        """
        Extracts numeric values and adds them as parameters.
        Shallow extraction — SlotExtractor does the full pass.
        """
        numeric_matches = _NUMERIC_VALUE_PATTERN.findall(text)
        for i, match in enumerate(numeric_matches[:3]):  # cap at 3 values
            try:
                val = float(match) if "." in match else int(match)
                intent.add_parameter(
                    name=f"value_{i}",
                    value=val,
                    type_hint="float" if isinstance(val, float) else "int",
                    confidence=0.7,
                )
            except ValueError:
                pass