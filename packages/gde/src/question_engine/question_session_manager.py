"""
question_session_manager.py — QuestionSessionManager
======================================================
Manages the lifecycle of one clarification session.

A clarification session starts when the GDE encounters an ambiguous intent.
It presents questions one at a time and collects answers until all ambiguity
is resolved or the session times out.

## Session States
    PENDING   — session created, first question not yet shown
    ACTIVE    — a question is currently awaiting a user response
    ANSWERED  — current question answered, more questions may follow
    COMPLETE  — all questions answered, pipeline may resume
    CANCELLED — user cancelled or session timed out
    FAILED    — an unrecoverable error occurred

## Answer Flow
    1. session.current_question()   → the pending question
    2. session.submit_answer(text)  → validate + record answer
    3. session.is_complete()        → True when all questions answered
    4. session.resolved_parameters()→ dict of parameter_name → typed value
    5. GDE orchestrator merges resolved_parameters into the intent
    6. GDE orchestrator resumes the pipeline from the recorded resume_point

## Resume Point
The resume_point is a string label identifying where in the GDE pipeline
to resume after clarification:
    "slot_extraction"   — re-run slot extraction with enriched intent
    "scope_resolution"  — re-run scope resolver
    "transaction_build" — proceed directly to transaction building
    "full_pipeline"     — restart from intent classification
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .question_types import BaseQuestion, ValidationOutcome


# ── Session States ────────────────────────────────────────────────────────────

class SessionState:
    PENDING   = "PENDING"
    ACTIVE    = "ACTIVE"
    ANSWERED  = "ANSWERED"
    COMPLETE  = "COMPLETE"
    CANCELLED = "CANCELLED"
    FAILED    = "FAILED"


# ── Session Answer ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SessionAnswer:
    """Records one answered question."""
    question_id:    str
    parameter_name: str
    raw_response:   str
    parsed_value:   Any
    answered_at:    float = field(default_factory=time.time)


# ── Session Error ─────────────────────────────────────────────────────────────

class SessionError(Exception):
    """Raised when a QuestionSession operation fails."""


# ── Question Session ──────────────────────────────────────────────────────────

@dataclass
class QuestionSession:
    """
    State for one in-progress clarification session.

    Created by QuestionSessionManager.create_session().
    Managed exclusively through QuestionSessionManager methods.

    Attributes
    ----------
    session_id : str
        Unique session identifier (UUID4 hex).
    questions : list[BaseQuestion]
        Ordered questions to ask, produced by QuestionEngine.
    answers : list[SessionAnswer]
        Answers collected so far, in answer order.
    state : str
        Current session state (one of SessionState constants).
    current_index : int
        Index into questions of the currently active question.
    resume_point : str
        Where in the GDE pipeline to resume after completion.
    intent_snapshot : dict
        Snapshot of intent.scope + intent.action at session creation.
        Used to detect if the intent changed between questions.
    created_at : float
        Unix timestamp of session creation.
    timeout_seconds : float
        Seconds before the session auto-cancels (0 = no timeout).
    """

    session_id:       str
    questions:        list[BaseQuestion]
    answers:          list[SessionAnswer]     = field(default_factory=list)
    state:            str                     = SessionState.PENDING
    current_index:    int                     = 0
    resume_point:     str                     = "slot_extraction"
    intent_snapshot:  dict[str, Any]          = field(default_factory=dict)
    created_at:       float                   = field(default_factory=time.time)
    timeout_seconds:  float                   = 120.0

    def is_timed_out(self) -> bool:
        if self.timeout_seconds <= 0:
            return False
        return (time.time() - self.created_at) > self.timeout_seconds

    def question_count(self) -> int:
        return len(self.questions)

    def answered_count(self) -> int:
        return len(self.answers)

    def remaining_count(self) -> int:
        return self.question_count() - self.answered_count()

    def resolved_parameters(self) -> dict[str, Any]:
        """Returns all answered parameters as a flat dict."""
        return {ans.parameter_name: ans.parsed_value for ans in self.answers}

    def __repr__(self) -> str:
        return (
            f"QuestionSession(id={self.session_id[:8]}, "
            f"state={self.state}, "
            f"{self.answered_count()}/{self.question_count()} answered)"
        )


# ── Question Session Manager ──────────────────────────────────────────────────

class QuestionSessionManager:
    """
    Creates, manages, and resolves clarification sessions.

    Maintains a registry of active sessions keyed by session_id.
    Sessions are cleaned up when they complete, cancel, or expire.

    Usage
    -----
        manager = QuestionSessionManager()

        # Start a session
        session = manager.create_session(questions, resume_point="scope_resolution")

        # Get the first question
        q = manager.current_question(session.session_id)

        # Submit an answer
        result = manager.submit_answer(session.session_id, "Zombie")

        # Check if done
        if manager.is_complete(session.session_id):
            params = manager.resolved_parameters(session.session_id)
            # merge params into intent and resume pipeline
    """

    def __init__(self) -> None:
        self._sessions: dict[str, QuestionSession] = {}

    # ── Session Lifecycle ─────────────────────────────────────────────────────

    def create_session(
        self,
        questions:       list[BaseQuestion],
        resume_point:    str                  = "slot_extraction",
        intent_snapshot: dict[str, Any]       | None = None,
        timeout_seconds: float                = 120.0,
    ) -> QuestionSession:
        """
        Creates a new QuestionSession and registers it.

        Parameters
        ----------
        questions : list[BaseQuestion]
            Ordered questions from QuestionEngine.build().
        resume_point : str
            GDE pipeline label to resume after completion.
        intent_snapshot : dict | None
            Snapshot of the intent at session creation.
        timeout_seconds : float
            Auto-cancel timeout. 0 = no timeout.

        Returns
        -------
        QuestionSession
            The created session (also stored internally by session_id).
        """
        if not questions:
            raise SessionError(
                "Cannot create a session with no questions. "
                "Check that AmbiguityDetector produced a non-empty "
                "ClarificationRequest before creating a session."
            )

        session = QuestionSession(
            session_id=uuid.uuid4().hex,
            questions=questions,
            state=SessionState.PENDING,
            resume_point=resume_point,
            intent_snapshot=intent_snapshot or {},
            timeout_seconds=timeout_seconds,
        )
        self._sessions[session.session_id] = session
        return session

    def cancel_session(self, session_id: str) -> None:
        """Cancels an active session."""
        session = self._get_session(session_id)
        session.state = SessionState.CANCELLED

    def close_session(self, session_id: str) -> None:
        """Removes a completed or cancelled session from the registry."""
        self._sessions.pop(session_id, None)

    # ── Question Flow ─────────────────────────────────────────────────────────

    def current_question(self, session_id: str) -> BaseQuestion | None:
        """
        Returns the current pending question, or None if the session is complete.
        Automatically cancels timed-out sessions.
        """
        session = self._get_session(session_id)

        if session.is_timed_out():
            session.state = SessionState.CANCELLED
            return None

        if session.state in (SessionState.COMPLETE, SessionState.CANCELLED):
            return None

        if session.current_index >= len(session.questions):
            session.state = SessionState.COMPLETE
            return None

        session.state = SessionState.ACTIVE
        return session.questions[session.current_index]

    def submit_answer(
        self,
        session_id: str,
        raw_response: str,
    ) -> ValidationOutcome:
        """
        Validates and records a user's answer to the current question.

        On success: advances to the next question (or marks COMPLETE).
        On failure: returns the validation error — question stays active.

        Parameters
        ----------
        session_id : str
            The session to advance.
        raw_response : str
            The user's raw text input.

        Returns
        -------
        ValidationOutcome
            is_valid=True means answer accepted and recorded.
            is_valid=False means answer rejected — show error to user.
        """
        session = self._get_session(session_id)

        if session.state not in (SessionState.PENDING, SessionState.ACTIVE, SessionState.ANSWERED):
            raise SessionError(
                f"Session '{session_id[:8]}' is in state '{session.state}' "
                f"and cannot accept answers."
            )

        if session.is_timed_out():
            session.state = SessionState.CANCELLED
            raise SessionError(
                f"Session '{session_id[:8]}' has timed out. "
                f"Please restart the clarification flow."
            )

        current_q = session.questions[session.current_index]
        outcome   = current_q.validate(raw_response)

        if not outcome.is_valid:
            return outcome

        # Record the answer
        session.answers.append(SessionAnswer(
            question_id=current_q.question_id,
            parameter_name=current_q.parameter_name,
            raw_response=raw_response,
            parsed_value=outcome.parsed_value,
        ))

        # Advance to next question
        session.current_index += 1
        if session.current_index >= len(session.questions):
            session.state = SessionState.COMPLETE
        else:
            session.state = SessionState.ANSWERED

        return outcome

    def skip_question(self, session_id: str) -> None:
        """
        Skips the current question (only for non-required questions).
        Raises SessionError if the question is required.
        """
        session  = self._get_session(session_id)
        current_q = session.questions[session.current_index]

        if current_q.is_required:
            raise SessionError(
                f"Question '{current_q.question_id}' is required and cannot be skipped."
            )

        session.current_index += 1
        if session.current_index >= len(session.questions):
            session.state = SessionState.COMPLETE

    # ── Result Access ─────────────────────────────────────────────────────────

    def is_complete(self, session_id: str) -> bool:
        """True if all questions have been answered."""
        session = self._get_session(session_id)
        return session.state == SessionState.COMPLETE

    def is_cancelled(self, session_id: str) -> bool:
        session = self._get_session(session_id)
        return session.state == SessionState.CANCELLED

    def resolved_parameters(self, session_id: str) -> dict[str, Any]:
        """
        Returns all collected answers as parameter_name → typed_value dict.
        Only valid after is_complete() returns True.
        """
        session = self._get_session(session_id)
        return session.resolved_parameters()

    def resume_point(self, session_id: str) -> str:
        """Returns the GDE pipeline resume label for this session."""
        return self._get_session(session_id).resume_point

    def session_summary(self, session_id: str) -> dict[str, Any]:
        """Returns a summary dict for logging and builder UI display."""
        session = self._get_session(session_id)
        return {
            "session_id":       session.session_id,
            "state":            session.state,
            "question_count":   session.question_count(),
            "answered_count":   session.answered_count(),
            "remaining_count":  session.remaining_count(),
            "resume_point":     session.resume_point,
            "resolved":         session.resolved_parameters(),
        }

    def active_session_count(self) -> int:
        return sum(
            1 for s in self._sessions.values()
            if s.state in (SessionState.PENDING, SessionState.ACTIVE, SessionState.ANSWERED)
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _get_session(self, session_id: str) -> QuestionSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionError(
                f"Session '{session_id[:8]}…' not found. "
                f"It may have been closed or never created."
            )
        return session