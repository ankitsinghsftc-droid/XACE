"""
history_manager.py — HistoryManager
=====================================
Manages the prompt history, mutation log, and session lifecycle.

HistoryManager is the single interface for all history operations in the
PIL pipeline. Every component that needs to read or write history goes
through HistoryManager — never directly to SessionStore.

## What HistoryManager Does

    Recording (called by pipeline coordinator):
        on_prompt(prompt, turn_index)
        on_commit(mutation_summary, cgs_hash_before, cgs_hash_after, turn_index)
        on_clarification(question, answer, parameter_key, resume_point, turn_index)
        on_failure(prompt, failure_type, reason, pass_label, turn_index)
        on_cgs_snapshot(cgs_hash, schema_version, turn_index)

    Retrieval (called by ContextAssembler / ClarificationEngine):
        for_context(n_prompts, n_mutations) → HistoryContext
        recent_failures(n) → list[PipelineFailure]
        was_this_prompt_tried_before(prompt) → bool
        get_undo_target(turn_index) → str | None (CGS hash before that turn)

    Session lifecycle:
        close_session() → SessionSummary

## HistoryContext

    Compact summary of recent history for injection into LLM context.
    Produces a short text block (≤300 chars) suitable for per-prompt body.
    Does NOT go in the cached prefix (history changes every turn).

## Undo Support

    get_undo_target(turn_index) returns the CGS hash from BEFORE that
    turn's mutation, enabling the "undo last change" feature.
    The actual rollback is performed by GDE's RollbackManager (Phase 13.9).
    HistoryManager only provides the target hash.

## Deduplication

    was_this_prompt_tried_before() checks the last 10 prompts for
    near-duplicates (case-insensitive, stripped). If a prompt has been
    tried more than once recently (without a successful mutation in between),
    the pipeline routes to ClarificationEngine instead of retrying.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from session_store import (
    SessionStore,
    PromptRecord, MutationSummary, ClarificationRecord,
    PipelineFailure, CGSSnapshot,
)


# ── History Context ───────────────────────────────────────────────────────────

@dataclass
class HistoryContext:
    """
    Compact history for LLM per-prompt body injection.

    Attributes
    ----------
    recent_prompt_texts  : list[str]          — last N prompt strings
    recent_mutation_summaries : list[str]     — last N mutation one-liners
    recent_failure_reasons: list[str]         — last N failure reasons
    as_text              : str                — formatted for LLM prompt body
    """
    recent_prompt_texts:       list[str] = field(default_factory=list)
    recent_mutation_summaries: list[str] = field(default_factory=list)
    recent_failure_reasons:    list[str] = field(default_factory=list)

    @property
    def as_text(self) -> str:
        if not any([self.recent_prompt_texts,
                    self.recent_mutation_summaries,
                    self.recent_failure_reasons]):
            return ""
        parts = ["=== RECENT HISTORY ==="]
        if self.recent_prompt_texts:
            parts.append(
                "Recent prompts: "
                + " | ".join(f'"{p}"' for p in self.recent_prompt_texts[-3:])
            )
        if self.recent_mutation_summaries:
            parts.append("Recent mutations:")
            for m in self.recent_mutation_summaries[-2:]:
                parts.append(f"  - {m}")
        if self.recent_failure_reasons:
            parts.append(
                f"Recent failures: "
                + "; ".join(self.recent_failure_reasons[-2:])
            )
        parts.append("=== END HISTORY ===")
        return "\n".join(parts)


# ── Session Summary ───────────────────────────────────────────────────────────

@dataclass
class SessionSummary:
    """
    Summary produced when a session is closed.

    Attributes
    ----------
    session_id         : str
    total_turns        : int
    total_mutations    : int
    total_failures     : int
    failure_rate       : float
    version_bumps      : dict[str, int]   — {"patch": N, "minor": M, "major": K}
    final_cgs_hash     : str
    most_failed_type   : str | None       — most common failure_type, if any
    """
    session_id:       str
    total_turns:      int
    total_mutations:  int
    total_failures:   int
    failure_rate:     float
    version_bumps:    dict[str, int]
    final_cgs_hash:   str
    most_failed_type: str | None = None

    def __repr__(self) -> str:
        return (
            f"SessionSummary(mutations={self.total_mutations}, "
            f"failures={self.total_failures}, "
            f"rate={self.failure_rate:.1%})"
        )


# ── History Manager ───────────────────────────────────────────────────────────

class HistoryManager:
    """
    Single interface for all history operations.

    One instance per PIL session.

    Usage
    -----
        hm = HistoryManager(session_id="s1")

        # On each user prompt:
        hm.on_prompt("make the zombie faster", turn_index=1)

        # On successful commit:
        hm.on_commit(MutationSummary(...), turn_index=1)

        # Before retrying a failed prompt:
        if hm.was_this_prompt_tried_before("make zombie faster"):
            route_to_clarification()

        # For LLM context:
        ctx = hm.for_context(n_prompts=3, n_mutations=2)
        prompt_body += ctx.as_text

        # On session end:
        summary = hm.close_session(final_turn=10)
    """

    def __init__(self, session_id: str = "") -> None:
        self._session_id = session_id
        self._store      = SessionStore(session_id=session_id)
        self._turn_index = 0

    @property
    def store(self) -> SessionStore:
        """Direct access to the underlying store (for testing and inspection)."""
        return self._store

    @property
    def current_turn(self) -> int:
        return self._turn_index

    # ── Recording ─────────────────────────────────────────────────────────────

    def on_prompt(self, prompt: str, turn_index: int | None = None) -> None:
        """Records a user prompt. Advances internal turn index."""
        if turn_index is not None:
            self._turn_index = turn_index
        else:
            self._turn_index += 1

        self._store.add_prompt(PromptRecord(
            prompt     = prompt.strip()[:200],
            turn_index = self._turn_index,
            session_id = self._session_id,
        ))

    def on_commit(
        self,
        summary:         str,
        schema_delta:    str,
        risk_level:      str,
        confidence:      float,
        version_bump:    str,
        cgs_hash_before: str,
        cgs_hash_after:  str,
        turn_index:      int | None        = None,
        affected_systems: list[str] | None = None,
    ) -> None:
        """Records a successful mutation commit."""
        turn = turn_index if turn_index is not None else self._turn_index

        self._store.add_mutation(MutationSummary(
            summary          = summary[:200],
            schema_delta     = schema_delta,
            risk_level       = risk_level,
            confidence_score = confidence,
            version_bump     = version_bump,
            cgs_hash_before  = cgs_hash_before,
            cgs_hash_after   = cgs_hash_after,
            turn_index       = turn,
            affected_systems = affected_systems or [],
        ))

        self._store.add_cgs_snapshot(CGSSnapshot(
            cgs_hash       = cgs_hash_after,
            schema_version = "",   # filled in by MemoryLifecycleManager
            turn_index     = turn,
            mutation_count = self._store.mutation_count,
        ))

    def on_clarification(
        self,
        question:      str,
        answer:        str,
        parameter_key: str,
        resume_point:  str,
        turn_index:    int | None = None,
    ) -> None:
        """Records one completed clarification Q&A pair."""
        turn = turn_index if turn_index is not None else self._turn_index
        self._store.add_clarification(ClarificationRecord(
            question      = question[:200],
            answer        = answer[:200],
            parameter_key = parameter_key,
            resume_point  = resume_point,
            turn_index    = turn,
        ))

    def on_failure(
        self,
        prompt:       str,
        failure_type: str,
        reason:       str,
        pass_label:   str       = "",
        turn_index:   int | None = None,
    ) -> None:
        """Records a pipeline failure."""
        turn = turn_index if turn_index is not None else self._turn_index
        self._store.add_failure(PipelineFailure(
            prompt       = prompt.strip()[:150],
            failure_type = failure_type,
            reason       = reason[:200],
            pass_label   = pass_label,
            turn_index   = turn,
        ))

    def on_cgs_snapshot(
        self,
        cgs_hash:       str,
        schema_version: str = "",
        turn_index:     int | None = None,
    ) -> None:
        """Records a CGS hash checkpoint."""
        turn = turn_index if turn_index is not None else self._turn_index
        self._store.add_cgs_snapshot(CGSSnapshot(
            cgs_hash       = cgs_hash,
            schema_version = schema_version,
            turn_index     = turn,
            mutation_count = self._store.mutation_count,
        ))

    # ── Retrieval ─────────────────────────────────────────────────────────────

    def for_context(
        self,
        n_prompts:   int = 3,
        n_mutations: int = 2,
        n_failures:  int = 2,
    ) -> HistoryContext:
        """
        Returns a compact HistoryContext for LLM per-prompt body injection.
        """
        return HistoryContext(
            recent_prompt_texts = [
                r.prompt for r in self._store.recent_prompts(n_prompts)
            ],
            recent_mutation_summaries = [
                r.summary for r in self._store.recent_mutations(n_mutations)
            ],
            recent_failure_reasons = [
                f"{r.failure_type}: {r.reason[:60]}"
                for r in self._store.recent_failures(n_failures)
            ],
        )

    def recent_failures(self, n: int = 5) -> list[PipelineFailure]:
        return self._store.recent_failures(n)

    def was_this_prompt_tried_before(self, prompt: str) -> bool:
        """
        Returns True if this prompt (case-insensitive) has been tried
        in the last 10 turns without a successful mutation in between.
        """
        normalised     = prompt.strip().lower()
        recent_prompts = self._store.recent_prompts(n=10)
        last_mutation_turn = (
            self._store.recent_mutations(n=1)[0].turn_index
            if self._store.mutation_count > 0 else -1
        )

        for rec in reversed(recent_prompts[:-1]):   # exclude the current prompt
            if rec.turn_index <= last_mutation_turn:
                break   # a successful mutation happened — reset context
            if rec.prompt.lower() == normalised:
                return True
        return False

    def get_undo_target(self, turn_index: int) -> str | None:
        """
        Returns the CGS hash from before the mutation at the given turn.
        Used by the "undo" feature to identify the rollback target.
        Returns None if no mutation exists at that turn.
        """
        mutations = self._store.mutations_between(turn_index, turn_index)
        if not mutations:
            return None
        return mutations[0].cgs_hash_before

    def get_mutation_at_turn(self, turn_index: int) -> MutationSummary | None:
        """Returns the mutation committed at a specific turn, or None."""
        mutations = self._store.mutations_between(turn_index, turn_index)
        return mutations[0] if mutations else None

    def find_failures_by_type(self, failure_type: str) -> list[PipelineFailure]:
        return self._store.find_failures_by_type(failure_type)

    # ── Session lifecycle ─────────────────────────────────────────────────────

    def close_session(self, final_turn: int | None = None) -> SessionSummary:
        """
        Closes the session and returns a summary.
        After calling this, the store is cleared.
        """
        total_turns = final_turn if final_turn is not None else self._turn_index
        stats       = self._store.stats()

        # Most common failure type
        failure_types: dict[str, int] = {}
        for f in self._store.recent_failures(n=MAX_FAILURES_FOR_ANALYSIS):
            failure_types[f.failure_type] = failure_types.get(f.failure_type, 0) + 1
        most_failed = (max(failure_types, key=lambda k: failure_types[k])
                       if failure_types else None)

        summary = SessionSummary(
            session_id       = self._session_id,
            total_turns      = total_turns,
            total_mutations  = stats["mutation_count"],
            total_failures   = stats["failure_count"],
            failure_rate     = stats["failure_rate"],
            version_bumps    = stats["version_bumps"],
            final_cgs_hash   = stats["latest_cgs_hash"],
            most_failed_type = most_failed,
        )

        self._store.clear()
        self._turn_index = 0
        return summary

    def __repr__(self) -> str:
        return (
            f"HistoryManager(session={self._session_id!r}, "
            f"turn={self._turn_index}, "
            f"mutations={self._store.mutation_count})"
        )


MAX_FAILURES_FOR_ANALYSIS = 30