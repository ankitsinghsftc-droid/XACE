"""
design_memory.py — DesignMemory
=================================
Layer 1 of the 5-layer memory model. CACHED PREFIX.

Stores the game's high-level design vision and philosophy. This layer
is the most stable — it changes only when a designer makes an explicit
high-level decision, not on every mutation.

## Contents

    game_vision   : str    — one-paragraph game concept summary
                            "Top-down zombie survival. Player must reach
                             extraction zone while managing health and ammo."

    difficulty_philosophy : str
                            "Hard by default. Player death is permanent
                             in a session. Zombies should feel dangerous."

    core_constraints : list[str]
                            Invariants the designer wants preserved:
                            "Player always has agency — no instant kills."
                            "All threats visible on screen before attack."

## Design Drift Detection

    When a new mutation is proposed, DesignMemory.check_drift() compares
    the mutation summary against the stated core_constraints. If a mutation
    directly contradicts a constraint, it returns a drift warning.

    Example: core_constraint = "Player always has agency"
             proposed mutation: "Remove all input from player during cutscene"
             → drift detected: "This contradicts 'Player always has agency'"

    Drift detection is advisory — it never blocks a mutation on its own.
    The CritiqueEngine uses drift findings as concerns.

## IN CACHED PREFIX (II9)

    All DesignMemory content goes into the LLM cached prefix because:
    1. It's stable across many calls
    2. It's large (game vision can be hundreds of words)
    3. It's identical across successive calls for the same game

    MemoryLayer.DESIGN is assigned to entries from this class.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "memory"))
from memory_store import MemoryStore, MemoryLayer


# ── Design Memory ─────────────────────────────────────────────────────────────

class DesignMemory:
    """
    Manages the game design vision layer.

    Usage
    -----
        dm = DesignMemory(store)
        dm.set_game_vision("Top-down zombie survival shooter.")
        dm.set_difficulty_philosophy("Hard but fair.")
        dm.add_core_constraint("Player always has agency.")

        # Before committing a mutation:
        drift = dm.check_drift("Remove player input during cutscene")
        # drift → ["Constraint conflict: 'Player always has agency'"]

        # For LLM context:
        prefix = dm.to_prefix_text()
    """

    def __init__(self, store: MemoryStore) -> None:
        self._store = store
        # Design memory uses special entry IDs for stable single-value fields
        self._vision_id:    str | None = None
        self._difficulty_id: str | None = None

    # ── Setters ───────────────────────────────────────────────────────────────

    def set_game_vision(self, vision: str) -> None:
        """Sets (or replaces) the game vision summary."""
        if self._vision_id:
            self._store.remove(self._vision_id)
        entry = self._store.add(
            layer           = MemoryLayer.DESIGN,
            content         = f"GAME VISION: {vision.strip()}",
            relevance_score = 1.0,
            tags            = {"vision", "design"},
            metadata        = {"field": "game_vision"},
        )
        self._vision_id = entry.entry_id

    def set_difficulty_philosophy(self, philosophy: str) -> None:
        """Sets (or replaces) the difficulty philosophy."""
        if self._difficulty_id:
            self._store.remove(self._difficulty_id)
        entry = self._store.add(
            layer           = MemoryLayer.DESIGN,
            content         = f"DIFFICULTY: {philosophy.strip()}",
            relevance_score = 0.9,
            tags            = {"difficulty", "design"},
            metadata        = {"field": "difficulty_philosophy"},
        )
        self._difficulty_id = entry.entry_id

    def add_core_constraint(self, constraint: str) -> str:
        """Adds a core design constraint. Returns entry_id."""
        entry = self._store.add(
            layer           = MemoryLayer.DESIGN,
            content         = f"CONSTRAINT: {constraint.strip()}",
            relevance_score = 0.95,
            tags            = {"constraint", "design"},
            metadata        = {"field": "core_constraint"},
        )
        return entry.entry_id

    def remove_constraint(self, entry_id: str) -> bool:
        """Removes a constraint by entry_id. Returns True if found."""
        return self._store.remove(entry_id) is not None

    # ── Retrieval ─────────────────────────────────────────────────────────────

    @property
    def game_vision(self) -> str | None:
        if self._vision_id:
            entry = self._store.find_by_id(self._vision_id)
            if entry:
                return entry.content.removeprefix("GAME VISION: ")
        return None

    @property
    def difficulty_philosophy(self) -> str | None:
        if self._difficulty_id:
            entry = self._store.find_by_id(self._difficulty_id)
            if entry:
                return entry.content.removeprefix("DIFFICULTY: ")
        return None

    @property
    def core_constraints(self) -> list[str]:
        entries = self._store.get_by_tag("constraint")
        return [
            e.content.removeprefix("CONSTRAINT: ")
            for e in entries
            if e.layer == MemoryLayer.DESIGN
        ]

    def all_entries(self):
        return self._store.get_layer(MemoryLayer.DESIGN)

    # ── Drift detection ───────────────────────────────────────────────────────

    def check_drift(self, mutation_summary: str) -> list[str]:
        """
        Checks if a proposed mutation contradicts any core constraint.
        Returns a list of drift warnings (empty if none detected).
        Advisory only — does not block.
        """
        drift: list[str] = []
        summary_lower = mutation_summary.lower()

        for constraint in self.core_constraints:
            if self._likely_contradicts(summary_lower, constraint.lower()):
                drift.append(
                    f"Design drift: proposed mutation may contradict constraint: "
                    f"'{constraint}'"
                )
        return drift

    @staticmethod
    def _likely_contradicts(mutation_lower: str, constraint_lower: str) -> bool:
        """
        Heuristic contradiction detection.
        Looks for negation of key constraint phrases in the mutation.
        """
        # Extract key nouns from constraint (include shorter words, keep "player")
        stop_words = {"always", "never", "should", "every", "about", "their"}
        key_words = [w for w in constraint_lower.split()
                     if len(w) >= 4 and w not in stop_words]

        negation_prefixes = ("remove", "disable", "delete", "prevent", "block",
                              "strip", "eliminate", "no ")
        has_negation = any(mutation_lower.startswith(p) or f" {p}" in mutation_lower
                           for p in negation_prefixes)
        key_match = any(kw in mutation_lower for kw in key_words)

        return has_negation and key_match

    # ── LLM prefix text ───────────────────────────────────────────────────────

    def to_prefix_text(self) -> str:
        """Returns design memory as formatted text for LLM cached prefix."""
        parts: list[str] = ["=== GAME DESIGN MEMORY ==="]
        if self.game_vision:
            parts.append(f"Vision: {self.game_vision}")
        if self.difficulty_philosophy:
            parts.append(f"Difficulty: {self.difficulty_philosophy}")
        constraints = self.core_constraints
        if constraints:
            parts.append("Core constraints:")
            for c in constraints:
                parts.append(f"  - {c}")
        parts.append("=== END DESIGN MEMORY ===")
        return "\n".join(parts)

    @property
    def entry_count(self) -> int:
        return self._store.count(MemoryLayer.DESIGN)