"""
safety_memory.py — SafetyMemory
=================================
Layer 5 of the 5-layer memory model. PER-PROMPT BODY.

Records safety-relevant events: blocked mutations and accepted risk
confirmations. Prevents the system from showing the same warning twice
and tracks the designer's explicit risk acceptances.

## Contents

    blocked_mutations : Recent hard-blocked attempts (guard name + reason)
    risk_confirmations: Explicit "yes, I accept this risk" responses
    active_warnings   : Soft warnings currently in effect

## Why PER-PROMPT (not cached prefix)

    Safety state changes every turn — a designer who confirmed a risk
    at turn 3 should not have to re-confirm at turn 4 (session-local).
    But a NEW session starts fresh — a new user shouldn't inherit
    risk confirmations from a previous session.

## Anti-Redundancy

    SafetyMemory.is_already_blocked(guard_name, path) checks whether
    the same guard has already blocked the same path in this session.
    If so, the pipeline can skip the guard for that specific path in
    subsequent attempts.

    SafetyMemory.has_confirmed_risk(guard_name) checks whether the
    designer has explicitly confirmed they accept the risk from a
    specific guard. If confirmed, the guard produces a WARNING not
    a BLOCK on the next attempt.

## Max Entries

    blocked_mutations: 10
    risk_confirmations: 20
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "memory"))
from memory_store import MemoryStore, MemoryLayer

MAX_BLOCKED_RECORDS      = 10
MAX_RISK_CONFIRMATIONS   = 20


@dataclass
class BlockedRecord:
    """Record of one hard-blocked mutation attempt."""
    guard_name:  str
    path:        str
    reason:      str
    turn_index:  int


@dataclass
class RiskConfirmation:
    """Designer's explicit acceptance of a risk."""
    guard_name:  str
    description: str
    turn_index:  int
    confirmed:   bool   # True = accepted, False = rejected (cancelled)


class SafetyMemory:
    """
    Tracks safety events and risk acceptances for the current session.

    Usage
    -----
        sm = SafetyMemory(store)
        sm.record_block("scope_boundary", "metadata.cgs_hash", "forbidden")
        sm.record_risk_confirmation("cascade_risk", "20 systems affected", True)

        sm.is_already_blocked("scope_boundary", "metadata.cgs_hash")  # True
        sm.has_confirmed_risk("cascade_risk")  # True
    """

    def __init__(self, store: MemoryStore) -> None:
        self._store            = store
        self._blocked:         list[BlockedRecord]    = []
        self._confirmations:   list[RiskConfirmation] = []

    # ── Recording ─────────────────────────────────────────────────────────────

    def record_block(
        self,
        guard_name: str,
        path:       str,
        reason:     str,
    ) -> None:
        """Records a hard-blocked mutation attempt."""
        turn = self._store.turn_index
        rec  = BlockedRecord(guard_name=guard_name, path=path,
                             reason=reason, turn_index=turn)
        self._blocked.append(rec)
        if len(self._blocked) > MAX_BLOCKED_RECORDS:
            self._blocked.pop(0)

        self._store.add(
            layer           = MemoryLayer.SAFETY,
            content         = (
                f"BLOCKED[{guard_name}]: path='{path[:60]}' "
                f"reason='{reason[:100]}'"
            ),
            relevance_score = 1.0,   # safety entries always max relevance
            tags            = {"safety", "blocked", guard_name},
            metadata        = {"kind": "block", "guard": guard_name, "turn": turn},
        )

    def record_risk_confirmation(
        self,
        guard_name:  str,
        description: str,
        confirmed:   bool,
    ) -> None:
        """
        Records the designer's response to a risk warning.
        confirmed=True means they accepted the risk.
        confirmed=False means they cancelled/rejected.
        """
        turn = self._store.turn_index
        conf = RiskConfirmation(guard_name=guard_name, description=description,
                                turn_index=turn, confirmed=confirmed)
        self._confirmations.append(conf)
        if len(self._confirmations) > MAX_RISK_CONFIRMATIONS:
            self._confirmations.pop(0)

        verb = "ACCEPTED" if confirmed else "REJECTED"
        self._store.add(
            layer           = MemoryLayer.SAFETY,
            content         = (
                f"RISK {verb}[{guard_name}]: {description[:120]}"
            ),
            relevance_score = 0.9,
            tags            = {"safety", "confirmation", guard_name},
            metadata        = {"kind": "confirmation", "guard": guard_name,
                               "confirmed": confirmed, "turn": turn},
        )

    # ── Queries ───────────────────────────────────────────────────────────────

    def is_already_blocked(self, guard_name: str, path: str) -> bool:
        """True if this guard has already blocked this exact path in this session."""
        return any(
            b.guard_name == guard_name and b.path == path
            for b in self._blocked
        )

    def has_confirmed_risk(self, guard_name: str) -> bool:
        """True if the designer has confirmed acceptance of this guard's risk."""
        return any(
            c.guard_name == guard_name and c.confirmed
            for c in self._confirmations
        )

    def has_rejected_risk(self, guard_name: str) -> bool:
        """True if the designer has rejected/cancelled this guard's risk."""
        return any(
            c.guard_name == guard_name and not c.confirmed
            for c in self._confirmations
        )

    @property
    def blocked_guards_this_session(self) -> list[str]:
        """Names of guards that have blocked at least once this session."""
        return list(dict.fromkeys(b.guard_name for b in self._blocked))

    @property
    def confirmed_risks(self) -> list[str]:
        """Guard names for which risk has been confirmed."""
        return [c.guard_name for c in self._confirmations if c.confirmed]

    # ── Clear ─────────────────────────────────────────────────────────────────

    def clear(self) -> None:
        """Clears safety memory. Called on session end."""
        self._store.clear_layer(MemoryLayer.SAFETY)
        self._blocked.clear()
        self._confirmations.clear()

    # ── Body text ─────────────────────────────────────────────────────────────

    def to_body_text(self) -> str:
        """Returns safety memory as formatted text for per-prompt body."""
        parts = ["=== SAFETY CONTEXT ==="]

        if self._blocked:
            recent_blocks = self._blocked[-3:]
            parts.append(f"Recent blocks ({len(self._blocked)} total):")
            for b in recent_blocks:
                parts.append(f"  - [{b.guard_name}] {b.reason[:60]}")

        if self._confirmations:
            accepted = [c for c in self._confirmations if c.confirmed]
            if accepted:
                guards = list(dict.fromkeys(c.guard_name for c in accepted))
                parts.append(f"Designer accepted risks: {', '.join(guards)}")

        if not self._blocked and not self._confirmations:
            parts.append("No safety events this session.")

        parts.append("=== END SAFETY CONTEXT ===")
        return "\n".join(parts)

    @property
    def entry_count(self) -> int:
        return self._store.count(MemoryLayer.SAFETY)