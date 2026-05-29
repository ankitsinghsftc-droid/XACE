"""
session_store.py — SessionStore
=================================
Persistent-within-session data store for history_manager.

SessionStore is the data layer. HistoryManager is the logic layer.
They are separated so the store can be tested independently and
potentially serialized to disk in Phase 17 (standalone compiler).

## What SessionStore Holds

    prompts         : ordered log of user prompt strings + turn index
    mutations       : ordered log of committed MutationSummary records
    clarifications  : ordered log of ClarificationRecord (question + answer)
    failures        : ordered log of PipelineFailure records
    cgs_snapshots   : lightweight CGS hash log (hash + version + turn)

## Retrieval Patterns

    Most recent N items (for LLM context window):
        store.recent_prompts(n=5)
        store.recent_mutations(n=3)

    By turn range:
        store.mutations_between(turn_start=0, turn_end=10)

    Search:
        store.find_failures_by_type("parse_error")
        store.find_mutations_by_delta("structural_add")

## Capacity Limits

    Each collection has a max capacity. When full, oldest entry is evicted
    (FIFO ring-buffer semantics). Limits are generous — history is cheap.

    MAX_PROMPTS:        50
    MAX_MUTATIONS:      50
    MAX_CLARIFICATIONS: 100
    MAX_FAILURES:       30
    MAX_CGS_SNAPSHOTS:  100
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


# ── Capacity limits ───────────────────────────────────────────────────────────

MAX_PROMPTS        = 50
MAX_MUTATIONS      = 50
MAX_CLARIFICATIONS = 100
MAX_FAILURES       = 30
MAX_CGS_SNAPSHOTS  = 100


# ── Record types ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PromptRecord:
    """One user prompt."""
    prompt:     str
    turn_index: int
    timestamp:  float = field(default_factory=time.time)
    session_id: str   = ""


@dataclass(frozen=True)
class MutationSummary:
    """One committed mutation, logged for history."""
    summary:          str     # human-readable description
    schema_delta:     str     # "value_mutation" | "structural_add" | etc.
    risk_level:       str     # "low" | "medium" | "high"
    confidence_score: float
    version_bump:     str     # "patch" | "minor" | "major"
    cgs_hash_before:  str
    cgs_hash_after:   str
    turn_index:       int
    affected_systems: list[str] = field(default_factory=list)
    timestamp:        float     = field(default_factory=time.time)


@dataclass(frozen=True)
class ClarificationRecord:
    """One completed clarification Q&A pair."""
    question:      str
    answer:        str
    parameter_key: str
    resume_point:  str
    turn_index:    int
    timestamp:     float = field(default_factory=time.time)


@dataclass(frozen=True)
class PipelineFailure:
    """One pipeline failure."""
    prompt:        str
    failure_type:  str   # "parse_error"|"validation"|"safety_block"|"retry_exhausted"|"unknown"
    reason:        str
    pass_label:    str   # which pass failed ("pass2_dsl_draft" etc.)
    turn_index:    int
    timestamp:     float = field(default_factory=time.time)


@dataclass(frozen=True)
class CGSSnapshot:
    """Lightweight CGS version record."""
    cgs_hash:       str
    schema_version: str
    turn_index:     int
    mutation_count: int   # how many mutations have been applied since start
    timestamp:      float = field(default_factory=time.time)


# ── Session Store ─────────────────────────────────────────────────────────────

class SessionStore:
    """
    FIFO ring-buffer store for one builder session's history.

    Not thread-safe. One instance per session.

    Usage
    -----
        store = SessionStore(session_id="s1")
        store.add_prompt(PromptRecord(prompt="make it faster", turn_index=1))
        store.add_mutation(MutationSummary(...))
        store.recent_prompts(n=3)
    """

    def __init__(self, session_id: str = "") -> None:
        self._session_id    = session_id
        self._prompts:        list[PromptRecord]       = []
        self._mutations:      list[MutationSummary]    = []
        self._clarifications: list[ClarificationRecord] = []
        self._failures:       list[PipelineFailure]    = []
        self._cgs_snapshots:  list[CGSSnapshot]        = []

    # ── Add records ───────────────────────────────────────────────────────────

    def add_prompt(self, record: PromptRecord) -> None:
        self._append(self._prompts, record, MAX_PROMPTS)

    def add_mutation(self, record: MutationSummary) -> None:
        self._append(self._mutations, record, MAX_MUTATIONS)

    def add_clarification(self, record: ClarificationRecord) -> None:
        self._append(self._clarifications, record, MAX_CLARIFICATIONS)

    def add_failure(self, record: PipelineFailure) -> None:
        self._append(self._failures, record, MAX_FAILURES)

    def add_cgs_snapshot(self, record: CGSSnapshot) -> None:
        self._append(self._cgs_snapshots, record, MAX_CGS_SNAPSHOTS)

    # ── Retrieval: most-recent ────────────────────────────────────────────────

    def recent_prompts(self, n: int = 5) -> list[PromptRecord]:
        return list(self._prompts[-n:])

    def recent_mutations(self, n: int = 5) -> list[MutationSummary]:
        return list(self._mutations[-n:])

    def recent_clarifications(self, n: int = 5) -> list[ClarificationRecord]:
        return list(self._clarifications[-n:])

    def recent_failures(self, n: int = 5) -> list[PipelineFailure]:
        return list(self._failures[-n:])

    def recent_cgs_snapshots(self, n: int = 5) -> list[CGSSnapshot]:
        return list(self._cgs_snapshots[-n:])

    # ── Retrieval: by turn range ──────────────────────────────────────────────

    def mutations_between(self, turn_start: int, turn_end: int) -> list[MutationSummary]:
        return [m for m in self._mutations
                if turn_start <= m.turn_index <= turn_end]

    def prompts_between(self, turn_start: int, turn_end: int) -> list[PromptRecord]:
        return [p for p in self._prompts
                if turn_start <= p.turn_index <= turn_end]

    # ── Retrieval: search ─────────────────────────────────────────────────────

    def find_failures_by_type(self, failure_type: str) -> list[PipelineFailure]:
        return [f for f in self._failures if f.failure_type == failure_type]

    def find_mutations_by_delta(self, schema_delta: str) -> list[MutationSummary]:
        return [m for m in self._mutations if m.schema_delta == schema_delta]

    def find_prompt_at_turn(self, turn_index: int) -> PromptRecord | None:
        for p in reversed(self._prompts):
            if p.turn_index == turn_index:
                return p
        return None

    def cgs_hash_at_turn(self, turn_index: int) -> str | None:
        """Returns the most recent CGS hash at or before the given turn."""
        for snap in reversed(self._cgs_snapshots):
            if snap.turn_index <= turn_index:
                return snap.cgs_hash
        return None

    # ── Statistics ────────────────────────────────────────────────────────────

    @property
    def prompt_count(self) -> int:
        return len(self._prompts)

    @property
    def mutation_count(self) -> int:
        return len(self._mutations)

    @property
    def failure_count(self) -> int:
        return len(self._failures)

    @property
    def clarification_count(self) -> int:
        return len(self._clarifications)

    @property
    def failure_rate(self) -> float:
        """Ratio of failures to total pipeline runs (prompts)."""
        total = self.prompt_count
        return self.failure_count / total if total > 0 else 0.0

    @property
    def latest_cgs_hash(self) -> str:
        return self._cgs_snapshots[-1].cgs_hash if self._cgs_snapshots else ""

    @property
    def total_version_bumps(self) -> dict[str, int]:
        """Count of each version bump type across all mutations."""
        counts: dict[str, int] = {"patch": 0, "minor": 0, "major": 0}
        for m in self._mutations:
            if m.version_bump in counts:
                counts[m.version_bump] += 1
        return counts

    def stats(self) -> dict:
        return {
            "session_id":          self._session_id,
            "prompt_count":        self.prompt_count,
            "mutation_count":      self.mutation_count,
            "failure_count":       self.failure_count,
            "clarification_count": self.clarification_count,
            "failure_rate":        round(self.failure_rate, 3),
            "latest_cgs_hash":     self.latest_cgs_hash[:8],
            "version_bumps":       self.total_version_bumps,
        }

    # ── Clear ─────────────────────────────────────────────────────────────────

    def clear(self) -> None:
        """Clears all records. Called on session end."""
        self._prompts.clear()
        self._mutations.clear()
        self._clarifications.clear()
        self._failures.clear()
        self._cgs_snapshots.clear()

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _append(collection: list, record: Any, max_size: int) -> None:
        """Appends to collection, evicting oldest entry when at capacity."""
        if len(collection) >= max_size:
            collection.pop(0)
        collection.append(record)

    def __repr__(self) -> str:
        return (
            f"SessionStore(session={self._session_id!r}, "
            f"prompts={self.prompt_count}, "
            f"mutations={self.mutation_count}, "
            f"failures={self.failure_count})"
        )