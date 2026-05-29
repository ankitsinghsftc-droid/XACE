"""
clarification_engine.py — ClarificationEngine
================================================
Orchestrates the full clarification loop.

Invoked when:
    1. llm_orchestrator returns PipelineResult(needs_clarification=True)
    2. IntentIntakeLayer produces IntentEnvelope(requires_clarification=True)
    3. ModeController is COLLABORATIVE/FULLY_ASSISTED and confidence < threshold

## Responsibilities

    create_session()
        Detects ambiguity signals from the IntentEnvelope + optional
        retry failure context, generates questions via QuestionGenerator,
        and returns a ClarificationSession ready for the builder UI.

    get_current_question()
        Returns the ClarificationQuestion the UI should render now.

    submit_answer()
        Forwards the user's answer to the active session.
        Returns True if accepted, False with error details if invalid.

    is_session_complete()
        True when all questions have been answered.

    apply_answers()
        Returns an updated IntentEnvelope or parameter dict that the
        pipeline can use to resume at the appropriate resume_point.

    close_session()
        Discards the session. Called after pipeline resumes successfully.

## Session Store

    ClarificationEngine maintains a small in-memory session store
    (dict[session_id → ClarificationSession]). Expired sessions are
    cleaned up lazily on create_session() calls.
    Max concurrent sessions: 10 per ClarificationEngine instance
    (one per active builder tab).

## apply_answers() Output

    Returns ClarificationOutcome:
        resume_point      : str              — where to re-enter the pipeline
        resolved_params   : dict[str, Any]   — parameter_key → normalised value
        rephrased_prompt  : str | None       — if user rephrased the prompt
        confirmed         : bool | None      — if user confirmed a destructive op
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "intent_intake"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "llm_orchestrator"))

from intent_envelope import IntentEnvelope
from clarification_session import ClarificationSession, ClarificationQuestion
from question_generator import QuestionGenerator, AmbiguitySignal


# ── Constants ─────────────────────────────────────────────────────────────────

MAX_CONCURRENT_SESSIONS = 10


# ── Exceptions ────────────────────────────────────────────────────────────────

class SessionNotFoundError(Exception):
    def __init__(self, session_id: str) -> None:
        super().__init__(f"Clarification session '{session_id}' not found or expired.")
        self.session_id = session_id


class SessionExpiredError(Exception):
    def __init__(self, session_id: str) -> None:
        super().__init__(f"Clarification session '{session_id}' has expired.")
        self.session_id = session_id


class NothingToClarifyError(Exception):
    """Raised when create_session() is called but no signals are detected."""


# ── Clarification Outcome ─────────────────────────────────────────────────────

@dataclass
class ClarificationOutcome:
    """
    Output of ClarificationEngine.apply_answers().

    Attributes
    ----------
    resume_point      : str              — pipeline re-entry point
    resolved_params   : dict[str, Any]  — all answered parameter_key→value pairs
    rephrased_prompt  : str | None      — if user provided a new prompt phrasing
    confirmed         : bool | None     — True/False if a CONFIRM was answered
    target_actor_id   : str | None      — resolved actor if actor_ambiguous
    target_mode_id    : str | None      — resolved mode if mode_ambiguous
    target_field      : str | None      — resolved field if field_ambiguous
    numeric_value     : float | None    — resolved value if value_missing
    """
    resume_point:    str
    resolved_params: dict[str, Any]    = field(default_factory=dict)
    rephrased_prompt: str | None       = None
    confirmed:        bool | None      = None
    target_actor_id:  str | None       = None
    target_mode_id:   str | None       = None
    target_field:     str | None       = None
    numeric_value:    float | None     = None

    @property
    def was_confirmed(self) -> bool:
        return self.confirmed is True

    @property
    def was_rejected(self) -> bool:
        return self.confirmed is False

    def __repr__(self) -> str:
        return (
            f"ClarificationOutcome(resume={self.resume_point!r}, "
            f"params={list(self.resolved_params.keys())})"
        )


# ── Clarification Engine ──────────────────────────────────────────────────────

class ClarificationEngine:
    """
    Orchestrates the clarification loop between the PIL pipeline and
    the builder UI.

    One instance per PIL session (not shared across users).

    Usage
    -----
        engine = ClarificationEngine()

        # When pipeline needs clarification:
        session = engine.create_session(
            envelope     = intent_envelope,
            cgs          = current_cgs,
            resume_point = "pass2_dsl_draft",
            retry_context = {"pass_label": "pass2_dsl_draft", "reasons": [...]}
        )

        # Builder UI loop:
        while not engine.is_session_complete(session.session_id):
            q = engine.get_current_question(session.session_id)
            answer = ui.ask(q)
            ok = engine.submit_answer(session.session_id, answer)
            if not ok:
                error = engine.get_last_error(session.session_id)
                ui.show_error(error)

        # Resume pipeline:
        outcome = engine.apply_answers(session.session_id)
        engine.close_session(session.session_id)
        # use outcome.resume_point, outcome.resolved_params
    """

    def __init__(self) -> None:
        self._sessions:  dict[str, ClarificationSession] = {}
        self._generator: QuestionGenerator               = QuestionGenerator()

    # ── Session management ────────────────────────────────────────────────────

    def create_session(
        self,
        envelope:      IntentEnvelope,
        cgs:           dict[str, Any],
        resume_point:  str                  = "pass1_planning",
        retry_context: dict | None          = None,
        extra_signals: list[AmbiguitySignal] | None = None,
    ) -> ClarificationSession:
        """
        Creates a new ClarificationSession for the given intent.

        Parameters
        ----------
        envelope      : IntentEnvelope    — current intent
        cgs           : dict              — current CGS
        resume_point  : str               — where pipeline resumes after answers
        retry_context : dict | None       — from PILRetryPolicy.summary() on failure
                                            {"pass_label": str, "reasons": list[str]}
        extra_signals : list | None       — additional pre-detected signals

        Returns
        -------
        ClarificationSession

        Raises
        ------
        NothingToClarifyError
            When no ambiguity signals are detected and no retry context given.
        """
        # Cleanup expired sessions lazily
        self._cleanup_expired()

        # Detect signals
        signals: list[AmbiguitySignal] = self._generator.detect_signals(envelope, cgs)

        # Add retry failure signal if provided
        if retry_context:
            signals.insert(0, AmbiguitySignal(
                signal_type = "retry_failure",
                description = f"Pipeline failed on {retry_context.get('pass_label','?')}",
                context     = retry_context,
            ))

        # Add extra signals if provided
        if extra_signals:
            signals.extend(extra_signals)

        if not signals:
            raise NothingToClarifyError(
                "No ambiguity signals detected. "
                "The intent appears unambiguous — clarification is unnecessary."
            )

        # Generate questions
        questions = self._generator.generate(envelope, signals, cgs)

        if not questions:
            raise NothingToClarifyError(
                "Signal detection produced no questions. "
                "Cannot create a clarification session."
            )

        session = ClarificationSession(
            questions    = questions,
            resume_point = resume_point,
        )

        # Evict oldest if at capacity
        if len(self._sessions) >= MAX_CONCURRENT_SESSIONS:
            oldest_id = next(iter(self._sessions))
            del self._sessions[oldest_id]

        self._sessions[session.session_id] = session
        return session

    def create_session_from_signals(
        self,
        signals:       list[AmbiguitySignal],
        envelope:      IntentEnvelope,
        cgs:           dict[str, Any],
        resume_point:  str = "pass1_planning",
    ) -> ClarificationSession:
        """
        Creates a session from pre-built signals (bypasses auto-detection).
        Used when the caller already knows what's ambiguous.
        """
        self._cleanup_expired()

        questions = self._generator.generate(envelope, signals, cgs)
        if not questions:
            raise NothingToClarifyError("No questions generated from the provided signals.")

        session = ClarificationSession(questions=questions, resume_point=resume_point)

        if len(self._sessions) >= MAX_CONCURRENT_SESSIONS:
            oldest_id = next(iter(self._sessions))
            del self._sessions[oldest_id]

        self._sessions[session.session_id] = session
        return session

    def close_session(self, session_id: str) -> None:
        """Discards a session after the pipeline resumes successfully."""
        self._sessions.pop(session_id, None)

    # ── Question interaction ──────────────────────────────────────────────────

    def get_current_question(self, session_id: str) -> ClarificationQuestion | None:
        """Returns the pending question, or None if complete."""
        session = self._get_session(session_id)
        return session.current_question

    def submit_answer(self, session_id: str, raw_answer: str) -> bool:
        """
        Submits an answer to the current question.
        Returns True if accepted, False if invalid.
        """
        session = self._get_session(session_id)
        return session.submit_answer(raw_answer)

    def get_last_error(self, session_id: str) -> str:
        """Returns the last validation error for the session, or ''."""
        session = self._get_session(session_id)
        return session.last_error

    def is_session_complete(self, session_id: str) -> bool:
        """True when all questions have been answered."""
        try:
            session = self._get_session(session_id)
            return session.is_complete
        except (SessionNotFoundError, SessionExpiredError):
            return False

    def get_progress(self, session_id: str) -> str:
        """Returns a human-readable progress string, e.g. '1 of 3'."""
        session = self._get_session(session_id)
        return session.progress

    # ── Outcome assembly ──────────────────────────────────────────────────────

    def apply_answers(self, session_id: str) -> ClarificationOutcome:
        """
        Assembles a ClarificationOutcome from all session answers.

        Call after is_session_complete() returns True.

        Returns
        -------
        ClarificationOutcome
            Carries resume_point and all resolved parameters for pipeline.
        """
        session = self._get_session(session_id)

        if not session.is_complete:
            raise ValueError(
                f"Session '{session_id}' is not yet complete "
                f"({session.remaining_count} questions remaining)."
            )

        params = session.resolved_parameters

        return ClarificationOutcome(
            resume_point     = session.resume_point,
            resolved_params  = params,
            rephrased_prompt = params.get("rephrased_prompt") or params.get("clarified_detail"),
            confirmed        = params.get("confirmed"),
            target_actor_id  = params.get("target_actor_id"),
            target_mode_id   = params.get("target_mode_id"),
            target_field     = params.get("target_field"),
            numeric_value    = (float(params["numeric_value"])
                                if "numeric_value" in params
                                and isinstance(params["numeric_value"], (int, float))
                                else None),
        )

    # ── Session store ─────────────────────────────────────────────────────────

    def _get_session(self, session_id: str) -> ClarificationSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError(session_id)
        if session.is_expired:
            del self._sessions[session_id]
            raise SessionExpiredError(session_id)
        return session

    def _cleanup_expired(self) -> None:
        expired = [sid for sid, s in self._sessions.items() if s.is_expired]
        for sid in expired:
            del self._sessions[sid]

    @property
    def active_session_count(self) -> int:
        return len(self._sessions)