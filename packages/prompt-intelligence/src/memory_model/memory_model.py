"""
memory_model.py — MemoryModel
================================
Unified interface for all 5 memory layers.

MemoryModel owns one MemoryStore and instantiates each of the 5 domain
layers as views into it. Callers interact with the MemoryModel rather
than individual layers, using:
    memory_model.design     → DesignMemory
    memory_model.structural → StructuralMemory
    memory_model.behavioral → BehavioralMemory
    memory_model.session    → SessionMemory
    memory_model.safety     → SafetyMemory

Memory influences reasoning ONLY — it is never written to the runtime
or the CGS directly. It is injected into the LLMContextPacket via
MemoryLifecycleManager and appears as text in the LLM prompt.

## II9 Routing (enforced here)

    cached_prefix_text()  → layers 1-3 (Design, Structural, Behavioral)
    per_prompt_text()     → layers 4-5 (Session, Safety)

Both are called by MemoryLifecycleManager to assemble the context.

## Session Lifecycle

    One MemoryModel per builder session. Created at session start,
    discarded at session end. The MemoryStore backing it can optionally
    be serialized to disk by a future SessionPersistenceManager.
"""

from __future__ import annotations

from typing import Any

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "memory"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from memory_store import MemoryStore
from design_memory import DesignMemory
from structural_memory import StructuralMemory
from behavioral_memory import BehavioralMemory
from session_memory import SessionMemory, MutationRecord, FailureRecord
from safety_memory import SafetyMemory


class MemoryModel:
    """
    Unified 5-layer memory model for one builder session.

    Usage
    -----
        model = MemoryModel(session_id="s1")

        # Design layer
        model.design.set_game_vision("Top-down zombie survival.")
        model.design.add_core_constraint("Player always has agency.")

        # Structural layer (sync from CGS after each commit)
        model.structural.sync_from_cgs(current_cgs)

        # Behavioral layer
        model.behavioral.add_pacing_concern("Early game is too fast.")

        # Session layer (updated each turn)
        model.session.record_prompt("make the zombie faster")
        model.session.advance_turn()

        # Safety layer
        model.safety.record_block("scope_boundary", "metadata.cgs_hash", "forbidden")

        # For LLM context assembly
        cached_text    = model.cached_prefix_text()
        per_prompt_text = model.per_prompt_text()
    """

    def __init__(self, session_id: str = "", max_entries: dict | None = None) -> None:
        self._session_id = session_id
        self._store      = MemoryStore(session_id=session_id, max_entries=max_entries)

        # Instantiate each layer as a view into the shared store
        self.design     = DesignMemory(self._store)
        self.structural = StructuralMemory(self._store)
        self.behavioral = BehavioralMemory(self._store)
        self.session    = SessionMemory(self._store)
        self.safety     = SafetyMemory(self._store)

    # ── II9 Text Assembly ─────────────────────────────────────────────────────

    def cached_prefix_text(self) -> str:
        """
        Returns all cached-prefix memory (layers 1-3) as a single text block.
        This text goes into the LLM cached prefix via prompt_cache.py.
        """
        parts: list[str] = []

        design_text = self.design.to_prefix_text()
        if self.design.entry_count > 0:
            parts.append(design_text)

        structural_text = self.structural.to_prefix_text()
        if self.structural.entry_count > 0:
            parts.append(structural_text)

        behavioral_text = self.behavioral.to_prefix_text()
        if self.behavioral.entry_count > 0:
            parts.append(behavioral_text)

        return "\n\n".join(parts) if parts else ""

    def per_prompt_text(self) -> str:
        """
        Returns all per-prompt memory (layers 4-5) as a single text block.
        This text goes into the per-prompt body of the LLM call.
        """
        parts: list[str] = []

        session_text = self.session.to_body_text()
        if self.session.entry_count > 0:
            parts.append(session_text)

        safety_text = self.safety.to_body_text()
        if self.safety.entry_count > 0:
            parts.append(safety_text)

        return "\n\n".join(parts) if parts else ""

    # ── Turn management ───────────────────────────────────────────────────────

    def advance_turn(self) -> int:
        """Advances the session turn index. Call once per user prompt."""
        return self._store.advance_turn()

    @property
    def turn_index(self) -> int:
        return self._store.turn_index

    # ── Statistics ────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        base = self._store.stats()
        base["session_id"] = self._session_id
        return base

    def total_entries(self) -> int:
        return self._store.count()

    # ── Session reset ─────────────────────────────────────────────────────────

    def clear_session_layers(self) -> None:
        """Clears layers 4-5 (Session + Safety). Called on session end."""
        self.session.clear()
        self.safety.clear()

    def __repr__(self) -> str:
        return (
            f"MemoryModel(session={self._session_id!r}, "
            f"turn={self.turn_index}, "
            f"entries={self.total_entries()})"
        )