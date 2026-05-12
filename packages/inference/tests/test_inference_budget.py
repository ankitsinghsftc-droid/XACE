"""
tests/test_inference_budget.py
================================
Tests for InferenceBudget: cap enforcement, warn thresholds,
record accumulation, and session lifecycle.
"""

from __future__ import annotations

import time
import pytest

from ..src.inference_budget import (
    InferenceBudget, BudgetConfig, BudgetExceededError, UNLIMITED_BUDGET,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _budget(
    session_tokens:    float = 0.0,
    session_cents:     float = 0.0,
    daily_tokens:      float = 0.0,
    daily_cents:       float = 0.0,
    global_cents_hr:   float = 0.0,
    warn_fraction:     float = 0.80,
) -> InferenceBudget:
    config = BudgetConfig(
        session_max_tokens            = session_tokens,
        session_max_cost_cents        = session_cents,
        daily_user_max_tokens         = daily_tokens,
        daily_user_max_cost_cents     = daily_cents,
        global_max_cost_cents_per_hour = global_cents_hr,
        session_warn_fraction          = warn_fraction,
        daily_warn_fraction            = warn_fraction,
    )
    return InferenceBudget(config)


# ── Unlimited Budget ──────────────────────────────────────────────────────────

class TestUnlimitedBudget:

    def test_pre_check_never_raises_with_default_config(self) -> None:
        budget = InferenceBudget()
        for _ in range(100):
            budget.pre_check("session_1")   # must never raise

    def test_unlimited_budget_is_not_limited(self) -> None:
        assert not UNLIMITED_BUDGET.is_limited()

    def test_custom_config_with_no_limits_is_not_limited(self) -> None:
        cfg = BudgetConfig()
        assert not cfg.is_limited()

    def test_config_with_session_token_limit_is_limited(self) -> None:
        cfg = BudgetConfig(session_max_tokens=10_000)
        assert cfg.is_limited()

    def test_record_accumulates_without_limit(self) -> None:
        budget = InferenceBudget()
        for _ in range(1000):
            budget.record("session_x", input_tokens=100, output_tokens=50, cost_cents=0.1)
        usage = budget.session_usage("session_x")
        assert usage["tokens"]     == 150_000
        assert abs(usage["cost_cents"] - 100.0) < 0.01


# ── Session Token Cap ─────────────────────────────────────────────────────────

class TestSessionTokenCap:

    def test_session_token_cap_blocks_on_breach(self) -> None:
        budget = _budget(session_tokens=1000)
        budget.record("sess", input_tokens=900, output_tokens=200)  # total 1100 > 1000
        with pytest.raises(BudgetExceededError) as exc_info:
            budget.pre_check("sess")
        err = exc_info.value
        assert err.scope         == "session"
        assert err.exceeded_type == "tokens"

    def test_session_token_cap_passes_under_limit(self) -> None:
        budget = _budget(session_tokens=1000)
        budget.record("sess", input_tokens=400, output_tokens=400)  # total 800 < 1000
        budget.pre_check("sess")   # must not raise

    def test_session_token_cap_exactly_at_limit_blocks(self) -> None:
        budget = _budget(session_tokens=1000)
        budget.record("sess", input_tokens=500, output_tokens=500)  # exactly 1000
        with pytest.raises(BudgetExceededError):
            budget.pre_check("sess")

    def test_fresh_session_not_blocked(self) -> None:
        budget = _budget(session_tokens=1000)
        budget.pre_check("fresh_session")   # no records yet → must not raise


# ── Session Cost Cap ──────────────────────────────────────────────────────────

class TestSessionCostCap:

    def test_session_cost_cap_blocks_on_breach(self) -> None:
        budget = _budget(session_cents=10.0)
        budget.record("sess", cost_cents=11.0)
        with pytest.raises(BudgetExceededError) as exc_info:
            budget.pre_check("sess")
        err = exc_info.value
        assert err.scope         == "session"
        assert err.exceeded_type == "cost_cents"

    def test_session_cost_cap_passes_under_limit(self) -> None:
        budget = _budget(session_cents=100.0)
        budget.record("sess", cost_cents=50.0)
        budget.pre_check("sess")   # must not raise

    def test_multiple_records_accumulate(self) -> None:
        budget = _budget(session_cents=10.0)
        for i in range(5):
            budget.record(f"sess_{i}", cost_cents=3.0)   # different sessions

        # Only one session has records — it's at 3.0¢, not 15.0¢
        budget.pre_check("sess_0")   # 3.0 < 10.0 → must not raise

    def test_two_records_same_session_accumulate(self) -> None:
        budget = _budget(session_cents=10.0)
        budget.record("sess", cost_cents=6.0)
        budget.record("sess", cost_cents=6.0)   # total 12.0 > 10.0
        with pytest.raises(BudgetExceededError):
            budget.pre_check("sess")


# ── Daily User Cap ────────────────────────────────────────────────────────────

class TestDailyUserCap:

    def test_daily_user_cost_cap_blocks_on_breach(self) -> None:
        budget = _budget(daily_cents=50.0)
        budget.record("sess", user_id="user1", cost_cents=55.0)
        with pytest.raises(BudgetExceededError) as exc_info:
            budget.pre_check("sess", user_id="user1")
        err = exc_info.value
        assert err.scope   == "daily_user"
        assert err.user_id == "user1"

    def test_daily_user_cap_passes_under_limit(self) -> None:
        budget = _budget(daily_cents=100.0)
        budget.record("sess", user_id="user1", cost_cents=40.0)
        budget.pre_check("sess", user_id="user1")   # must not raise

    def test_different_users_independent_caps(self) -> None:
        budget = _budget(daily_cents=50.0)
        budget.record("sess1", user_id="user1", cost_cents=55.0)
        budget.record("sess2", user_id="user2", cost_cents=10.0)
        # user1 over limit
        with pytest.raises(BudgetExceededError):
            budget.pre_check("sess1", user_id="user1")
        # user2 under limit
        budget.pre_check("sess2", user_id="user2")   # must not raise

    def test_no_user_id_skips_daily_check(self) -> None:
        budget = _budget(daily_cents=5.0)
        budget.record("sess", cost_cents=10.0)
        # Without user_id, daily check skipped
        budget.pre_check("sess")   # must not raise (only session checked)


# ── Session Lifecycle ─────────────────────────────────────────────────────────

class TestSessionLifecycle:

    def test_close_session_releases_counter(self) -> None:
        budget = _budget(session_tokens=1000)
        budget.record("sess", input_tokens=900, output_tokens=200)
        budget.close_session("sess")
        # After close, pre_check should not raise (counter gone)
        budget.pre_check("sess")

    def test_session_usage_returns_zero_for_unknown(self) -> None:
        budget = InferenceBudget()
        usage  = budget.session_usage("never_seen")
        assert usage["tokens"]     == 0.0
        assert usage["cost_cents"] == 0.0

    def test_user_day_usage_returns_zero_for_unknown(self) -> None:
        budget = InferenceBudget()
        usage  = budget.user_day_usage("unknown_user")
        assert usage["tokens"]     == 0.0
        assert usage["cost_cents"] == 0.0


# ── Warn Threshold ────────────────────────────────────────────────────────────

class TestWarnThreshold:

    def test_warn_fraction_returns_warnings_at_threshold(self) -> None:
        budget = _budget(session_cents=100.0, warn_fraction=0.80)
        budget.record("sess", cost_cents=82.0)   # 82% > 80% warn threshold
        warnings = budget.warn_fraction_reached("sess")
        assert len(warnings) > 0
        assert any("budget" in w.lower() or "%" in w for w in warnings)

    def test_no_warning_below_threshold(self) -> None:
        budget = _budget(session_cents=100.0, warn_fraction=0.80)
        budget.record("sess", cost_cents=70.0)   # 70% < 80%
        warnings = budget.warn_fraction_reached("sess")
        assert len(warnings) == 0

    def test_unlimited_budget_no_warnings(self) -> None:
        budget   = InferenceBudget()
        budget.record("sess", cost_cents=9999.0)
        warnings = budget.warn_fraction_reached("sess")
        assert warnings == []


# ── Record Accounting ─────────────────────────────────────────────────────────

class TestRecordAccounting:

    def test_zero_cost_record_is_allowed(self) -> None:
        budget = InferenceBudget()
        budget.record("sess", input_tokens=0, output_tokens=0, cost_cents=0.0)
        usage = budget.session_usage("sess")
        assert usage["tokens"]     == 0.0
        assert usage["cost_cents"] == 0.0

    def test_tokens_are_input_plus_output(self) -> None:
        budget = InferenceBudget()
        budget.record("sess", input_tokens=300, output_tokens=150, cost_cents=5.0)
        usage = budget.session_usage("sess")
        assert usage["tokens"] == 450.0

    def test_repr_shows_budget_status(self) -> None:
        budget = _budget(session_cents=100.0)
        budget.record("s1", cost_cents=10.0)
        r = repr(budget)
        assert "InferenceBudget" in r
        assert "limited=True" in r