"""
question_engine.py — QuestionEngine
=====================================
Converts a ClarificationRequest into a fully-typed, ordered list of
question objects ready for the builder UI or a text session.

## Responsibility
AmbiguityDetector produces ClarificationRequests with ClarificationQuestion
stubs. QuestionEngine converts those stubs into the full typed question
objects (ChoiceQuestion, ConfirmQuestion, FillQuestion, ScopeSelectQuestion)
with response validators and option values populated.

It also:
    - Deduplicates questions targeting the same parameter_name
    - Orders questions by priority (scope before field before value before confirm)
    - Caps the total question count at MAX_QUESTIONS_PER_SESSION
    - Formats options in plain English (no technical vocabulary)

## Session Integration
QuestionEngine is used by QuestionSessionManager to set up a session.
The session then manages the state (which question is active, answers so far).

## Mode Sensitivity
The mode profile controls question verbosity:
    FULLY_ASSISTED  — all questions, detailed hints
    COLLABORATIVE   — all questions, brief hints
    ADVANCED        — only required (is_required=True) questions
    ARCHITECT_MODE  — no questions generated at all
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..prompt_interpretation.ambiguity_detector import ClarificationRequest, ClarificationQuestion
from ..prompt_interpretation.context_loader import CGSContextSlice
from ..prompt_interpretation.intent_object import IntentObject
from .question_types import (
    BaseQuestion, ChoiceQuestion, ConfirmQuestion,
    FillQuestion, ScopeSelectQuestion,
    make_choice, make_confirm, make_fill,
)


# ── Question Priority ─────────────────────────────────────────────────────────

_AMBIGUITY_PRIORITY: dict[str, int] = {
    "A7": 0,   # UNKNOWN intent — must resolve first
    "A5": 1,   # missing required structural data
    "A1": 2,   # no actor resolved
    "A2": 3,   # multiple actors matched
    "A3": 4,   # no field resolved
    "A4": 5,   # value present but field unclear
    "A6": 6,   # low overall confidence — confirm last
    "":   7,   # untagged questions go last
}

MAX_QUESTIONS_PER_SESSION = 5


# ── Question Engine ───────────────────────────────────────────────────────────

@dataclass
class QuestionEngine:
    """
    Converts ClarificationRequests into ordered typed question objects.

    Stateless — one call to build() per clarification flow.

    Usage
    -----
        engine    = QuestionEngine()
        questions = engine.build(clarification_request, cgs_slice, intent, mode)
    """

    def build(
        self,
        request:    ClarificationRequest,
        cgs_slice:  CGSContextSlice,
        intent:     IntentObject,
        mode:       str = "COLLABORATIVE",
    ) -> list[BaseQuestion]:
        """
        Builds a typed, deduplicated, ordered question list.

        Parameters
        ----------
        request : ClarificationRequest
            The ambiguity signals to address.
        cgs_slice : CGSContextSlice
            Context used to populate option lists.
        intent : IntentObject
            The intent being clarified.
        mode : str
            One of: FULLY_ASSISTED | COLLABORATIVE | ADVANCED | ARCHITECT_MODE

        Returns
        -------
        list[BaseQuestion]
            Ordered typed question objects ready for QuestionSessionManager.
            Empty list for ARCHITECT_MODE.
        """
        if mode == "ARCHITECT_MODE":
            return []

        # Sort by priority
        sorted_stubs = sorted(
            request.questions,
            key=lambda q: _AMBIGUITY_PRIORITY.get(q.ambiguity_code, 7),
        )

        # ADVANCED mode — only required questions
        if mode == "ADVANCED":
            sorted_stubs = [
                q for q in sorted_stubs
                if q.ambiguity_code in ("A5", "A7")
            ]

        # Deduplicate by parameter_name (keep first occurrence)
        seen_params: set[str] = set()
        unique_stubs: list[ClarificationQuestion] = []
        for stub in sorted_stubs:
            if stub.parameter_name not in seen_params:
                unique_stubs.append(stub)
                seen_params.add(stub.parameter_name)

        # Convert stubs to typed questions
        typed: list[BaseQuestion] = []
        for stub in unique_stubs[:MAX_QUESTIONS_PER_SESSION]:
            q = self._convert_stub(stub, cgs_slice, intent, mode)
            if q is not None:
                typed.append(q)

        return typed

    # ── Stub → Typed Question ─────────────────────────────────────────────────

    def _convert_stub(
        self,
        stub:      ClarificationQuestion,
        cgs_slice: CGSContextSlice,
        intent:    IntentObject,
        mode:      str,
    ) -> BaseQuestion | None:
        """Converts one ClarificationQuestion stub to a typed question object."""
        hint = _hint_for_mode(mode)

        match stub.question_type:
            case "CHOICE":
                return self._make_choice(stub, cgs_slice, hint)
            case "CONFIRM":
                return make_confirm(
                    question_id=stub.question_id,
                    text=stub.text,
                    parameter_name=stub.parameter_name,
                    default=stub.default,
                    ambiguity_code=stub.ambiguity_code,
                )
            case "FILL":
                return self._make_fill(stub, hint)
            case "SCOPE_SELECT":
                return self._make_scope_select(stub, cgs_slice)
            case _:
                return make_fill(
                    question_id=stub.question_id,
                    text=stub.text,
                    parameter_name=stub.parameter_name,
                    ambiguity_code=stub.ambiguity_code,
                )

    def _make_choice(
        self,
        stub:      ClarificationQuestion,
        cgs_slice: CGSContextSlice,
        hint:      str,
    ) -> ChoiceQuestion:
        options = stub.options if stub.options else _derive_options(stub, cgs_slice)
        return make_choice(
            question_id=stub.question_id,
            text=stub.text,
            options=options,
            parameter_name=stub.parameter_name,
            default=stub.default,
            ambiguity_code=stub.ambiguity_code,
            hint_text=hint,
        )

    @staticmethod
    def _make_fill(stub: ClarificationQuestion, hint: str) -> FillQuestion:
        expected_type = _infer_fill_type(stub.parameter_name)
        placeholder   = _placeholder_for(stub.parameter_name)
        return make_fill(
            question_id=stub.question_id,
            text=stub.text,
            parameter_name=stub.parameter_name,
            expected_type=expected_type,
            placeholder=placeholder,
            ambiguity_code=stub.ambiguity_code,
            hint_text=hint,
        )

    @staticmethod
    def _make_scope_select(
        stub:      ClarificationQuestion,
        cgs_slice: CGSContextSlice,
    ) -> ScopeSelectQuestion:
        actor_ids = cgs_slice.all_actor_ids_in_mode
        return ScopeSelectQuestion.from_actor_ids(
            question_id=stub.question_id,
            text=stub.text,
            actor_ids=actor_ids,
            parameter_name=stub.parameter_name,
            ambiguity_code=stub.ambiguity_code,
        )

    # ── Standalone Generators (called from GDE orchestrator directly) ─────────

    def ask_which_actor(
        self,
        question_id: str,
        actor_ids:   list[str],
    ) -> ScopeSelectQuestion:
        """Generates a which-actor question without a ClarificationRequest."""
        return ScopeSelectQuestion.from_actor_ids(
            question_id=question_id,
            text="Which character should this change apply to?",
            actor_ids=actor_ids,
            parameter_name="target_actor_id",
            ambiguity_code="A1",
        )

    def ask_which_field(
        self,
        question_id: str,
        field_options: list[str],
    ) -> ChoiceQuestion:
        return make_choice(
            question_id=question_id,
            text="Which property would you like to change?",
            options=field_options,
            parameter_name="target_field",
            ambiguity_code="A3",
        )

    def ask_confirm_intent(
        self,
        question_id:  str,
        description:  str,
    ) -> ConfirmQuestion:
        return make_confirm(
            question_id=question_id,
            text=f"Just to confirm — {description}?",
            parameter_name="intent_confirmed",
            ambiguity_code="A6",
        )

    def ask_new_entity_name(
        self,
        question_id:  str,
        entity_type:  str = "character",
    ) -> FillQuestion:
        return make_fill(
            question_id=question_id,
            text=f"What would you like to call this new {entity_type}?",
            parameter_name="new_entity_id",
            expected_type="id",
            placeholder=f"e.g. my_{entity_type}",
            ambiguity_code="A5",
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hint_for_mode(mode: str) -> str:
    match mode:
        case "FULLY_ASSISTED":
            return "Pick the option that best matches what you want."
        case "COLLABORATIVE":
            return ""
        case _:
            return ""


def _derive_options(
    stub: ClarificationQuestion, cgs_slice: CGSContextSlice
) -> list[str]:
    """Derives option list from context when stub.options is empty."""
    if stub.parameter_name == "target_actor_id":
        return [
            aid.replace("actor_", "").replace("_", " ").title()
            for aid in cgs_slice.all_actor_ids_in_mode
        ]
    if stub.parameter_name == "target_field":
        options: list[str] = []
        seen: set[str] = set()
        for hint in cgs_slice.component_hints:
            for fld in hint.get("fields", []):
                leaf = fld.split(".")[-1]
                if leaf not in seen:
                    options.append(leaf)
                    seen.add(leaf)
        return options[:6]
    return []


def _infer_fill_type(parameter_name: str) -> str:
    if any(kw in parameter_name for kw in ("value", "amount", "count", "size", "rate")):
        return "float"
    if any(kw in parameter_name for kw in ("id", "name", "entity")):
        return "id"
    return "any"


def _placeholder_for(parameter_name: str) -> str:
    _placeholders = {
        "new_entity_id":    "e.g. boss_zombie",
        "rule_condition":   "e.g. when the player's health reaches 0",
        "target_field":     "e.g. health, speed",
        "numeric_value_0":  "e.g. 80",
    }
    return _placeholders.get(parameter_name, "")