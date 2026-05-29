"""
clarification_session.py — ClarificationSession
=================================================
Manages state for one clarification interaction.

A ClarificationSession is created when the pipeline cannot proceed
without additional user input. It tracks:
    - The ordered queue of questions to ask
    - Which question is currently pending
    - User answers collected so far
    - The pipeline resume point (where to re-enter after answers)
    - Session timeout

## Lifecycle

    1. ClarificationEngine creates a ClarificationSession with questions.
    2. The builder UI reads the current_question and renders it.
    3. The user answers via submit_answer().
    4. If more questions remain, the UI renders the next one.
    5. When is_complete, the pipeline resumes at resume_point.
    6. ClarificationEngine.apply_answers() merges resolved parameters
       back into the pipeline context.

## Resume Points

    "pass1_planning"      — restart from Pass 1 with clarified intent
    "pass2_dsl_draft"     — restart Pass 2 with clarified scope/value
    "intake"              — restart from IntentIntakeLayer (full restart)
    "scope_resolution"    — resume at ScopeBuilder after actor/mode clarified

## Timeout

    Sessions expire after SESSION_TIMEOUT_SECONDS (default 300 = 5 minutes).
    An expired session must be discarded and the pipeline restarted.
    is_expired checks against the session's creation time.

## Answer Validation

    Each question has an expected answer type. submit_answer() validates:
        CHOICE     — answer must be one of the listed options
        CONFIRM    — answer must be a boolean-equivalent string
        FILL       — any non-empty string
        SCOPE_SELECT — answer must match a CGS entity ID
    Invalid answers set the error field without advancing the question index.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


# ── Constants ─────────────────────────────────────────────────────────────────

SESSION_TIMEOUT_SECONDS = 300   # 5 minutes
MAX_QUESTIONS_PER_SESSION = 5   # never ask more than 5 questions in one session

# Question types
class QuestionType:
    CHOICE       = "CHOICE"       # pick one of N labelled options
    CONFIRM      = "CONFIRM"      # yes / no
    FILL         = "FILL"         # free-text fill-in with optional hint
    SCOPE_SELECT = "SCOPE_SELECT" # pick a CGS entity (actor, system, mode, rule)

    ALL = frozenset({CHOICE, CONFIRM, FILL, SCOPE_SELECT})


# ── Question ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ClarificationQuestion:
    """
    One structured micro-form question.

    Attributes
    ----------
    question_id   : str            — unique ID within the session
    question_type : str            — QuestionType constant
    prompt        : str            — question text shown to user
    options       : tuple[str,...] — for CHOICE/SCOPE_SELECT: the allowed choices
    hint          : str            — for FILL: format hint (e.g. "a number like 20")
    parameter_key : str            — which parameter this answer resolves
                                     (e.g. "target_actor_id", "numeric_value")
    required      : bool           — whether an answer is mandatory to proceed
    """
    question_id:   str
    question_type: str
    prompt:        str
    options:       tuple[str, ...]  = field(default_factory=tuple)
    hint:          str              = ""
    parameter_key: str              = ""
    required:      bool             = True

    def validate_answer(self, raw_answer: str) -> tuple[bool, str]:
        """
        Validates a raw answer string against this question's type.
        Returns (is_valid, error_message_or_empty).
        """
        answer = raw_answer.strip()

        if not answer and self.required:
            return False, "An answer is required for this question."

        if self.question_type == QuestionType.CHOICE:
            if self.options and answer not in self.options:
                return False, (
                    f"Please choose one of: {', '.join(self.options)}. "
                    f"Got: {answer!r}"
                )

        elif self.question_type == QuestionType.CONFIRM:
            normalised = answer.lower()
            if normalised not in {"yes", "no", "y", "n", "true", "false"}:
                return False, (
                    f"Please answer 'yes' or 'no'. Got: {answer!r}"
                )

        elif self.question_type == QuestionType.FILL:
            if not answer:
                return False, "Please provide a value."

        elif self.question_type == QuestionType.SCOPE_SELECT:
            if self.options and answer not in self.options:
                return False, (
                    f"Please select a valid entity ID from: "
                    f"{', '.join(self.options)}. Got: {answer!r}"
                )

        return True, ""

    def normalise_answer(self, raw_answer: str) -> Any:
        """
        Normalises a validated answer to its canonical Python type.
        CONFIRM → bool, FILL with numeric hint → float/int if parseable, others → str.
        """
        answer = raw_answer.strip()
        if self.question_type == QuestionType.CONFIRM:
            return answer.lower() in {"yes", "y", "true"}
        if self.question_type == QuestionType.FILL and self.hint:
            # Try numeric coercion if hint suggests a number
            if "number" in self.hint.lower() or "value" in self.hint.lower():
                try:
                    if "." in answer:
                        return float(answer)
                    return int(answer)
                except ValueError:
                    pass
        return answer

    def __repr__(self) -> str:
        return (
            f"ClarificationQuestion({self.question_type}, "
            f"key={self.parameter_key!r}, "
            f"{self.prompt[:50]!r})"
        )


# ── Session Answer ────────────────────────────────────────────────────────────

@dataclass
class SessionAnswer:
    """One recorded answer within a session."""
    question_id:    str
    parameter_key:  str
    raw_answer:     str
    normalised:     Any
    answered_at:    float = field(default_factory=time.time)


# ── Clarification Session ─────────────────────────────────────────────────────

class ClarificationSession:
    """
    Stateful session for one clarification interaction.

    Not thread-safe — one instance per builder session turn.

    Usage
    -----
        session = ClarificationSession(
            questions    = [q1, q2],
            resume_point = "pass2_dsl_draft",
        )

        q = session.current_question   # q1
        session.submit_answer("actor_zombie")
        q = session.current_question   # q2
        session.submit_answer("50.0")
        session.is_complete            # True
        session.resolved_parameters    # {"target_actor_id": "actor_zombie", ...}
    """

    def __init__(
        self,
        questions:    list[ClarificationQuestion],
        resume_point: str  = "pass1_planning",
        session_id:   str | None = None,
    ) -> None:
        if len(questions) > MAX_QUESTIONS_PER_SESSION:
            questions = questions[:MAX_QUESTIONS_PER_SESSION]

        self._questions:    list[ClarificationQuestion] = list(questions)
        self._resume_point: str                         = resume_point
        self._session_id:   str = session_id or uuid.uuid4().hex
        self._created_at:   float = time.time()
        self._current_idx:  int   = 0
        self._answers:      list[SessionAnswer] = []
        self._last_error:   str = ""

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def resume_point(self) -> str:
        return self._resume_point

    # ── State ─────────────────────────────────────────────────────────────────

    @property
    def is_complete(self) -> bool:
        """True when all required questions have been answered."""
        return self._current_idx >= len(self._questions)

    @property
    def is_expired(self) -> bool:
        return (time.time() - self._created_at) > SESSION_TIMEOUT_SECONDS

    @property
    def current_question(self) -> ClarificationQuestion | None:
        """The question currently awaiting an answer, or None if complete."""
        if self.is_complete:
            return None
        return self._questions[self._current_idx]

    @property
    def question_count(self) -> int:
        return len(self._questions)

    @property
    def answered_count(self) -> int:
        return self._current_idx

    @property
    def remaining_count(self) -> int:
        return max(0, len(self._questions) - self._current_idx)

    @property
    def last_error(self) -> str:
        """Last validation error from submit_answer, or empty string."""
        return self._last_error

    @property
    def progress(self) -> str:
        """Human-readable progress: "1 of 3"."""
        return f"{self._current_idx + 1} of {len(self._questions)}"

    # ── Answer submission ─────────────────────────────────────────────────────

    def submit_answer(self, raw_answer: str) -> bool:
        """
        Submits an answer to the current question.

        Parameters
        ----------
        raw_answer : str
            Raw string answer from the user.

        Returns
        -------
        bool
            True if the answer was accepted and session advanced.
            False if the answer was invalid (check last_error).
        """
        if self.is_complete:
            self._last_error = "Session is already complete."
            return False

        if self.is_expired:
            self._last_error = "Session has expired. Please restart."
            return False

        q = self._questions[self._current_idx]
        is_valid, error = q.validate_answer(raw_answer)

        if not is_valid:
            self._last_error = error
            return False

        normalised = q.normalise_answer(raw_answer)
        self._answers.append(SessionAnswer(
            question_id   = q.question_id,
            parameter_key = q.parameter_key,
            raw_answer    = raw_answer.strip(),
            normalised    = normalised,
        ))
        self._last_error  = ""
        self._current_idx += 1
        return True

    # ── Resolved parameters ───────────────────────────────────────────────────

    @property
    def resolved_parameters(self) -> dict[str, Any]:
        """
        Returns parameter_key → normalised_value for all answered questions.
        Used by ClarificationEngine.apply_answers() to update pipeline context.
        """
        return {
            a.parameter_key: a.normalised
            for a in self._answers
            if a.parameter_key
        }

    @property
    def all_answers(self) -> list[SessionAnswer]:
        return list(self._answers)

    # ── Serialization ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "session_id":    self._session_id,
            "resume_point":  self._resume_point,
            "is_complete":   self.is_complete,
            "is_expired":    self.is_expired,
            "answered_count": self.answered_count,
            "total_questions": self.question_count,
            "resolved_parameters": self.resolved_parameters,
        }

    def __repr__(self) -> str:
        status = "complete" if self.is_complete else f"{self.progress}"
        return (
            f"ClarificationSession(id={self._session_id[:8]}, "
            f"resume={self._resume_point!r}, {status})"
        )