"""
byok_manager.py — BYOKManager
================================
Manages user-supplied API keys (Bring Your Own Key) for per-session
provider dispatch overrides.

## Status: Pre-Beta Placeholder
The interface is complete and wired into ProviderRegistry via BYOKOverride.
Encryption in this version is obfuscation-level (XOR + base64) — suitable
only for development and testing. Production requires:
    - Fernet symmetric encryption (cryptography library)
    - Or a KMS adapter (AWS KMS, Azure Key Vault, HashiCorp Vault)
    - At-rest encryption of the key store
    - Key rotation policy

When activating BYOK for production:
    1. Replace _encode_key() and _decode_key() with Fernet.encrypt/decrypt
    2. Set up a per-deployment Fernet key (from environment variable)
    3. Add rate limiting per user per provider
    4. Add audit logging for key access

## What BYOK Does
Without BYOK: all inference calls use the platform operator's API keys.
The operator pays. The user has no visibility into cost.

With BYOK: the user supplies their own Anthropic/OpenAI/DeepSeek API key.
InferenceAdapter dispatches using that key. The user pays their own provider
directly. Useful for:
    - Enterprise accounts with negotiated provider pricing
    - Users who prefer cost transparency
    - Users who want to use their own rate limits / quotas

## Key Lifecycle
    store_key(session_id, provider, api_key)  → validates format, stores
    get_key(session_id, provider)             → returns key if present
    get_override(session_id, provider)        → returns BYOKOverride for registry
    revoke_key(session_id, provider)          → removes one provider key
    revoke_session(session_id)               → removes all keys for a session
    session_end(session_id)                  → calls revoke_session + cleanup

## Key Validation
Basic format checks per provider (not a full auth check — that
happens when the first inference call is made with the key):
    anthropic : "sk-ant-" prefix, 40+ chars
    openai    : "sk-" prefix, 40+ chars
    deepseek  : any non-empty key, 20+ chars
    zai       : any non-empty key, 16+ chars
    minimax   : any non-empty key, 16+ chars

## Thread Safety
BYOKManager is thread-safe via RLock.
"""

from __future__ import annotations

import base64
import hashlib
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any


# ── Errors ────────────────────────────────────────────────────────────────────

class BYOKError(Exception):
    """Base error for BYOK operations."""

class InvalidAPIKeyError(BYOKError):
    """Raised when a supplied API key fails format validation."""

class KeyNotFoundError(BYOKError):
    """Raised when attempting to retrieve a key that doesn't exist."""


# ── Key Validation Patterns ───────────────────────────────────────────────────

@dataclass(frozen=True)
class KeySpec:
    """Validation spec for one provider's API key format."""
    provider:    str
    pattern:     re.Pattern
    min_length:  int
    description: str


_KEY_SPECS: dict[str, KeySpec] = {
    "anthropic": KeySpec(
        provider    = "anthropic",
        pattern     = re.compile(r'^sk-ant-[A-Za-z0-9\-_]+$'),
        min_length  = 40,
        description = "Anthropic API key (starts with 'sk-ant-')",
    ),
    "openai": KeySpec(
        provider    = "openai",
        pattern     = re.compile(r'^sk-[A-Za-z0-9\-_]+$'),
        min_length  = 40,
        description = "OpenAI API key (starts with 'sk-')",
    ),
    "deepseek": KeySpec(
        provider    = "deepseek",
        pattern     = re.compile(r'^[A-Za-z0-9\-_]+$'),
        min_length  = 20,
        description = "DeepSeek API key",
    ),
    "zai": KeySpec(
        provider    = "zai",
        pattern     = re.compile(r'^[A-Za-z0-9\-_.]+$'),
        min_length  = 16,
        description = "Z.AI (GLM) API key",
    ),
    "minimax": KeySpec(
        provider    = "minimax",
        pattern     = re.compile(r'^[A-Za-z0-9\-_.]+$'),
        min_length  = 16,
        description = "MiniMax API key",
    ),
}


# ── Stored Key Record ─────────────────────────────────────────────────────────

@dataclass
class StoredKey:
    """Internal record for one stored API key."""
    session_id:     str
    provider:       str
    encoded_key:    str       # obfuscated; NOT plaintext
    fingerprint:    str       # last 4 chars of key for display only
    stored_at:      float
    use_count:      int = 0
    last_used_at:   float = 0.0


# ── BYOK Override ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BYOKOverride:
    """
    Per-session provider override. Consumed by ProviderRegistry.get_client_for().
    See provider_registry.py for how this is applied.
    """
    session_id:  str
    provider:    str
    api_key:     str    # PLAINTEXT — only exists transiently in memory during dispatch
    model_id:    str = ""


# ── BYOK Manager ─────────────────────────────────────────────────────────────

class BYOKManager:
    """
    Manages user-supplied API keys for per-session provider overrides.

    Pre-beta: obfuscation-level key protection. See module docstring
    for production upgrade path.

    Usage
    -----
        manager = BYOKManager()

        # User provides their Anthropic key in the builder UI
        manager.store_key("session_abc", "anthropic", "sk-ant-...")

        # InferenceAdapter calls before routing
        override = manager.get_override("session_abc", "anthropic")
        if override:
            registry.register_byok(override)

        # Session ends
        manager.session_end("session_abc")
        registry.revoke_byok("session_abc")
    """

    def __init__(self, obfuscation_salt: str = "xace-byok-dev") -> None:
        self._salt   = obfuscation_salt.encode("utf-8")
        self._store: dict[str, dict[str, StoredKey]] = {}
        # {session_id → {provider → StoredKey}}
        self._lock   = threading.RLock()

    # ── Store / Retrieve ──────────────────────────────────────────────────────

    def store_key(
        self,
        session_id: str,
        provider:   str,
        api_key:    str,
    ) -> str:
        """
        Validates and stores one API key for a session.

        Returns the key fingerprint (last 4 chars) for UI confirmation.

        Raises
        ------
        InvalidAPIKeyError
            If the key fails format validation for the provider.
        """
        self._validate_key(provider, api_key)

        fingerprint  = api_key[-4:] if len(api_key) >= 4 else "****"
        encoded      = self._encode_key(api_key)

        with self._lock:
            if session_id not in self._store:
                self._store[session_id] = {}
            self._store[session_id][provider] = StoredKey(
                session_id  = session_id,
                provider    = provider,
                encoded_key = encoded,
                fingerprint = fingerprint,
                stored_at   = time.time(),
            )
        return fingerprint

    def has_key(self, session_id: str, provider: str) -> bool:
        """Returns True if a key exists for this session + provider."""
        with self._lock:
            return (
                session_id in self._store
                and provider in self._store[session_id]
            )

    def get_fingerprint(self, session_id: str, provider: str) -> str | None:
        """Returns the key fingerprint (safe for display) or None."""
        with self._lock:
            rec = self._store.get(session_id, {}).get(provider)
            return rec.fingerprint if rec else None

    def get_override(
        self,
        session_id: str,
        provider:   str,
        model_id:   str = "",
    ) -> BYOKOverride | None:
        """
        Returns a BYOKOverride for ProviderRegistry, or None if no key stored.
        The API key is decoded transiently — it is not stored in plaintext.
        """
        with self._lock:
            rec = self._store.get(session_id, {}).get(provider)
            if rec is None:
                return None
            decoded = self._decode_key(rec.encoded_key)
            rec.use_count    += 1
            rec.last_used_at  = time.time()
            return BYOKOverride(
                session_id = session_id,
                provider   = provider,
                api_key    = decoded,
                model_id   = model_id,
            )

    # ── Revocation ────────────────────────────────────────────────────────────

    def revoke_key(self, session_id: str, provider: str) -> bool:
        """Removes one provider's key. Returns True if it existed."""
        with self._lock:
            session_keys = self._store.get(session_id, {})
            existed = provider in session_keys
            session_keys.pop(provider, None)
            return existed

    def revoke_session(self, session_id: str) -> int:
        """Removes all keys for a session. Returns count removed."""
        with self._lock:
            keys = self._store.pop(session_id, {})
            return len(keys)

    def session_end(self, session_id: str) -> None:
        """Called on session end. Revokes all keys and cleans up."""
        self.revoke_session(session_id)

    # ── Introspection ─────────────────────────────────────────────────────────

    def active_sessions(self) -> list[str]:
        """Returns session IDs that have at least one stored key."""
        with self._lock:
            return [sid for sid, keys in self._store.items() if keys]

    def providers_for_session(self, session_id: str) -> list[str]:
        """Returns providers that have keys for a session."""
        with self._lock:
            return sorted(self._store.get(session_id, {}).keys())

    def summary(self) -> dict[str, Any]:
        """Returns a summary dict for admin/telemetry (no key material)."""
        with self._lock:
            return {
                "active_sessions": len(self.active_sessions()),
                "total_keys":      sum(
                    len(keys) for keys in self._store.values()
                ),
                "sessions": {
                    sid: [
                        {"provider": p, "fingerprint": rec.fingerprint,
                         "use_count": rec.use_count}
                        for p, rec in keys.items()
                    ]
                    for sid, keys in self._store.items()
                }
            }

    # ── Validation ────────────────────────────────────────────────────────────

    @staticmethod
    def _validate_key(provider: str, api_key: str) -> None:
        """
        Validates an API key format for the given provider.
        Does NOT check authentication — that happens on first use.
        """
        if not api_key or not api_key.strip():
            raise InvalidAPIKeyError(
                f"API key for provider '{provider}' must not be empty."
            )

        spec = _KEY_SPECS.get(provider)
        if spec is None:
            # Unknown provider — basic length check only
            if len(api_key) < 8:
                raise InvalidAPIKeyError(
                    f"API key for unknown provider '{provider}' is too short."
                )
            return

        if len(api_key) < spec.min_length:
            raise InvalidAPIKeyError(
                f"API key for '{provider}' is too short "
                f"(got {len(api_key)} chars, expected at least {spec.min_length}). "
                f"Expected format: {spec.description}"
            )

        if not spec.pattern.match(api_key):
            raise InvalidAPIKeyError(
                f"API key for '{provider}' has an unexpected format. "
                f"Expected: {spec.description}"
            )

    # ── Obfuscation ───────────────────────────────────────────────────────────
    # NOTE: This is obfuscation, NOT encryption. Keys are stored in memory
    # and XOR-obfuscated. DO NOT use for production without replacing this
    # with Fernet encryption backed by a secure keystore.

    def _encode_key(self, plaintext: str) -> str:
        """XOR obfuscation + base64 encoding. Dev/test only."""
        data  = plaintext.encode("utf-8")
        # Extend salt to match data length by repeating
        salt  = (self._salt * ((len(data) // len(self._salt)) + 1))[:len(data)]
        xored = bytes(b ^ s for b, s in zip(data, salt))
        return base64.b64encode(xored).decode("ascii")

    def _decode_key(self, encoded: str) -> str:
        """Reverses XOR obfuscation. Dev/test only."""
        xored = base64.b64decode(encoded.encode("ascii"))
        salt  = (self._salt * ((len(xored) // len(self._salt)) + 1))[:len(xored)]
        data  = bytes(b ^ s for b, s in zip(xored, salt))
        return data.decode("utf-8")

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"BYOKManager("
                f"sessions={len(self.active_sessions())}, "
                f"keys={sum(len(v) for v in self._store.values())})"
            )