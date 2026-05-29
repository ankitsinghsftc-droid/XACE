"""
session_memory.py — SessionMemory
====================================
Layer 4 of the 5-layer memory model. PER-PROMPT BODY.

Short-term working memory for the current conversation. Records what
has happened in this session so the LLM can reference recent context
without the designer having to repeat themselves.

## Contents

    recent_prompts    : Last N user prompts (N=5 default)
    recent_mutations  : Last N committed mutation summaries
    active_clarifications: Pending clarification sessions
    recent_failures   : Last N pipeline failures and their reasons
    turn_context      : What the designer is "working on" right now

## IN PER-PROMPT BODY (II9)

    Session memory changes every turn — it would defeat caching to put
    it in the prefix. Each call gets a fresh session context block.

## Cleared on Session End

    SessionMemory.clear() is called when the builder session ends or
    times out. Session-local facts are not persisted to disk.

## Max Entries

    Kept deliberately small to respect the 8K dynamic token cap:
        recent_prompts:   5
        recent_mutations: 5
        recent_failures:  3
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "memory"))
from memory_store import MemoryStore, MemoryLayer

MAX_RECENT_PROMPTS    = 5
MAX_RECENT_MUTATIONS  = 5
MAX_RECENT_FAILURES   = 3


@dataclass
class MutationRecord:
    """Brief record of one committed mutation."""
    summary:         str
    schema_delta:    str
    risk_level:      str
    turn_index:      int
    cgs_hash_after:  str = ""


@dataclass
class FailureRecord:
    """Record of one pipeline failure."""
    prompt:       str
    failure_type: str   # "parse_error" | "validation" | "safety_block" | "retry_exhausted"
    reason:       str
    turn_index:   int


class SessionMemory:
    """
    Manages the short-term session working memory.

    Usage
    -----
        sm = SessionMemory(store)
        sm.record_prompt("make the zombie faster")
        sm.record_mutation(MutationRecord(...))
        text = sm.to_body_text()
    """

    def __init__(self, store: MemoryStore) -> None:
        self._store           = store
        self._recent_prompts:    list[str]           = []
        self._recent_mutations:  list[MutationRecord] = []
        self._recent_failures:   list[FailureRecord]  = []
        self._turn_context:      str                  = ""

    # ── Recording ─────────────────────────────────────────────────────────────

    def record_prompt(self, prompt: str) -> None:
        """Records a user prompt at the current turn."""
        self._recent_prompts.append(prompt.strip()[:200])
        if len(self._recent_prompts) > MAX_RECENT_PROMPTS:
            self._recent_prompts.pop(0)

        self._store.add(
            layer           = MemoryLayer.SESSION,
            content         = f"User: {prompt.strip()[:150]}",
            relevance_score = 0.80,
            tags            = {"prompt", "session"},
            metadata        = {"kind": "user_prompt"},
        )

    def record_mutation(self, mutation: MutationRecord) -> None:
        """Records a successful mutation commitment."""
        self._recent_mutations.append(mutation)
        if len(self._recent_mutations) > MAX_RECENT_MUTATIONS:
            self._recent_mutations.pop(0)

        self._store.add(
            layer           = MemoryLayer.SESSION,
            content         = (
                f"Committed [{mutation.schema_delta}]: {mutation.summary} "
                f"(risk={mutation.risk_level})"
            ),
            relevance_score = 0.75,
            tags            = {"mutation", "session", mutation.schema_delta},
            metadata        = {"kind": "mutation", "turn": mutation.turn_index},
        )

    def record_failure(self, failure: FailureRecord) -> None:
        """Records a pipeline failure."""
        self._recent_failures.append(failure)
        if len(self._recent_failures) > MAX_RECENT_FAILURES:
            self._recent_failures.pop(0)

        self._store.add(
            layer           = MemoryLayer.SESSION,
            content         = (
                f"Failed [{failure.failure_type}] on prompt "
                f"'{failure.prompt[:60]}': {failure.reason[:100]}"
            ),
            relevance_score = 0.85,   # failures are important context
            tags            = {"failure", "session", failure.failure_type},
            metadata        = {"kind": "failure", "turn": failure.turn_index},
        )

    def set_turn_context(self, context: str) -> None:
        """Sets what the designer is currently working on."""
        self._turn_context = context.strip()[:200]

    # ── Retrieval ─────────────────────────────────────────────────────────────

    @property
    def recent_prompts(self) -> list[str]:
        return list(self._recent_prompts)

    @property
    def recent_mutations(self) -> list[MutationRecord]:
        return list(self._recent_mutations)

    @property
    def recent_failures(self) -> list[FailureRecord]:
        return list(self._recent_failures)

    @property
    def turn_context(self) -> str:
        return self._turn_context

    @property
    def last_prompt(self) -> str | None:
        return self._recent_prompts[-1] if self._recent_prompts else None

    @property
    def last_mutation(self) -> MutationRecord | None:
        return self._recent_mutations[-1] if self._recent_mutations else None

    def has_recent_failure(self, failure_type: str) -> bool:
        return any(f.failure_type == failure_type for f in self._recent_failures)

    # ── Clear ─────────────────────────────────────────────────────────────────

    def clear(self) -> None:
        """Clears session memory. Called on session end."""
        self._store.clear_layer(MemoryLayer.SESSION)
        self._recent_prompts.clear()
        self._recent_mutations.clear()
        self._recent_failures.clear()
        self._turn_context = ""

    # ── Body text ─────────────────────────────────────────────────────────────

    def to_body_text(self) -> str:
        """Returns session memory as formatted text for per-prompt body."""
        parts = ["=== SESSION CONTEXT ==="]

        if self._turn_context:
            parts.append(f"Current focus: {self._turn_context}")

        if self._recent_prompts:
            recent = self._recent_prompts[-3:]   # last 3 only
            parts.append(f"Recent prompts: {' | '.join(repr(p) for p in recent)}")

        if self._recent_mutations:
            last = self._recent_mutations[-2:]   # last 2
            parts.append("Recent mutations:")
            for m in last:
                parts.append(f"  - {m.summary[:80]}")

        if self._recent_failures:
            parts.append(f"Recent failures ({len(self._recent_failures)}):")
            for f in self._recent_failures[-2:]:
                parts.append(f"  - [{f.failure_type}] {f.reason[:60]}")

        parts.append("=== END SESSION CONTEXT ===")
        return "\n".join(parts)

    @property
    def entry_count(self) -> int:
        return self._store.count(MemoryLayer.SESSION)