"""
question_generator.py — QuestionGenerator
==========================================
Generates structured micro-form clarification questions from ambiguity
signals, validated against the current CGS.

## What Makes a Good Clarification Question

    Bad (chat-style):
        "I'm not sure what you mean. Could you clarify which actor you
        want to modify and what value you'd like to set it to?"

    Good (micro-form):
        CHOICE: "Which actor do you want to make faster?"
        Options: ["Zombie", "Player"]  ← real IDs from CGS

    Good micro-forms are:
        - Single-purpose (one question, one answer)
        - Schema-aware (options come from real CGS entities)
        - Binary or small-N choice when possible
        - Typed (CHOICE, CONFIRM, FILL, SCOPE_SELECT — not free chat)

## Question Generation Triggers

    1. Actor ambiguity
       Prompt mentions "the enemy" or "the character" without a specific ID.
       Multiple actors exist in the CGS → SCOPE_SELECT from actor IDs.

    2. Value ambiguity
       Prompt says "make it faster" without a numeric value.
       Intent type is BalanceAdjustment → FILL with numeric hint.

    3. Destructive confirmation
       Prompt intends to remove an actor/system/rule.
       → CONFIRM before committing.

    4. Mode ambiguity
       Prompt doesn't specify which mode when multiple modes exist.
       → SCOPE_SELECT from mode IDs.

    5. Field ambiguity
       Multiple fields on a component could match the intent.
       "Make the zombie stronger" → COMP_HEALTH_V1 or COMP_AI_V1.aggression?
       → CHOICE between field interpretations.

    6. Retry failure context
       PILRetryPolicy reported exhaustion on a specific pass.
       → FILL question targeting the exact issue reported.

## CGS-Aware Option Generation

    QuestionGenerator reads the current CGS to populate options:
        - Actor IDs → from modes[*].actors[*].id
        - Mode IDs  → from modes[*].id
        - System IDs → from modes[*].systems[*].id + global_systems[*].id
        - Rule IDs   → from modes[*].rules[*].id
        - Field names → from component defaults keys

    Options are always real CGS entities — never invented labels.
    Display labels are the ID with spaces replacing underscores for readability.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "intent_intake"))

from intent_envelope import IntentEnvelope, PILIntentCategory
from clarification_session import (
    ClarificationQuestion, QuestionType, MAX_QUESTIONS_PER_SESSION
)


# ── Ambiguity Signal ──────────────────────────────────────────────────────────

@dataclass
class AmbiguitySignal:
    """
    Describes one ambiguity detected in the intent.

    Attributes
    ----------
    signal_type : str
        One of: "actor_ambiguous" | "value_missing" | "destructive_confirm" |
                "mode_ambiguous" | "field_ambiguous" | "retry_failure"
    description : str
        Human-readable description of the ambiguity.
    context     : dict
        Signal-specific context:
            actor_ambiguous:    {"candidate_actor_ids": [...]}
            value_missing:      {"field_name": str, "unit_hint": str}
            destructive_confirm:{"target": str, "op": str}
            mode_ambiguous:     {"candidate_mode_ids": [...]}
            field_ambiguous:    {"actor_id": str, "candidates": [...]}
            retry_failure:      {"pass_label": str, "reasons": [...]}
    """
    signal_type: str
    description: str
    context:     dict


# ── Question Generator ────────────────────────────────────────────────────────

class QuestionGenerator:
    """
    Generates ClarificationQuestion objects from ambiguity signals.

    Stateless — one shared instance.

    Usage
    -----
        generator = QuestionGenerator()
        questions = generator.generate(
            envelope = intent_envelope,
            signals  = [AmbiguitySignal(...)],
            cgs      = current_cgs,
        )
    """

    def generate(
        self,
        envelope: IntentEnvelope,
        signals:  list[AmbiguitySignal],
        cgs:      dict[str, Any],
    ) -> list[ClarificationQuestion]:
        """
        Generates a list of ClarificationQuestions from ambiguity signals.

        Deduplicated and capped at MAX_QUESTIONS_PER_SESSION.
        Questions are ordered by priority: destructive confirms first,
        then scope questions, then value questions.

        Parameters
        ----------
        envelope : IntentEnvelope
            Current intent context.
        signals  : list[AmbiguitySignal]
            Detected ambiguities.
        cgs      : dict
            Current CGS for schema-aware option generation.

        Returns
        -------
        list[ClarificationQuestion]
        """
        questions: list[ClarificationQuestion] = []
        seen_types: set[str] = set()

        # Priority ordering: destructive > scope > value > field > retry
        priority = {
            "destructive_confirm": 0,
            "mode_ambiguous":      1,
            "actor_ambiguous":     2,
            "field_ambiguous":     3,
            "value_missing":       4,
            "retry_failure":       5,
        }
        sorted_signals = sorted(
            signals,
            key=lambda s: priority.get(s.signal_type, 99)
        )

        for signal in sorted_signals:
            if signal.signal_type in seen_types:
                continue   # one question per signal type
            seen_types.add(signal.signal_type)

            q = self._generate_one(signal, envelope, cgs)
            if q:
                questions.append(q)
            if len(questions) >= MAX_QUESTIONS_PER_SESSION:
                break

        return questions

    def generate_from_retry_failure(
        self,
        pass_label: str,
        reasons:    list[str],
        envelope:   IntentEnvelope,
        cgs:        dict[str, Any],
    ) -> list[ClarificationQuestion]:
        """
        Generates questions specifically for a PILRetryPolicy exhaustion.
        Called by llm_orchestrator when needs_clarification=True.
        """
        signal = AmbiguitySignal(
            signal_type = "retry_failure",
            description = f"Pipeline failed on {pass_label}",
            context     = {"pass_label": pass_label, "reasons": reasons},
        )
        return self.generate(envelope, [signal], cgs)

    def detect_signals(
        self,
        envelope: IntentEnvelope,
        cgs:      dict[str, Any],
    ) -> list[AmbiguitySignal]:
        """
        Automatically detects ambiguity signals from an IntentEnvelope + CGS.
        Called when the pipeline wants clarification without a specific reason.
        """
        signals: list[AmbiguitySignal] = []
        prompt_lower = envelope.normalized_text.lower()

        actor_ids = self._get_actor_ids(cgs)
        mode_ids  = self._get_mode_ids(cgs)

        # Signal: actor ambiguous — multiple actors, none named in prompt
        if len(actor_ids) > 1:
            named = [aid for aid in actor_ids if aid.lower() in prompt_lower
                     or aid.replace("actor_", "").lower() in prompt_lower]
            if not named:
                signals.append(AmbiguitySignal(
                    signal_type = "actor_ambiguous",
                    description = "Prompt doesn't specify which actor to modify.",
                    context     = {"candidate_actor_ids": actor_ids},
                ))

        # Signal: value missing — BalanceAdjustment without a number
        if envelope.intent_category == PILIntentCategory.BALANCE_ADJUSTMENT:
            has_number = any(c.isdigit() for c in envelope.normalized_text)
            if not has_number:
                signals.append(AmbiguitySignal(
                    signal_type = "value_missing",
                    description = "Balance adjustment without a numeric value.",
                    context     = {"field_name": "value", "unit_hint": "a number"},
                ))

        # Signal: mode ambiguous — multiple modes, none named in prompt
        if len(mode_ids) > 1:
            named_mode = any(mid.lower() in prompt_lower for mid in mode_ids)
            if not named_mode:
                signals.append(AmbiguitySignal(
                    signal_type = "mode_ambiguous",
                    description = "Prompt doesn't specify which game mode.",
                    context     = {"candidate_mode_ids": mode_ids},
                ))

        # Signal: unknown intent — UNKNOWN category
        if envelope.intent_category == PILIntentCategory.UNKNOWN:
            signals.append(AmbiguitySignal(
                signal_type = "retry_failure",
                description = "Intent could not be classified.",
                context     = {
                    "pass_label": "intake",
                    "reasons": ["Intent category is UNKNOWN — cannot proceed."],
                },
            ))

        return signals

    # ── Signal → Question ─────────────────────────────────────────────────────

    def _generate_one(
        self,
        signal:   AmbiguitySignal,
        envelope: IntentEnvelope,
        cgs:      dict[str, Any],
    ) -> ClarificationQuestion | None:
        stype = signal.signal_type

        if stype == "actor_ambiguous":
            return self._actor_question(signal, cgs)
        if stype == "value_missing":
            return self._value_question(signal, envelope)
        if stype == "destructive_confirm":
            return self._destructive_confirm_question(signal)
        if stype == "mode_ambiguous":
            return self._mode_question(signal, cgs)
        if stype == "field_ambiguous":
            return self._field_question(signal)
        if stype == "retry_failure":
            return self._retry_failure_question(signal, envelope)

        return None

    def _actor_question(
        self,
        signal: AmbiguitySignal,
        cgs:    dict[str, Any],
    ) -> ClarificationQuestion:
        actor_ids    = signal.context.get("candidate_actor_ids", self._get_actor_ids(cgs))
        display_opts = tuple(
            aid.replace("actor_", "").replace("_", " ").title()
            if aid.startswith("actor_") else aid
            for aid in actor_ids
        )
        # Use display labels as options but keep ID mapping for resolution
        # Options are raw actor_ids — display labels shown by UI layer
        return ClarificationQuestion(
            question_id   = _new_qid("actor"),
            question_type = QuestionType.SCOPE_SELECT,
            prompt        = "Which character do you want to modify?",
            options       = tuple(actor_ids),
            hint          = "",
            parameter_key = "target_actor_id",
            required      = True,
        )

    def _value_question(
        self,
        signal:   AmbiguitySignal,
        envelope: IntentEnvelope,
    ) -> ClarificationQuestion:
        field_name = signal.context.get("field_name", "value")
        unit_hint  = signal.context.get("unit_hint", "a number")
        return ClarificationQuestion(
            question_id   = _new_qid("value"),
            question_type = QuestionType.FILL,
            prompt        = (
                f"What value should '{field_name}' be set to? "
                f"(Enter {unit_hint})"
            ),
            options       = (),
            hint          = unit_hint,
            parameter_key = "numeric_value",
            required      = True,
        )

    @staticmethod
    def _destructive_confirm_question(
        signal: AmbiguitySignal,
    ) -> ClarificationQuestion:
        target  = signal.context.get("target", "this element")
        op      = signal.context.get("op", "remove").lower()
        return ClarificationQuestion(
            question_id   = _new_qid("confirm"),
            question_type = QuestionType.CONFIRM,
            prompt        = f"Are you sure you want to {op} {target!r}? This cannot be undone.",
            options       = ("yes", "no"),
            hint          = "",
            parameter_key = "confirmed",
            required      = True,
        )

    def _mode_question(
        self,
        signal: AmbiguitySignal,
        cgs:    dict[str, Any],
    ) -> ClarificationQuestion:
        mode_ids = signal.context.get("candidate_mode_ids", self._get_mode_ids(cgs))
        return ClarificationQuestion(
            question_id   = _new_qid("mode"),
            question_type = QuestionType.SCOPE_SELECT,
            prompt        = "Which game mode does this change apply to?",
            options       = tuple(mode_ids),
            hint          = "",
            parameter_key = "target_mode_id",
            required      = True,
        )

    @staticmethod
    def _field_question(signal: AmbiguitySignal) -> ClarificationQuestion:
        candidates = signal.context.get("candidates", [])
        actor_id   = signal.context.get("actor_id", "the actor")
        return ClarificationQuestion(
            question_id   = _new_qid("field"),
            question_type = QuestionType.CHOICE,
            prompt        = (
                f"Which property of {actor_id!r} do you want to change?"
            ),
            options       = tuple(candidates),
            hint          = "",
            parameter_key = "target_field",
            required      = True,
        )

    @staticmethod
    def _retry_failure_question(
        signal:   AmbiguitySignal,
        envelope: IntentEnvelope,
    ) -> ClarificationQuestion:
        pass_label = signal.context.get("pass_label", "the pipeline")
        reasons    = signal.context.get("reasons", [])
        reason_str = reasons[0] if reasons else "The request could not be processed."

        # For intake failures, ask for a rephrased prompt
        if pass_label == "intake" or "UNKNOWN" in reason_str:
            return ClarificationQuestion(
                question_id   = _new_qid("rephrase"),
                question_type = QuestionType.FILL,
                prompt        = (
                    "I couldn't understand that request. "
                    "Could you describe what you want to change? "
                    "(e.g. 'set zombie health to 50', 'add a boss enemy')"
                ),
                options       = (),
                hint          = "describe the change you want to make",
                parameter_key = "rephrased_prompt",
                required      = True,
            )

        # For value/path failures, ask for the specific missing detail
        if "value" in reason_str.lower() or "path" in reason_str.lower():
            return ClarificationQuestion(
                question_id   = _new_qid("clarify_value"),
                question_type = QuestionType.FILL,
                prompt        = (
                    f"I had trouble generating the mutation. "
                    f"Could you be more specific? "
                    f"(Problem: {reason_str[:80]})"
                ),
                options       = (),
                hint          = "specific value or target",
                parameter_key = "clarified_detail",
                required      = True,
            )

        # Generic rephrasing fallback
        return ClarificationQuestion(
            question_id   = _new_qid("retry_rephrase"),
            question_type = QuestionType.FILL,
            prompt        = (
                "I wasn't able to complete that change. "
                "Could you rephrase it more specifically? "
                "(e.g. include the exact value, actor name, or field)"
            ),
            options       = (),
            hint          = "rephrase your request with more detail",
            parameter_key = "rephrased_prompt",
            required      = True,
        )

    # ── CGS helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _get_actor_ids(cgs: dict[str, Any]) -> list[str]:
        ids: list[str] = []
        for mode in cgs.get("modes", []):
            for actor in mode.get("actors", []):
                aid = actor.get("id", "")
                if aid and aid not in ids:
                    ids.append(aid)
        return ids

    @staticmethod
    def _get_mode_ids(cgs: dict[str, Any]) -> list[str]:
        return [m.get("id", "") for m in cgs.get("modes", []) if m.get("id")]

    @staticmethod
    def _get_system_ids(cgs: dict[str, Any]) -> list[str]:
        ids: list[str] = []
        for gs in cgs.get("global_systems", []):
            ids.append(gs.get("id", ""))
        for mode in cgs.get("modes", []):
            for s in mode.get("systems", []):
                ids.append(s.get("id", ""))
        return [i for i in ids if i]

    @staticmethod
    def _get_rule_ids(cgs: dict[str, Any]) -> list[str]:
        ids: list[str] = []
        for mode in cgs.get("modes", []):
            for r in mode.get("rules", []):
                ids.append(r.get("id", ""))
        return [i for i in ids if i]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _new_qid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:6]}"