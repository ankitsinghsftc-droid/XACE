"""
behavioral_memory.py — BehavioralMemory
=========================================
Layer 3 of the 5-layer memory model. CACHED PREFIX.

Tracks player-observable behavioral patterns the designer has identified:
pacing concerns, known broken moments, intended feel, and emergent
behaviors that have been noticed during playtesting.

## Contents

    pacing_concerns   : Moments where the game feels too slow/fast
    broken_moments    : Specific situations that feel wrong
    intended_patterns : What the designer wants the game to feel like
    emergent_notes    : Unintended behaviors the designer has accepted or wants fixed

## Examples

    Pacing: "Zombie chase feels too fast in first 30 seconds — player overwhelmed"
    Broken: "When zombie reaches player, damage is applied twice (stacking bug)"
    Intended: "Player should feel constant pressure, never safe for more than 5s"
    Emergent: "Players found that hiding behind initial spawn point skips all zombies"

## IN CACHED PREFIX (II9)

    Behavioral memory is cached because playtesting insights are stable
    within a design session. They don't change mid-pipeline.
"""

from __future__ import annotations

from typing import Any

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "memory"))
from memory_store import MemoryStore, MemoryLayer


class BehavioralMemory:
    """
    Tracks player-observable game behavior patterns.

    Usage
    -----
        bm = BehavioralMemory(store)
        bm.add_pacing_concern("Zombie speed makes early game feel unwinnable.")
        bm.add_intended_pattern("Player should feel constant pressure.")
        prefix = bm.to_prefix_text()
    """

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    # ── Adders ────────────────────────────────────────────────────────────────

    def add_pacing_concern(self, concern: str, tags: set[str] | None = None) -> str:
        entry = self._store.add(
            layer           = MemoryLayer.BEHAVIORAL,
            content         = f"PACING: {concern.strip()}",
            relevance_score = 0.80,
            tags            = (tags or set()) | {"pacing", "behavioral"},
            metadata        = {"kind": "pacing_concern"},
        )
        return entry.entry_id

    def add_broken_moment(self, description: str, tags: set[str] | None = None) -> str:
        entry = self._store.add(
            layer           = MemoryLayer.BEHAVIORAL,
            content         = f"BROKEN: {description.strip()}",
            relevance_score = 0.90,   # high relevance — broken moments must be fixed
            tags            = (tags or set()) | {"broken", "behavioral"},
            metadata        = {"kind": "broken_moment"},
        )
        return entry.entry_id

    def add_intended_pattern(self, pattern: str, tags: set[str] | None = None) -> str:
        entry = self._store.add(
            layer           = MemoryLayer.BEHAVIORAL,
            content         = f"INTENDED: {pattern.strip()}",
            relevance_score = 0.85,
            tags            = (tags or set()) | {"intended", "behavioral"},
            metadata        = {"kind": "intended_pattern"},
        )
        return entry.entry_id

    def add_emergent_note(self, note: str, accepted: bool = False,
                           tags: set[str] | None = None) -> str:
        status = "ACCEPTED" if accepted else "NEEDS FIX"
        entry = self._store.add(
            layer           = MemoryLayer.BEHAVIORAL,
            content         = f"EMERGENT[{status}]: {note.strip()}",
            relevance_score = 0.70,
            tags            = (tags or set()) | {"emergent", "behavioral"},
            metadata        = {"kind": "emergent_note", "accepted": accepted},
        )
        return entry.entry_id

    def remove(self, entry_id: str) -> bool:
        return self._store.remove(entry_id) is not None

    # ── Retrieval ─────────────────────────────────────────────────────────────

    def all_entries(self):
        return self._store.get_layer(MemoryLayer.BEHAVIORAL)

    def pacing_concerns(self) -> list[str]:
        return [
            e.content.removeprefix("PACING: ")
            for e in self._store.get_by_tag("pacing")
            if e.layer == MemoryLayer.BEHAVIORAL
        ]

    def broken_moments(self) -> list[str]:
        return [
            e.content.removeprefix("BROKEN: ")
            for e in self._store.get_by_tag("broken")
            if e.layer == MemoryLayer.BEHAVIORAL
        ]

    def intended_patterns(self) -> list[str]:
        return [
            e.content.removeprefix("INTENDED: ")
            for e in self._store.get_by_tag("intended")
            if e.layer == MemoryLayer.BEHAVIORAL
        ]

    def has_broken_moments(self) -> bool:
        return len(self.broken_moments()) > 0

    # ── Prefix text ───────────────────────────────────────────────────────────

    def to_prefix_text(self) -> str:
        """Returns behavioral memory as formatted text for LLM cached prefix."""
        parts = ["=== BEHAVIORAL MEMORY ==="]

        patterns = self.intended_patterns()
        if patterns:
            parts.append("Intended feel:")
            for p in patterns[:3]:
                parts.append(f"  - {p}")

        concerns = self.pacing_concerns()
        if concerns:
            parts.append("Pacing concerns:")
            for c in concerns[:3]:
                parts.append(f"  - {c}")

        broken = self.broken_moments()
        if broken:
            parts.append(f"Known issues ({len(broken)} total):")
            for b in broken[:2]:
                parts.append(f"  - {b}")

        parts.append("=== END BEHAVIORAL MEMORY ===")
        return "\n".join(parts)

    @property
    def entry_count(self) -> int:
        return self._store.count(MemoryLayer.BEHAVIORAL)