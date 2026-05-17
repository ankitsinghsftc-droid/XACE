"""
credit_system.py — CreditSystem
===================================
Per-user, per-session credit accounting for XACE inference calls.

Credits gate every LLM call:
    1. check_credits(user_id, estimated_cost) → raises InsufficientCreditsError if insufficient
    2. ... inference call dispatched ...
    3. deduct_credits(user_id, actual_cost) → deducts actual cost from balance

## Credit Unit
1 credit = 1 USD cent (¢). Users top up $10 = 1,000 credits.
The `base_credit_price_cents` field in CreditConfig exists for future flexibility.

## Relationship to InferenceBudget
Both CreditSystem and InferenceBudget enforce spending limits, but:
    - CreditSystem:    "user has purchased X credits; deduct actual usage"
    - InferenceBudget: "this session/day must not exceed Y tokens/cents"

Both checks apply. CreditSystem runs FIRST (raises InsufficientCreditsError).
InferenceBudget runs SECOND (raises BudgetExceededError).

TIER_S (deterministic shortcut): zero cost, zero credit deduction.

## Ledger Format
Single JSON file at `ledger_path`:
```json
{
  "user_123": {
    "balance_credits": 950.0,
    "lifetime_spent_credits": 50.0,
    "created_at_epoch": 1716000000,
    "last_updated_epoch": 1716001000
  }
}
```

## Thread Safety
- In-process: `threading.RLock` on all ledger operations.
- Cross-process: `fcntl.flock` on POSIX; best-effort `try/except` on Windows
  (Windows flock equivalent is msvcrt which is per-file-handle, not per-process).
  For production with multiple processes, migrate to SQLite WAL mode.

## TIER_S Credit Behaviour
Tier S mutations cost zero credits. `check_credits` with `estimated_cost=0.0`
is a no-op (no balance consumed, no error raised).
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ── Error ─────────────────────────────────────────────────────────────────────

@dataclass
class InsufficientCreditsError(Exception):
    """
    Raised by check_credits when the user's balance would be exhausted.
    Caught by InferenceAdapter before any LLM call is dispatched.

    Attributes
    ----------
    user_id : str
    requested_credits : float
        Credits needed for this call (= estimated_cost_cents).
    available_credits : float
        Current user balance.
    """

    user_id:            str
    requested_credits:  float
    available_credits:  float

    def __str__(self) -> str:
        return (
            f"Insufficient credits for user '{self.user_id}': "
            f"need {self.requested_credits:.2f}¢, "
            f"have {self.available_credits:.2f}¢. "
            f"Top up at https://xace.dev/billing."
        )


# ── Config ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CreditConfig:
    """
    Configuration for the credit system.

    Attributes
    ----------
    ledger_path : str
        Path to the JSON ledger file. Created if it does not exist.
        Default: /var/xace/credits.json  (override for dev/test)
    base_credit_price_cents : float
        How many USD cents equal one credit.
        Default: 1.0  (1 credit = 1¢)
    low_balance_warn_threshold : float
        Emit a telemetry warning when user balance drops below this.
        Default: 100.0 credits (= $1.00)
    allow_negative_balance : bool
        If True, calls are allowed to proceed even when balance < 0.
        Use for grace-period / trial accounts.
        Default: False
    """

    ledger_path:                str   = "/var/xace/credits.json"
    base_credit_price_cents:    float = 1.0
    low_balance_warn_threshold: float = 100.0
    allow_negative_balance:     bool  = False


DEFAULT_CREDIT_CONFIG = CreditConfig()


# ── Ledger Record ─────────────────────────────────────────────────────────────

@dataclass
class _UserRecord:
    balance_credits:       float
    lifetime_spent_credits: float = 0.0
    created_at_epoch:      float  = field(default_factory=time.time)
    last_updated_epoch:    float  = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "balance_credits":        round(self.balance_credits, 6),
            "lifetime_spent_credits": round(self.lifetime_spent_credits, 6),
            "created_at_epoch":       self.created_at_epoch,
            "last_updated_epoch":     self.last_updated_epoch,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "_UserRecord":
        return cls(
            balance_credits        = float(d.get("balance_credits", 0.0)),
            lifetime_spent_credits = float(d.get("lifetime_spent_credits", 0.0)),
            created_at_epoch       = float(d.get("created_at_epoch", time.time())),
            last_updated_epoch     = float(d.get("last_updated_epoch", time.time())),
        )

    @classmethod
    def new(cls, initial_credits: float = 0.0) -> "_UserRecord":
        return cls(balance_credits=initial_credits)


# ── Credit System ─────────────────────────────────────────────────────────────

class CreditSystem:
    """
    Per-user credit accounting for XACE inference calls.

    One instance shared across InferenceAdapter calls.
    Thread-safe via RLock + file lock.

    Usage
    -----
        cs = CreditSystem(CreditConfig(ledger_path="./credits.json"))

        # Top up a user
        cs.add_credits("user_1", 1000.0)  # 1000 credits = $10

        # Before inference call (InferenceAdapter calls this)
        cs.check_credits("user_1", estimated_cost_cents=2.5)

        # After inference call (InferenceAdapter calls this)
        new_balance = cs.deduct_credits("user_1", actual_cost_cents=2.3)
    """

    def __init__(self, config: CreditConfig = DEFAULT_CREDIT_CONFIG) -> None:
        self._config = config
        self._lock   = threading.RLock()
        self._ensure_ledger_file()

    # ── Public API ────────────────────────────────────────────────────────────

    def check_credits(
        self,
        user_id:              str,
        estimated_cost_cents: float,
    ) -> None:
        """
        Checks whether the user has enough credits for a call.

        Does NOT deduct — call deduct_credits after the call completes.
        TIER_S calls (estimated_cost_cents=0.0) are always allowed.

        Raises
        ------
        InsufficientCreditsError
            If balance < estimated_cost and allow_negative_balance=False.
        """
        if estimated_cost_cents <= 0.0:
            return   # TIER_S or free call — always allow

        with self._lock:
            ledger = self._load()
            record = ledger.get(user_id, _UserRecord.new(0.0))
            if not self._config.allow_negative_balance:
                if record.balance_credits < estimated_cost_cents:
                    raise InsufficientCreditsError(
                        user_id           = user_id,
                        requested_credits = estimated_cost_cents,
                        available_credits = record.balance_credits,
                    )

    def deduct_credits(
        self,
        user_id:           str,
        actual_cost_cents: float,
    ) -> float:
        """
        Deducts actual call cost from the user's balance.
        Returns the new balance.
        TIER_S calls (actual_cost_cents=0.0) are no-ops.
        """
        if actual_cost_cents <= 0.0:
            return self.get_balance(user_id)

        with self._lock:
            ledger = self._load()
            record = ledger.get(user_id, _UserRecord.new(0.0))
            record.balance_credits         -= actual_cost_cents
            record.lifetime_spent_credits  += actual_cost_cents
            record.last_updated_epoch       = time.time()
            ledger[user_id]                 = record
            self._save(ledger)
            return record.balance_credits

    def get_balance(self, user_id: str) -> float:
        """Returns the current credit balance for a user (in credits = ¢)."""
        with self._lock:
            record = self._load().get(user_id, _UserRecord.new(0.0))
            return record.balance_credits

    def add_credits(self, user_id: str, credits: float) -> float:
        """
        Adds credits to a user's balance.
        Returns new balance.
        Creates the user record if it doesn't exist.
        """
        if credits < 0:
            raise ValueError(f"credits to add must be non-negative, got {credits}")
        with self._lock:
            ledger = self._load()
            record = ledger.get(user_id, _UserRecord.new(0.0))
            record.balance_credits    += credits
            record.last_updated_epoch  = time.time()
            ledger[user_id]            = record
            self._save(ledger)
            return record.balance_credits

    def set_balance(self, user_id: str, credits: float) -> None:
        """
        Sets a user's balance to an absolute value.
        Used for admin corrections or initial grants.
        """
        with self._lock:
            ledger = self._load()
            record = ledger.get(user_id, _UserRecord.new(0.0))
            record.balance_credits    = credits
            record.last_updated_epoch = time.time()
            ledger[user_id]           = record
            self._save(ledger)

    def lifetime_spent(self, user_id: str) -> float:
        """Returns total credits spent by a user over their lifetime."""
        with self._lock:
            return self._load().get(user_id, _UserRecord.new(0.0)).lifetime_spent_credits

    def is_low_balance(self, user_id: str) -> bool:
        """Returns True when balance is below the warn threshold."""
        return self.get_balance(user_id) < self._config.low_balance_warn_threshold

    def cost_to_credits(self, cost_cents: float) -> float:
        """Converts a USD cent cost to credits."""
        return cost_cents / self._config.base_credit_price_cents

    def user_exists(self, user_id: str) -> bool:
        with self._lock:
            return user_id in self._load()

    def all_users(self) -> list[str]:
        with self._lock:
            return list(self._load().keys())

    def user_summary(self, user_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._load().get(user_id)
            if record is None:
                return {"user_id": user_id, "exists": False}
            return {
                "user_id":               user_id,
                "exists":                True,
                "balance_credits":       record.balance_credits,
                "balance_usd":           record.balance_credits / 100.0,
                "lifetime_spent_credits": record.lifetime_spent_credits,
                "low_balance":           self._config.low_balance_warn_threshold >
                                         record.balance_credits > 0,
                "is_empty":              record.balance_credits <= 0,
            }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _ensure_ledger_file(self) -> None:
        path = Path(self._config.ledger_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            try:
                path.write_text("{}", encoding="utf-8")
            except OSError:
                pass

    def _load(self) -> dict[str, _UserRecord]:
        """Reads and parses the ledger file. Assumes _lock is held."""
        path = Path(self._config.ledger_path)
        try:
            raw  = self._read_locked(path)
            data = json.loads(raw or "{}")
            return {uid: _UserRecord.from_dict(rec) for uid, rec in data.items()}
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self, ledger: dict[str, _UserRecord]) -> None:
        """Writes the ledger atomically. Assumes _lock is held."""
        path    = Path(self._config.ledger_path)
        data    = {uid: rec.to_dict() for uid, rec in ledger.items()}
        payload = json.dumps(data, indent=2, ensure_ascii=True)
        # Atomic write via tmp file rename
        tmp = path.with_suffix(".tmp")
        try:
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(path)
        except OSError:
            pass

    @staticmethod
    def _read_locked(path: Path) -> str:
        """Reads a file with best-effort cross-process locking."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                if sys.platform != "win32":
                    try:
                        import fcntl
                        fcntl.flock(f, fcntl.LOCK_SH)
                    except ImportError:
                        pass
                return f.read()
        except OSError:
            return "{}"

    def __repr__(self) -> str:
        return f"CreditSystem(ledger={self._config.ledger_path!r})"