"""
memory_lifecycle_manager.py — MemoryLifecycleManager
======================================================
Manages when memory layers are assembled and updated.

## Lifecycle Rules

    LOAD (called at pipeline start, once per prompt):
        1. Structural layer synced from CGS if CGS hash changed since last sync
           (hash-gated sync avoids redundant re-indexing on repeated calls)
        2. Cached prefix assembled: design + structural + behavioral
           Assembled ONCE per unique CGS hash — result is memoized.
        3. Per-prompt body assembled: session + safety
           Assembled FRESH each call — no memoization.

    UPDATE (called only after successful GDE commit):
        1. Structural layer synced from new proposed_cgs
        2. Session layer records the committed mutation
        3. Safety layer records any warnings that were shown

    CLEAR (called on session end):
        Session and Safety layers cleared.
        Design, Structural, Behavioral layers preserved (persistent).

## Versioned Alongside CGS

    The structural layer is always in sync with the committed CGS hash.
    MemoryLifecycleManager tracks the last CGS hash it synced from.
    If the hash changes (another commit happened), sync is triggered
    automatically on the next LOAD.

## Token Budget

    The lifecycle manager estimates token counts for each assembled
    text block and warns if the total would push the context over budget.
    It does NOT enforce the 8K cap — that is context_budgeter.py's job
    (packages/inference). It only warns.

    Typical sizes:
        cached_prefix_text:  ~200–800 tokens (stable, large games more)
        per_prompt_text:     ~50–200 tokens
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from memory_model import MemoryModel
from session_memory import MutationRecord, FailureRecord


# ── Token warning thresholds ──────────────────────────────────────────────────

_CACHED_TOKEN_WARN  = 1_000    # cached prefix memory > this → warn
_PER_PROMPT_TOKEN_WARN = 400   # per-prompt memory > this → warn


# ── Assembly Result ───────────────────────────────────────────────────────────

@dataclass
class MemoryAssembly:
    """
    Result of one MemoryLifecycleManager.assemble() call.

    Attributes
    ----------
    cached_prefix_text  : str   — layers 1-3, for LLM cached prefix
    per_prompt_text     : str   — layers 4-5, for per-prompt body
    cached_token_est    : int   — estimated tokens for cached prefix text
    per_prompt_token_est: int   — estimated tokens for per-prompt text
    structural_synced   : bool  — True if structural layer was re-synced this call
    warnings            : list[str]  — advisory warnings (e.g. token budget)
    """
    cached_prefix_text:   str
    per_prompt_text:      str
    cached_token_est:     int        = 0
    per_prompt_token_est: int        = 0
    structural_synced:    bool       = False
    warnings:             list[str]  = field(default_factory=list)

    @property
    def total_token_est(self) -> int:
        return self.cached_token_est + self.per_prompt_token_est

    def __repr__(self) -> str:
        sync = " [resynced]" if self.structural_synced else ""
        return (
            f"MemoryAssembly({self.cached_token_est}+{self.per_prompt_token_est}tok"
            f"{sync})"
        )


# ── Memory Lifecycle Manager ──────────────────────────────────────────────────

class MemoryLifecycleManager:
    """
    Manages memory layer assembly and update timing.

    One instance per PIL session. Owns the MemoryModel.

    Usage
    -----
        manager = MemoryLifecycleManager(session_id="s1")

        # At the start of each prompt handling:
        assembly = manager.assemble(current_cgs, cgs_hash)
        # use assembly.cached_prefix_text in LLM prompt prefix
        # use assembly.per_prompt_text in LLM prompt body

        # After successful commit:
        manager.on_commit(mutation_record, new_cgs, new_cgs_hash)

        # After a pipeline failure:
        manager.on_failure(failure_record)

        # At session end:
        manager.on_session_end()
    """

    def __init__(self, session_id: str = "") -> None:
        self._model             = MemoryModel(session_id=session_id)
        self._last_synced_hash  = ""
        self._cached_prefix_cache: dict[str, str] = {}   # cgs_hash → cached text

    @property
    def model(self) -> MemoryModel:
        return self._model

    # ── Assembly (called each prompt) ─────────────────────────────────────────

    def assemble(
        self,
        current_cgs: dict[str, Any],
        cgs_hash:    str = "",
    ) -> MemoryAssembly:
        """
        Assembles cached prefix and per-prompt memory for this call.

        Parameters
        ----------
        current_cgs : dict    — current CGS (for structural sync if hash changed)
        cgs_hash    : str     — CGS hash for memoization and sync gating

        Returns
        -------
        MemoryAssembly
        """
        warnings: list[str] = []
        structural_synced = False

        # ── Structural sync (hash-gated) ──────────────────────────────────────
        if cgs_hash and cgs_hash != self._last_synced_hash:
            self._model.structural.sync_from_cgs(current_cgs)
            self._last_synced_hash = cgs_hash
            # Invalidate cached prefix text — structural changed
            self._cached_prefix_cache.clear()
            structural_synced = True

        # ── Cached prefix (memoized per CGS hash) ─────────────────────────────
        cache_key = cgs_hash or "__no_hash__"
        if cache_key not in self._cached_prefix_cache:
            self._cached_prefix_cache[cache_key] = self._model.cached_prefix_text()
        cached_text = self._cached_prefix_cache[cache_key]

        # ── Per-prompt text (always fresh) ────────────────────────────────────
        per_prompt_text = self._model.per_prompt_text()

        # ── Token estimation ──────────────────────────────────────────────────
        cached_tok    = max(0, len(cached_text)    // 4)
        per_prompt_tok = max(0, len(per_prompt_text) // 4)

        if cached_tok > _CACHED_TOKEN_WARN:
            warnings.append(
                f"Cached memory is large ({cached_tok} tokens). "
                f"Consider pruning design or behavioral memory."
            )
        if per_prompt_tok > _PER_PROMPT_TOKEN_WARN:
            warnings.append(
                f"Per-prompt memory is large ({per_prompt_tok} tokens). "
                f"Session may have too many entries."
            )

        return MemoryAssembly(
            cached_prefix_text   = cached_text,
            per_prompt_text      = per_prompt_text,
            cached_token_est     = cached_tok,
            per_prompt_token_est = per_prompt_tok,
            structural_synced    = structural_synced,
            warnings             = warnings,
        )

    # ── Lifecycle events ──────────────────────────────────────────────────────

    def on_prompt(self, prompt: str) -> None:
        """Call at the start of each user prompt processing."""
        self._model.session.record_prompt(prompt)
        self._model.advance_turn()

    def on_commit(
        self,
        mutation:    MutationRecord,
        new_cgs:     dict[str, Any],
        new_cgs_hash: str = "",
    ) -> None:
        """
        Called after a successful GDE commit.
        Updates structural layer and records the mutation in session memory.
        """
        self._model.session.record_mutation(mutation)

        # Sync structural from new CGS
        self._model.structural.sync_from_cgs(new_cgs)
        self._last_synced_hash = new_cgs_hash
        self._cached_prefix_cache.clear()

    def on_failure(self, failure: FailureRecord) -> None:
        """Called when the pipeline fails to commit a mutation."""
        self._model.session.record_failure(failure)

    def on_safety_block(
        self,
        guard_name: str,
        path:       str,
        reason:     str,
    ) -> None:
        """Called when SafetyScopeGuard blocks a mutation."""
        self._model.safety.record_block(guard_name, path, reason)

    def on_risk_confirmation(
        self,
        guard_name:  str,
        description: str,
        confirmed:   bool,
    ) -> None:
        """Called when the designer responds to a risk warning."""
        self._model.safety.record_risk_confirmation(guard_name, description, confirmed)

    def on_session_end(self) -> None:
        """Called when the builder session ends. Clears per-session layers."""
        self._model.clear_session_layers()
        self._cached_prefix_cache.clear()

    # ── Direct memory access (for initial setup) ──────────────────────────────

    def set_game_vision(self, vision: str) -> None:
        self._model.design.set_game_vision(vision)
        self._cached_prefix_cache.clear()

    def set_difficulty_philosophy(self, philosophy: str) -> None:
        self._model.design.set_difficulty_philosophy(philosophy)
        self._cached_prefix_cache.clear()

    def add_core_constraint(self, constraint: str) -> str:
        eid = self._model.design.add_core_constraint(constraint)
        self._cached_prefix_cache.clear()
        return eid

    def add_pacing_concern(self, concern: str) -> str:
        eid = self._model.behavioral.add_pacing_concern(concern)
        self._cached_prefix_cache.clear()
        return eid

    def add_broken_moment(self, description: str) -> str:
        eid = self._model.behavioral.add_broken_moment(description)
        self._cached_prefix_cache.clear()
        return eid

    def __repr__(self) -> str:
        return (
            f"MemoryLifecycleManager("
            f"session={self._model._session_id!r}, "
            f"turn={self._model.turn_index}, "
            f"synced_hash={self._last_synced_hash[:8]!r})"
        )