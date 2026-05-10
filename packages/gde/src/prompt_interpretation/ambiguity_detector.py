"""
ambiguity_detector.py — AmbiguityDetector
===========================================
Detects ambiguity in a processed IntentObject and generates
structured clarification questions when the intent is too uncertain
to safely proceed.

## When Is an Intent Ambiguous?
    A1 — No target actor could be resolved (actor hint matched nothing)
    A2 — Multiple actors matched the hint (which zombie?)
    A3 — No target field could be resolved (what property to change?)
    A4 — A numeric value is present but which field it targets is unclear
    A5 — A structural intent (ADD_ACTOR, ADD_RULE) is missing required data
    A6 — The intent confidence is below the proceed threshold
    A7 — The intent type is UNKNOWN

## Output
When ambiguous, the detector sets intent.requires_clarification=True
and populates intent.clarification_questions with plain-English questions.
It also returns a ClarificationRequest with structured question data
(CHOICE | CONFIRM | FILL | SCOPE_SELECT) for the builder UI to render
as micro-form cards — not chat messages.

## Proceed vs Ask
The detector does NOT block execution. It sets flags. The GDE orchestrator
decides whether to ask the user or proceed with best-guess values.
The mode profiles control this:
    FULLY_ASSISTED  — ask on confidence < 0.70
    COLLABORATIVE   — ask on confidence < 0.55
    ADVANCED        — ask only on UNKNOWN or A5 missing required data
    ARCHITECT_MODE  — never asks, always proceeds
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .intent_object import IntentObject, GDEIntentType
from .context_loader import CGSContextSlice


# ── Question Types ────────────────────────────────────────────────────────────

class QuestionType:
    CHOICE       = "CHOICE"        # user picks one option from a list
    CONFIRM      = "CONFIRM"       # user confirms yes/no
    FILL         = "FILL"          # user types a value
    SCOPE_SELECT = "SCOPE_SELECT"  # user selects which entity is affected


# ── Clarification Question ────────────────────────────────────────────────────

@dataclass
class ClarificationQuestion:
    """
    One structured clarification question for the builder UI.

    Rendered as a micro-form card — not a chat message.

    Attributes
    ----------
    question_id : str
        Unique identifier within the ClarificationRequest.
    question_type : str
        One of QuestionType constants — determines UI widget.
    text : str
        Plain-English question text. ZERO technical vocabulary.
        ✓ "Which character should move faster?"
        ✗ "Which actor_id should the COMP_VELOCITY_V1 mutation target?"
    options : list[str]
        For CHOICE and SCOPE_SELECT: the selectable options.
        For CONFIRM: ["Yes", "No"].
        For FILL: empty (free-text input).
    parameter_name : str
        The IntentObject parameter this question resolves.
        The answer populates intent.parameters[parameter_name].
    default : str | None
        Default selection (shown pre-selected in UI).
    ambiguity_code : str
        Which ambiguity code (A1–A7) triggered this question.
    """

    question_id:     str
    question_type:   str
    text:            str
    options:         list[str]      = field(default_factory=list)
    parameter_name:  str            = ""
    default:         str | None     = None
    ambiguity_code:  str            = ""

    def __repr__(self) -> str:
        return (
            f"ClarificationQuestion({self.question_type}: "
            f"{self.text[:50]!r}...)"
        )


# ── Clarification Request ─────────────────────────────────────────────────────

@dataclass
class ClarificationRequest:
    """
    A set of clarification questions blocking intent execution.

    Returned by AmbiguityDetector when the intent cannot be safely
    executed without user input. The GDE orchestrator sends this to
    the builder UI, which renders it as interactive cards.

    Attributes
    ----------
    intent_type : str
        The intent type that triggered clarification.
    questions : list[ClarificationQuestion]
        Ordered questions — answer each to resolve all ambiguities.
    summary : str
        One-sentence plain-English explanation of why we're asking.
    can_proceed_with_defaults : bool
        True if ADVANCED/ARCHITECT mode should proceed without asking.
    """

    intent_type:                str
    questions:                  list[ClarificationQuestion]
    summary:                    str
    can_proceed_with_defaults:  bool   = False

    def question_count(self) -> int:
        return len(self.questions)

    def is_empty(self) -> bool:
        return not self.questions

    def __repr__(self) -> str:
        return (
            f"ClarificationRequest(type={self.intent_type!r}, "
            f"{len(self.questions)} questions)"
        )


# ── Ambiguity Detector ────────────────────────────────────────────────────────

class AmbiguityDetector:
    """
    Detects ambiguity in a processed IntentObject and generates
    structured clarification questions.

    Stateless — call detect() once per intent. Updates intent in-place
    and returns a ClarificationRequest (may be empty if no ambiguity).

    Usage
    -----
        detector = AmbiguityDetector()
        request  = detector.detect(intent, cgs_slice, confidence_threshold=0.70)
        if not request.is_empty():
            return request   # send to builder UI
        # else proceed with intent execution
    """

    def detect(
        self,
        intent:               IntentObject,
        cgs_slice:            CGSContextSlice,
        confidence_threshold: float = 0.70,
    ) -> ClarificationRequest:
        """
        Detects ambiguity and returns a ClarificationRequest.

        Updates intent.requires_clarification and
        intent.clarification_questions in-place.

        An empty ClarificationRequest means no ambiguity detected.
        """
        questions: list[ClarificationQuestion] = []
        _id = [0]   # mutable counter for question IDs

        def next_id() -> str:
            _id[0] += 1
            return f"q{_id[0]:02d}"

        # ── A7: UNKNOWN intent ────────────────────────────────────────────────
        if intent.intent_type == GDEIntentType.UNKNOWN:
            q = ClarificationQuestion(
                question_id=next_id(),
                question_type=QuestionType.FILL,
                text=(
                    "I'm not sure what you'd like to change. "
                    "Could you describe what you want — for example, "
                    "'make the zombie faster' or 'add a health rule'?"
                ),
                parameter_name="intent_description",
                ambiguity_code="A7",
            )
            questions.append(q)
            _mark_intent(intent, questions)
            return ClarificationRequest(
                intent_type=intent.intent_type,
                questions=questions,
                summary="I couldn't understand what you'd like to do.",
                can_proceed_with_defaults=False,
            )

        # ── A1: No actor resolved ─────────────────────────────────────────────
        if (
            not intent.actor_id
            and intent.scope.get("actor_hint")
            and not GDEIntentType.is_query(intent.intent_type)
        ):
            actor_ids = cgs_slice.all_actor_ids_in_mode
            if actor_ids:
                display_names = _actor_display_names(actor_ids)
                questions.append(ClarificationQuestion(
                    question_id=next_id(),
                    question_type=QuestionType.SCOPE_SELECT,
                    text="Which character should this change apply to?",
                    options=display_names,
                    parameter_name="target_actor_id",
                    ambiguity_code="A1",
                ))

        # ── A2: Multiple actors matched ───────────────────────────────────────
        candidates = intent.scope.get("candidate_actor_ids", [])
        if len(candidates) > 1:
            display_names = _actor_display_names(candidates)
            questions.append(ClarificationQuestion(
                question_id=next_id(),
                question_type=QuestionType.SCOPE_SELECT,
                text=(
                    f"I found {len(candidates)} characters that could match. "
                    f"Which one did you mean?"
                ),
                options=display_names,
                default=display_names[0] if display_names else None,
                parameter_name="target_actor_id",
                ambiguity_code="A2",
            ))

        # ── A3: No field resolved for value mutations ─────────────────────────
        if (
            intent.intent_type in (
                GDEIntentType.SET_VALUE, GDEIntentType.MODIFY_VALUE,
                GDEIntentType.SCALE_VALUE,
            )
            and not intent.has_parameter("target_field")
            and not intent.action.get("field")
        ):
            field_options = _collect_field_options(cgs_slice)
            if field_options:
                questions.append(ClarificationQuestion(
                    question_id=next_id(),
                    question_type=QuestionType.CHOICE,
                    text="Which property would you like to change?",
                    options=field_options,
                    parameter_name="target_field",
                    ambiguity_code="A3",
                ))
            else:
                questions.append(ClarificationQuestion(
                    question_id=next_id(),
                    question_type=QuestionType.FILL,
                    text="Which property would you like to change? (e.g. health, speed)",
                    parameter_name="target_field",
                    ambiguity_code="A3",
                ))

        # ── A4: Value present but field unclear ───────────────────────────────
        numeric_params = [
            p for p in intent.parameters
            if p.get("type_hint") in ("float", "int") and "value" in p.get("name", "")
        ]
        if (
            numeric_params
            and not intent.has_parameter("target_field")
            and not intent.action.get("field")
            and not any(q.ambiguity_code == "A3" for q in questions)
        ):
            value = numeric_params[0]["value"]
            field_options = _collect_field_options(cgs_slice)
            if field_options:
                questions.append(ClarificationQuestion(
                    question_id=next_id(),
                    question_type=QuestionType.CHOICE,
                    text=f"You mentioned {value} — what should it apply to?",
                    options=field_options,
                    parameter_name="target_field",
                    ambiguity_code="A4",
                ))

        # ── A5: Structural intent missing required data ───────────────────────
        if intent.intent_type == GDEIntentType.CREATE_ACTOR:
            if not intent.has_parameter("new_entity_id"):
                questions.append(ClarificationQuestion(
                    question_id=next_id(),
                    question_type=QuestionType.FILL,
                    text="What would you like to call this new character?",
                    parameter_name="new_entity_id",
                    ambiguity_code="A5",
                ))

        if intent.intent_type == GDEIntentType.DEFINE_RULE:
            has_condition = intent.has_parameter("implied_condition")
            if not has_condition:
                questions.append(ClarificationQuestion(
                    question_id=next_id(),
                    question_type=QuestionType.FILL,
                    text=(
                        "When should this rule fire? "
                        "For example: 'when the player's health reaches 0'"
                    ),
                    parameter_name="rule_condition",
                    ambiguity_code="A5",
                ))

        # ── A6: Low overall confidence ────────────────────────────────────────
        if intent.confidence < confidence_threshold and not questions:
            questions.append(ClarificationQuestion(
                question_id=next_id(),
                question_type=QuestionType.CONFIRM,
                text=(
                    f"Just to confirm — you want to "
                    f"{_intent_plain_english(intent)}?"
                ),
                options=["Yes, that's right", "No, let me rephrase"],
                parameter_name="intent_confirmed",
                default="Yes, that's right",
                ambiguity_code="A6",
            ))

        if questions:
            _mark_intent(intent, questions)

        can_proceed = (
            intent.intent_type not in (GDEIntentType.UNKNOWN,)
            and not any(q.ambiguity_code == "A5" for q in questions)
        )

        summary = _build_summary(questions)
        return ClarificationRequest(
            intent_type=intent.intent_type,
            questions=questions,
            summary=summary,
            can_proceed_with_defaults=can_proceed,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mark_intent(
    intent: IntentObject, questions: list[ClarificationQuestion]
) -> None:
    intent.requires_clarification = True
    for q in questions:
        if q.text not in intent.clarification_questions:
            intent.clarification_questions.append(q.text)


def _actor_display_names(actor_ids: list[str]) -> list[str]:
    """Converts actor_ids to display names by stripping 'actor_' prefix."""
    return [
        aid.replace("actor_", "").replace("_", " ").title()
        for aid in actor_ids
    ]


def _collect_field_options(cgs_slice: CGSContextSlice) -> list[str]:
    """Collects all known field names from the context slice's component hints."""
    options: list[str] = []
    seen: set[str] = set()
    for comp_hint in cgs_slice.component_hints:
        for fld in comp_hint.get("fields", []):
            leaf = fld.split(".")[-1]
            if leaf not in seen:
                options.append(leaf)
                seen.add(leaf)
    return options[:8]  # cap at 8 options for UI


def _intent_plain_english(intent: IntentObject) -> str:
    """Returns a one-phrase plain-English description of the intent."""
    _type_descriptions = {
        GDEIntentType.SET_VALUE:       "set a value",
        GDEIntentType.MODIFY_VALUE:    "change a value",
        GDEIntentType.SCALE_VALUE:     "scale a value",
        GDEIntentType.CREATE_ACTOR:    "add a new character",
        GDEIntentType.REMOVE_ACTOR:    "remove a character",
        GDEIntentType.ADD_COMPONENT:   "add a component",
        GDEIntentType.REMOVE_COMPONENT:"remove a component",
        GDEIntentType.DEFINE_RULE:     "add a rule",
        GDEIntentType.MODIFY_RULE:     "change a rule",
        GDEIntentType.REMOVE_RULE:     "remove a rule",
        GDEIntentType.CREATE_SYSTEM:   "add a system",
        GDEIntentType.REMOVE_SYSTEM:   "remove a system",
    }
    return _type_descriptions.get(intent.intent_type, "make a change")


def _build_summary(questions: list[ClarificationQuestion]) -> str:
    if not questions:
        return ""
    codes = {q.ambiguity_code for q in questions}
    if "A7" in codes:
        return "I couldn't understand what you'd like to do."
    if "A1" in codes or "A2" in codes:
        return "I need to know which character this change applies to."
    if "A3" in codes or "A4" in codes:
        return "I need to know which property you'd like to change."
    if "A5" in codes:
        return "I need a bit more information to complete this change."
    return "I'd like to confirm a few details before making this change."