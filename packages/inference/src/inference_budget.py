"""
inference_budget.py — InferenceBudget
========================================
Enforces per-session and per-user-per-day token and cost budgets for
every LLM call that goes through InferenceAdapter.

## Why a Budget System Now?
At launch, all budgets default to infinite. The interface is installed
now so PIL submodules never need to know whether a budget exists.
When a budget threshold is set, it activates without any PIL changes.

## Three Budget Scopes
    session_budget   — tokens and cost allowed per builder session
                       (a session = one browser tab, one CGS load)
    daily_user_budget— tokens and cost per user per calendar day
    global_budget    — total platform budget; blocks ALL calls on breach
                       (only used in extreme cost-control scenarios)

## Two Budget Types per Scope
    token_budget   — total input+output tokens (catches volume abuse)
    cost_budget    — total USD cents (catches expensive model abuse)

## Flow in InferenceAdapter
    1. pre_check(session_id)   → raises BudgetExceededError if already over
    2. ... dispatch the call ...
    3. record(session_id, tokens, cost)  → updates running totals

## BudgetExceededError
    BudgetExceededError carries the scope, what was exceeded, and
    how much remains. InferenceAdapter catches it, emits a telemetry event
    with outcome="budget_exceeded", then re-raises for PIL to handle
    (typically: escalate to clarification).

## Thread Safety
InferenceBudget is thread-safe. All counter updates use a lock.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


# ── Budget Error ──────────────────────────────────────────────────────────────

@dataclass
class BudgetExceededError(Exception):
    """
    Raised when a call would breach a budget threshold.

    Attributes
    ----------
    scope : str
        Which budget was breached: "session" | "daily_user" | "global"
    exceeded_type : str
        What was exceeded: "tokens" | "cost_cents"
    current_value : float
        Current running total at time of rejection.
    limit : float
        The budget limit that was exceeded.
    session_id : str
        The session that triggered the check.
    user_id : str
        The user (empty for session-only budgets).
    """

    scope:          str
    exceeded_type:  str
    current_value:  float
    limit:          float
    session_id:     str = ""
    user_id:        str = ""

    def __str__(self) -> str:
        pct = (self.current_value / self.limit * 100) if self.limit > 0 else 0
        unit = "tokens" if self.exceeded_type == "tokens" else "¢"
        return (
            f"BudgetExceeded [{self.scope}]: "
            f"{self.exceeded_type} at {self.current_value:.1f}{unit} "
            f"/ {self.limit:.1f}{unit} limit ({pct:.0f}%%). "
            f"Session: {self.session_id!r}. "
            f"No further inference calls allowed until budget resets."
        )


# ── Budget Configuration ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class BudgetConfig:
    """
    Defines budget limits for all scopes.

    Values of 0 or negative mean "unlimited" for that field.
    All token limits are total (input + output combined).
    All cost limits are in USD cents.
    """

    # Per-session limits
    session_max_tokens:     float = 0.0   # 0 = unlimited
    session_max_cost_cents: float = 0.0   # 0 = unlimited

    # Per-user per-day limits
    daily_user_max_tokens:     float = 0.0
    daily_user_max_cost_cents: float = 0.0

    # Platform-wide global limit (emergency brake)
    global_max_cost_cents_per_hour: float = 0.0

    # Soft warning thresholds (fraction of limit, 0.0–1.0)
    # When reached, telemetry emits a warning but call proceeds.
    session_warn_fraction:    float = 0.80
    daily_warn_fraction:      float = 0.80

    def is_limited(self) -> bool:
        """Returns True if any limit is actually set (non-zero)."""
        return any([
            self.session_max_tokens > 0,
            self.session_max_cost_cents > 0,
            self.daily_user_max_tokens > 0,
            self.daily_user_max_cost_cents > 0,
            self.global_max_cost_cents_per_hour > 0,
        ])


# Default: no limits
UNLIMITED_BUDGET = BudgetConfig()


# ── Running Counters ──────────────────────────────────────────────────────────

@dataclass
class _BudgetCounter:
    """Internal mutable counter for one scope (session or user-day)."""

    tokens:     float = 0.0
    cost_cents: float = 0.0
    created_at: float = field(default_factory=time.time)
    warned:     bool  = False


# ── Inference Budget ──────────────────────────────────────────────────────────

class InferenceBudget:
    """
    Enforces per-session and per-user-per-day inference budgets.

    Stateful — one instance shared across InferenceAdapter calls.
    Default configuration is fully unlimited; set limits via set_config()
    or pass a BudgetConfig at construction.

    Usage
    -----
        budget = InferenceBudget(BudgetConfig(
            session_max_cost_cents=500.0,      # $5 per session
            daily_user_max_cost_cents=5000.0,  # $50 per user per day
        ))

        # In InferenceAdapter — before the call:
        budget.pre_check(session_id="sess_abc", user_id="user_xyz")

        # After the call:
        budget.record(
            session_id="sess_abc",
            user_id="user_xyz",
            input_tokens=1200,
            output_tokens=400,
            cost_cents=2.5,
        )
    """

    def __init__(self, config: BudgetConfig = UNLIMITED_BUDGET) -> None:
        self._config  = config
        self._lock    = threading.Lock()

        # session_id → _BudgetCounter
        self._sessions: dict[str, _BudgetCounter] = {}
        # "user_id:YYYY-MM-DD" → _BudgetCounter
        self._user_days: dict[str, _BudgetCounter] = {}
        # hourly platform total
        self._global_hour_start: float = time.time()
        self._global_hour_cost:  float = 0.0

    # ── Public API ────────────────────────────────────────────────────────────

    def pre_check(
        self,
        session_id: str,
        user_id:    str = "",
    ) -> None:
        """
        Checks whether any budget would be exceeded before dispatching a call.

        Raises
        ------
        BudgetExceededError
            If any active limit has already been reached.
        """
        if not self._config.is_limited():
            return   # fast path — no limits configured

        with self._lock:
            self._check_session(session_id)
            if user_id:
                self._check_user_day(user_id, session_id)
            self._check_global(session_id)

    def record(
        self,
        session_id:    str,
        input_tokens:  int   = 0,
        output_tokens: int   = 0,
        cost_cents:    float = 0.0,
        user_id:       str   = "",
    ) -> None:
        """
        Records actual usage after a call completes.
        Also records for TIER_S shortcuts (zero cost) and cache hits.
        """
        total_tokens = input_tokens + output_tokens

        with self._lock:
            # Session counter
            sess = self._sessions.setdefault(session_id, _BudgetCounter())
            sess.tokens     += total_tokens
            sess.cost_cents += cost_cents

            # User-day counter
            if user_id:
                key = self._user_day_key(user_id)
                day = self._user_days.setdefault(key, _BudgetCounter())
                day.tokens     += total_tokens
                day.cost_cents += cost_cents

            # Global hourly counter
            self._maybe_reset_global_hour()
            self._global_hour_cost += cost_cents

    def warn_fraction_reached(
        self,
        session_id: str,
        user_id:    str = "",
    ) -> list[str]:
        """
        Returns a list of warning strings for any counter that has crossed
        its soft warning threshold. Empty list = no warnings.
        Called by InferenceAdapter to emit soft-warning telemetry.
        """
        if not self._config.is_limited():
            return []

        warnings: list[str] = []
        with self._lock:
            sess = self._sessions.get(session_id)
            if sess:
                warnings.extend(self._session_warnings(sess, session_id))
            if user_id:
                key = self._user_day_key(user_id)
                day = self._user_days.get(key)
                if day:
                    warnings.extend(self._day_warnings(day, user_id))
        return warnings

    def session_usage(self, session_id: str) -> dict[str, float]:
        """Returns current usage for a session as a plain dict."""
        with self._lock:
            sess = self._sessions.get(session_id)
            if not sess:
                return {"tokens": 0.0, "cost_cents": 0.0}
            return {"tokens": sess.tokens, "cost_cents": sess.cost_cents}

    def user_day_usage(self, user_id: str) -> dict[str, float]:
        """Returns current usage for a user's current day."""
        with self._lock:
            key = self._user_day_key(user_id)
            day = self._user_days.get(key)
            if not day:
                return {"tokens": 0.0, "cost_cents": 0.0}
            return {"tokens": day.tokens, "cost_cents": day.cost_cents}

    def close_session(self, session_id: str) -> None:
        """Removes session counter. Call on session end to release memory."""
        with self._lock:
            self._sessions.pop(session_id, None)

    def set_config(self, config: BudgetConfig) -> None:
        """Replaces the budget configuration. Takes effect immediately."""
        with self._lock:
            self._config = config

    # ── Internal checks ───────────────────────────────────────────────────────

    def _check_session(self, session_id: str) -> None:
        sess = self._sessions.get(session_id)
        if not sess:
            return

        if self._config.session_max_tokens > 0:
            if sess.tokens >= self._config.session_max_tokens:
                raise BudgetExceededError(
                    scope         = "session",
                    exceeded_type = "tokens",
                    current_value = sess.tokens,
                    limit         = self._config.session_max_tokens,
                    session_id    = session_id,
                )

        if self._config.session_max_cost_cents > 0:
            if sess.cost_cents >= self._config.session_max_cost_cents:
                raise BudgetExceededError(
                    scope         = "session",
                    exceeded_type = "cost_cents",
                    current_value = sess.cost_cents,
                    limit         = self._config.session_max_cost_cents,
                    session_id    = session_id,
                )

    def _check_user_day(self, user_id: str, session_id: str) -> None:
        key = self._user_day_key(user_id)
        day = self._user_days.get(key)
        if not day:
            return

        if self._config.daily_user_max_tokens > 0:
            if day.tokens >= self._config.daily_user_max_tokens:
                raise BudgetExceededError(
                    scope         = "daily_user",
                    exceeded_type = "tokens",
                    current_value = day.tokens,
                    limit         = self._config.daily_user_max_tokens,
                    session_id    = session_id,
                    user_id       = user_id,
                )

        if self._config.daily_user_max_cost_cents > 0:
            if day.cost_cents >= self._config.daily_user_max_cost_cents:
                raise BudgetExceededError(
                    scope         = "daily_user",
                    exceeded_type = "cost_cents",
                    current_value = day.cost_cents,
                    limit         = self._config.daily_user_max_cost_cents,
                    session_id    = session_id,
                    user_id       = user_id,
                )

    def _check_global(self, session_id: str) -> None:
        if self._config.global_max_cost_cents_per_hour <= 0:
            return
        self._maybe_reset_global_hour()
        if self._global_hour_cost >= self._config.global_max_cost_cents_per_hour:
            raise BudgetExceededError(
                scope         = "global",
                exceeded_type = "cost_cents",
                current_value = self._global_hour_cost,
                limit         = self._config.global_max_cost_cents_per_hour,
                session_id    = session_id,
            )

    def _maybe_reset_global_hour(self) -> None:
        """Resets hourly counter if more than 3600s have passed."""
        now = time.time()
        if now - self._global_hour_start >= 3600:
            self._global_hour_cost  = 0.0
            self._global_hour_start = now

    def _session_warnings(
        self, sess: _BudgetCounter, session_id: str
    ) -> list[str]:
        warnings: list[str] = []
        frac = self._config.session_warn_fraction

        if self._config.session_max_tokens > 0:
            if sess.tokens >= self._config.session_max_tokens * frac and not sess.warned:
                warnings.append(
                    f"Session '{session_id}' token budget at "
                    f"{sess.tokens / self._config.session_max_tokens * 100:.0f}%% "
                    f"({sess.tokens:.0f}/{self._config.session_max_tokens:.0f})."
                )

        if self._config.session_max_cost_cents > 0:
            if sess.cost_cents >= self._config.session_max_cost_cents * frac and not sess.warned:
                warnings.append(
                    f"Session '{session_id}' cost budget at "
                    f"{sess.cost_cents / self._config.session_max_cost_cents * 100:.0f}%% "
                    f"({sess.cost_cents:.1f}/{self._config.session_max_cost_cents:.1f}¢)."
                )

        if warnings:
            sess.warned = True
        return warnings

    def _day_warnings(
        self, day: _BudgetCounter, user_id: str
    ) -> list[str]:
        warnings: list[str] = []
        frac = self._config.daily_warn_fraction

        if self._config.daily_user_max_cost_cents > 0:
            if day.cost_cents >= self._config.daily_user_max_cost_cents * frac and not day.warned:
                warnings.append(
                    f"User '{user_id}' daily cost budget at "
                    f"{day.cost_cents / self._config.daily_user_max_cost_cents * 100:.0f}%% "
                    f"({day.cost_cents:.1f}/{self._config.daily_user_max_cost_cents:.1f}¢)."
                )
                day.warned = True
        return warnings

    @staticmethod
    def _user_day_key(user_id: str) -> str:
        """Returns a stable key for today's user-day counter."""
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return f"{user_id}:{today}"

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"InferenceBudget("
                f"limited={self._config.is_limited()}, "
                f"sessions={len(self._sessions)}, "
                f"user_days={len(self._user_days)})"
            )