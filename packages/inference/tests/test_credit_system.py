"""
tests/test_credit_system.py
=============================
Tests for CreditSystem: balance management, check_credits enforcement,
deduction, file locking, TIER_S zero cost.
"""
 
import os
import tempfile
import pytest
 
from ..credit_system import (
    CreditSystem, CreditConfig, InsufficientCreditsError,
)
 
 
def _cs(initial: float = 0.0, allow_negative: bool = False) -> CreditSystem:
    """Creates a CreditSystem backed by a temporary file."""
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    config = CreditConfig(
        ledger_path          = tmp.name,
        allow_negative_balance = allow_negative,
        low_balance_warn_threshold = 100.0,
    )
    cs = CreditSystem(config)
    if initial > 0:
        cs.add_credits("user_test", initial)
    return cs
 
 
class TestCreditSystemBalance:
 
    def test_new_user_balance_is_zero(self) -> None:
        cs = _cs()
        assert cs.get_balance("new_user") == 0.0
 
    def test_add_credits_returns_new_balance(self) -> None:
        cs = _cs()
        balance = cs.add_credits("u1", 500.0)
        assert balance == 500.0
 
    def test_add_credits_accumulates(self) -> None:
        cs = _cs()
        cs.add_credits("u1", 300.0)
        cs.add_credits("u1", 200.0)
        assert cs.get_balance("u1") == 500.0
 
    def test_set_balance_overwrites(self) -> None:
        cs = _cs(initial=500.0)
        cs.set_balance("user_test", 100.0)
        assert cs.get_balance("user_test") == 100.0
 
    def test_add_negative_raises(self) -> None:
        cs = _cs()
        with pytest.raises(ValueError, match="non-negative"):
            cs.add_credits("u1", -10.0)
 
    def test_user_exists_true_after_add(self) -> None:
        cs = _cs()
        cs.add_credits("u_new", 10.0)
        assert cs.user_exists("u_new")
 
    def test_user_exists_false_for_unknown(self) -> None:
        cs = _cs()
        assert not cs.user_exists("unknown_xyz")
 
    def test_lifetime_spent_accumulates(self) -> None:
        cs = _cs(initial=1000.0)
        cs.deduct_credits("user_test", 30.0)
        cs.deduct_credits("user_test", 20.0)
        assert abs(cs.lifetime_spent("user_test") - 50.0) < 0.001
 
    def test_all_users_returns_list(self) -> None:
        cs = _cs()
        cs.add_credits("alpha", 100.0)
        cs.add_credits("beta",  200.0)
        users = cs.all_users()
        assert "alpha" in users
        assert "beta"  in users
 
 
class TestCreditSystemCheckCredits:
 
    def test_check_passes_when_balance_sufficient(self) -> None:
        cs = _cs(initial=500.0)
        cs.check_credits("user_test", 10.0)   # must not raise
 
    def test_check_raises_when_insufficient(self) -> None:
        cs = _cs(initial=5.0)
        with pytest.raises(InsufficientCreditsError) as exc_info:
            cs.check_credits("user_test", 10.0)
        err = exc_info.value
        assert err.user_id           == "user_test"
        assert err.requested_credits == 10.0
        assert err.available_credits  == 5.0
 
    def test_check_zero_cost_always_passes(self) -> None:
        cs = _cs(initial=0.0)
        cs.check_credits("broke_user", 0.0)   # TIER_S — must not raise
 
    def test_check_negative_cost_always_passes(self) -> None:
        cs = _cs(initial=0.0)
        cs.check_credits("u", -1.0)   # invalid but not an error
 
    def test_allow_negative_balance_permits_overdraft(self) -> None:
        cs = _cs(initial=5.0, allow_negative=True)
        cs.check_credits("user_test", 100.0)   # must not raise
 
    def test_error_message_is_informative(self) -> None:
        cs = _cs(initial=10.0)
        try:
            cs.check_credits("user_test", 50.0)
        except InsufficientCreditsError as e:
            msg = str(e)
            assert "user_test"  in msg
            assert "50.0"       in msg
            assert "10.0"       in msg
 
 
class TestCreditSystemDeduction:
 
    def test_deduct_reduces_balance(self) -> None:
        cs = _cs(initial=100.0)
        new_balance = cs.deduct_credits("user_test", 30.0)
        assert abs(new_balance - 70.0) < 0.001
        assert abs(cs.get_balance("user_test") - 70.0) < 0.001
 
    def test_deduct_zero_is_noop(self) -> None:
        cs = _cs(initial=100.0)
        cs.deduct_credits("user_test", 0.0)
        assert cs.get_balance("user_test") == 100.0
 
    def test_deduct_unknown_user_creates_negative_balance(self) -> None:
        cs = _cs(allow_negative=True)
        new_balance = cs.deduct_credits("new_user", 10.0)
        assert new_balance == -10.0
 
    def test_multiple_deductions_accumulate(self) -> None:
        cs = _cs(initial=100.0)
        for _ in range(5):
            cs.deduct_credits("user_test", 10.0)
        assert abs(cs.get_balance("user_test") - 50.0) < 0.001
 
 
class TestCreditSystemLowBalance:
 
    def test_is_low_balance_true_below_threshold(self) -> None:
        cs = _cs(initial=50.0)
        assert cs.is_low_balance("user_test")
 
    def test_is_low_balance_false_above_threshold(self) -> None:
        cs = _cs(initial=200.0)
        assert not cs.is_low_balance("user_test")
 
 
class TestCreditSystemPersistence:
 
    def test_balance_persists_across_instances(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
 
        config = CreditConfig(ledger_path=path)
        cs1 = CreditSystem(config)
        cs1.add_credits("persistent_user", 999.0)
 
        # Create new instance pointing to same file
        cs2 = CreditSystem(config)
        assert cs2.get_balance("persistent_user") == 999.0
 
        os.unlink(path)
 
    def test_user_summary_contains_expected_fields(self) -> None:
        cs = _cs(initial=500.0)
        summary = cs.user_summary("user_test")
        assert summary["exists"] is True
        assert summary["balance_credits"] == 500.0
        assert "balance_usd" in summary