"""
question_types.py — Question Type Definitions
===============================================
Defines the four question types used throughout the GDE clarification system.

Each question type is a self-contained dataclass with:
    - Structure: what data it carries
    - Validator: checks whether a user response is acceptable
    - Renderer hints: how the builder UI should display it
    - Answer parser: converts raw user input to a typed parameter value

## Four Question Types

    CHOICE       — user picks exactly one option from a fixed list
                   Builder renders as: radio buttons or pill selectors
                   Example: "Which character? ○ Player ● Zombie ○ Boss"

    CONFIRM      — user answers yes or no
                   Builder renders as: two buttons [Yes] [No]
                   Example: "Make the zombie faster?"

    FILL         — user types a free-text value
                   Builder renders as: single-line text input
                   Example: "What should the new name be?"

    SCOPE_SELECT — user selects one or more entities from a list of CGS nodes
                   Builder renders as: entity cards with checkboxes
                   Example: Shows actor cards, user taps to select

## Response Flow
    1. QuestionEngine generates a Question
    2. Builder UI renders it as a micro-form card
    3. User answers
    4. QuestionSessionManager receives the raw response
    5. question.validate(response) — check acceptable
    6. question.parse_answer(response) → typed value
    7. Typed value is written into intent.parameters[parameter_name]
    8. Pipeline resumes
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ── Validation Result ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ValidationOutcome:
    """Result of validating a user response to a question."""
    is_valid:     bool
    parsed_value: Any        = None
    error:        str        = ""


# ── Base Question ─────────────────────────────────────────────────────────────

@dataclass
class BaseQuestion:
    """
    Common fields shared by all question types.

    Attributes
    ----------
    question_id : str
        Unique identifier within a QuestionSession.
    question_type : str
        One of: "CHOICE", "CONFIRM", "FILL", "SCOPE_SELECT"
    text : str
        Plain-English question. ZERO technical vocabulary.
    parameter_name : str
        The intent parameter this question populates when answered.
    ambiguity_code : str
        A1–A7 code that triggered this question.
    is_required : bool
        If True, the pipeline cannot continue without an answer.
    default_answer : str | None
        Pre-selected or suggested answer.
    hint_text : str
        Short helper text shown below the question in the UI.
    """

    question_id:     str
    question_type:   str
    text:            str
    parameter_name:  str
    ambiguity_code:  str        = ""
    is_required:     bool       = True
    default_answer:  str | None = None
    hint_text:       str        = ""

    def validate(self, response: str) -> ValidationOutcome:
        raise NotImplementedError

    def parse_answer(self, response: str) -> Any:
        """Returns the typed value from a validated response string."""
        raise NotImplementedError

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(id={self.question_id!r}, "
            f"param={self.parameter_name!r})"
        )


# ── CHOICE Question ───────────────────────────────────────────────────────────

@dataclass
class ChoiceQuestion(BaseQuestion):
    """
    User picks exactly one option from a fixed list.

    Attributes
    ----------
    options : list[str]
        Display labels for the choices (2–6 recommended).
    option_values : list[Any]
        Typed values corresponding to each option label.
        If empty, the option label string is used as the value.
    """

    options:       list[str] = field(default_factory=list)
    option_values: list[Any] = field(default_factory=list)

    def validate(self, response: str) -> ValidationOutcome:
        response_stripped = response.strip()
        if response_stripped in self.options:
            idx = self.options.index(response_stripped)
            value = self.option_values[idx] if self.option_values else response_stripped
            return ValidationOutcome(is_valid=True, parsed_value=value)

        # Case-insensitive match
        lower_options = [o.lower() for o in self.options]
        if response_stripped.lower() in lower_options:
            idx = lower_options.index(response_stripped.lower())
            value = self.option_values[idx] if self.option_values else self.options[idx]
            return ValidationOutcome(is_valid=True, parsed_value=value)

        # Numeric index ("1", "2", ...)
        try:
            idx = int(response_stripped) - 1
            if 0 <= idx < len(self.options):
                value = self.option_values[idx] if self.option_values else self.options[idx]
                return ValidationOutcome(is_valid=True, parsed_value=value)
        except ValueError:
            pass

        return ValidationOutcome(
            is_valid=False,
            error=(
                f"Please choose one of: "
                f"{', '.join(self.options)}. "
                f"Got: {response_stripped!r}"
            ),
        )

    def parse_answer(self, response: str) -> Any:
        outcome = self.validate(response)
        if outcome.is_valid:
            return outcome.parsed_value
        return response.strip()

    def with_option_values(self, values: list[Any]) -> "ChoiceQuestion":
        """Fluent setter for option_values (post-construction)."""
        self.option_values = values
        return self


# ── CONFIRM Question ──────────────────────────────────────────────────────────

@dataclass
class ConfirmQuestion(BaseQuestion):
    """
    User answers yes or no.
    Always has exactly two options: affirmative and negative labels.
    """

    affirmative_label: str = "Yes"
    negative_label:    str = "No"

    _AFFIRMATIVE = frozenset({"yes", "y", "yeah", "yep", "sure", "ok", "okay", "correct", "1"})
    _NEGATIVE    = frozenset({"no", "n", "nope", "nah", "cancel", "0"})

    @property
    def options(self) -> list[str]:
        return [self.affirmative_label, self.negative_label]

    def validate(self, response: str) -> ValidationOutcome:
        r = response.strip().lower()
        if r in self._AFFIRMATIVE:
            return ValidationOutcome(is_valid=True, parsed_value=True)
        if r in self._NEGATIVE:
            return ValidationOutcome(is_valid=True, parsed_value=False)
        return ValidationOutcome(
            is_valid=False,
            error=f"Please answer '{self.affirmative_label}' or '{self.negative_label}'.",
        )

    def parse_answer(self, response: str) -> bool:
        outcome = self.validate(response)
        return bool(outcome.parsed_value)


# ── FILL Question ─────────────────────────────────────────────────────────────

_SNAKE_RE   = re.compile(r'^[a-z][a-z0-9_]*$')
_NUMERIC_RE = re.compile(r'^-?\d+(?:\.\d+)?$')


@dataclass
class FillQuestion(BaseQuestion):
    """
    User types a free-text value.

    Attributes
    ----------
    expected_type : str
        The type the answer should be coerced to:
        "str" | "int" | "float" | "id" | "any"
    min_length : int
        Minimum character count for a valid response.
    max_length : int
        Maximum character count. 0 = no limit.
    placeholder : str
        Example text shown in the input field.
    """

    expected_type: str   = "any"
    min_length:    int   = 1
    max_length:    int   = 0
    placeholder:   str   = ""

    def validate(self, response: str) -> ValidationOutcome:
        r = response.strip()

        if len(r) < self.min_length:
            return ValidationOutcome(
                is_valid=False,
                error=f"Response must be at least {self.min_length} character(s).",
            )
        if self.max_length > 0 and len(r) > self.max_length:
            return ValidationOutcome(
                is_valid=False,
                error=f"Response must not exceed {self.max_length} characters.",
            )

        match self.expected_type:
            case "int":
                try:
                    return ValidationOutcome(is_valid=True, parsed_value=int(r))
                except ValueError:
                    return ValidationOutcome(is_valid=False, error=f"'{r}' is not a whole number.")
            case "float":
                try:
                    return ValidationOutcome(is_valid=True, parsed_value=float(r))
                except ValueError:
                    return ValidationOutcome(is_valid=False, error=f"'{r}' is not a number.")
            case "id":
                slug = re.sub(r'[^a-z0-9]+', '_', r.lower()).strip('_')
                if not slug:
                    return ValidationOutcome(is_valid=False, error="Please provide a valid name.")
                return ValidationOutcome(is_valid=True, parsed_value=slug)
            case _:
                return ValidationOutcome(is_valid=True, parsed_value=r)

    def parse_answer(self, response: str) -> Any:
        outcome = self.validate(response)
        return outcome.parsed_value if outcome.is_valid else response.strip()


# ── SCOPE_SELECT Question ─────────────────────────────────────────────────────

@dataclass
class ScopeSelectQuestion(BaseQuestion):
    """
    User selects one entity from a list of CGS nodes.
    Rendered as entity cards with names; each card maps to an entity_id.

    Attributes
    ----------
    entity_options : list[dict]
        Each dict: {"display_name": str, "entity_id": str, "entity_type": str}
    allow_multi_select : bool
        If True, user can select multiple entities.
    """

    entity_options:    list[dict[str, str]] = field(default_factory=list)
    allow_multi_select: bool                = False

    @property
    def options(self) -> list[str]:
        return [e.get("display_name", e.get("entity_id", "?")) for e in self.entity_options]

    def validate(self, response: str) -> ValidationOutcome:
        r = response.strip()

        # Accept entity_id directly
        ids = [e.get("entity_id", "") for e in self.entity_options]
        if r in ids:
            return ValidationOutcome(is_valid=True, parsed_value=r)

        # Accept display name (case-insensitive)
        for entity in self.entity_options:
            dn = entity.get("display_name", "").lower()
            if r.lower() == dn or r.lower() == entity.get("entity_id", "").lower():
                return ValidationOutcome(
                    is_valid=True, parsed_value=entity.get("entity_id")
                )

        # Numeric index
        try:
            idx = int(r) - 1
            if 0 <= idx < len(self.entity_options):
                return ValidationOutcome(
                    is_valid=True,
                    parsed_value=self.entity_options[idx].get("entity_id"),
                )
        except ValueError:
            pass

        return ValidationOutcome(
            is_valid=False,
            error=f"Please select one of: {self.options}.",
        )

    def parse_answer(self, response: str) -> Any:
        outcome = self.validate(response)
        return outcome.parsed_value if outcome.is_valid else response.strip()

    @classmethod
    def from_actor_ids(
        cls,
        question_id:    str,
        text:           str,
        actor_ids:      list[str],
        parameter_name: str,
        ambiguity_code: str = "A2",
    ) -> "ScopeSelectQuestion":
        """Convenience factory for actor-selection questions."""
        entities = [
            {
                "entity_id":    aid,
                "display_name": aid.replace("actor_", "").replace("_", " ").title(),
                "entity_type":  "actor",
            }
            for aid in actor_ids
        ]
        return cls(
            question_id=question_id,
            question_type="SCOPE_SELECT",
            text=text,
            parameter_name=parameter_name,
            entity_options=entities,
            ambiguity_code=ambiguity_code,
        )


# ── Factory ───────────────────────────────────────────────────────────────────

def make_choice(
    question_id:    str,
    text:           str,
    options:        list[str],
    parameter_name: str,
    option_values:  list[Any] | None = None,
    default:        str | None       = None,
    ambiguity_code: str              = "",
    hint_text:      str              = "",
) -> ChoiceQuestion:
    """Convenience factory for ChoiceQuestion."""
    return ChoiceQuestion(
        question_id=question_id,
        question_type="CHOICE",
        text=text,
        parameter_name=parameter_name,
        options=options,
        option_values=option_values or [],
        default_answer=default,
        ambiguity_code=ambiguity_code,
        hint_text=hint_text,
    )


def make_confirm(
    question_id:    str,
    text:           str,
    parameter_name: str,
    default:        str | None = "Yes",
    ambiguity_code: str        = "",
) -> ConfirmQuestion:
    return ConfirmQuestion(
        question_id=question_id,
        question_type="CONFIRM",
        text=text,
        parameter_name=parameter_name,
        default_answer=default,
        ambiguity_code=ambiguity_code,
    )


def make_fill(
    question_id:    str,
    text:           str,
    parameter_name: str,
    expected_type:  str        = "any",
    placeholder:    str        = "",
    ambiguity_code: str        = "",
    hint_text:      str        = "",
) -> FillQuestion:
    return FillQuestion(
        question_id=question_id,
        question_type="FILL",
        text=text,
        parameter_name=parameter_name,
        expected_type=expected_type,
        placeholder=placeholder,
        ambiguity_code=ambiguity_code,
        hint_text=hint_text,
    )