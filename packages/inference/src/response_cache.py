"""
response_cache.py — ResponseCache
=====================================
Deterministic output cache for LLM responses.

When the same intent is expressed against the same CGS in the same mode,
the model produces the same mutation transaction. The response cache
stores the model's text output and serves it on subsequent identical
requests — at zero cost.

## When Is a Cache Hit Valid?
A response is safe to serve from cache when:
    - The CGS structural hash matches (same game schema)
    - The intent class matches (same type of mutation)
    - The logical model name matches (same model capability set)
    - The cached entry has not expired (TTL not exceeded)

## When Is a Cache Hit INVALID?
    - CGS has changed since caching (structural_hash changed)
    - Intent is of a type that depends on runtime state (DebugIssue)
    - The session's assistance mode changed (may produce different verbosity)
    - The entry was explicitly invalidated

## Cache Architecture
Two backends:
    InMemoryResponseCache — fast, evicted on process restart.
                            Used in dev and for all TIER_M/TIER_S calls.
    FileResponseCache    — persists across restarts; suitable for
                            frequent prompts in long-lived server processes.

Default is InMemoryResponseCache with max_entries=1000 and TTL=3600s.

## LRU Eviction
When max_entries is reached, the least recently used entry is evicted.
This keeps the cache bounded regardless of project size.

## Thread Safety
All cache implementations are thread-safe.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any


# ── Cache Entry ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CacheEntry:
    """One stored response in the cache."""
    key:        str
    value:      str       # the model response text
    stored_at:  float     # unix timestamp
    ttl:        float     # seconds until expiry (0 = never)
    hit_count:  int = 0   # read counter (updated by InMemoryResponseCache)

    @property
    def is_expired(self) -> bool:
        if self.ttl <= 0:
            return False   # 0 = immortal entry
        return (time.time() - self.stored_at) > self.ttl

    def age_seconds(self) -> float:
        return time.time() - self.stored_at

    def __repr__(self) -> str:
        return (
            f"CacheEntry(key={self.key[:20]!r}…, "
            f"age={self.age_seconds():.0f}s, "
            f"hits={self.hit_count})"
        )


# ── Cache Stats ───────────────────────────────────────────────────────────────

@dataclass
class CacheStats:
    """Accumulated cache statistics."""
    hits:          int   = 0
    misses:        int   = 0
    evictions:     int   = 0
    expirations:   int   = 0
    entries:       int   = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return (self.hits / total) if total > 0 else 0.0

    def __repr__(self) -> str:
        return (
            f"CacheStats(hit_rate={self.hit_rate:.1%}, "
            f"hits={self.hits}, misses={self.misses}, "
            f"entries={self.entries})"
        )


# ── Cache Interface ───────────────────────────────────────────────────────────

class IResponseCache(ABC):
    """Interface for response cache backends."""

    @abstractmethod
    def get(self, key: str) -> str | None:
        """Returns the cached response text, or None on miss/expiry."""

    @abstractmethod
    def put(self, key: str, value: str) -> None:
        """Stores a response. Evicts LRU entry if at capacity."""

    @abstractmethod
    def invalidate(self, key: str) -> bool:
        """Removes one entry. Returns True if it existed."""

    @abstractmethod
    def invalidate_prefix(self, prefix: str) -> int:
        """Removes all entries whose key starts with prefix. Returns count removed."""

    @abstractmethod
    def stats(self) -> CacheStats:
        """Returns current cache statistics."""

    @abstractmethod
    def clear(self) -> None:
        """Removes all entries."""


# ── In-Memory Response Cache ──────────────────────────────────────────────────

class InMemoryResponseCache(IResponseCache):
    """
    LRU + TTL in-memory cache using OrderedDict.

    - O(1) get, put, evict (OrderedDict move_to_end is O(1))
    - Thread-safe via RLock
    - Bounded by max_entries (LRU eviction)
    - Entries expire after ttl seconds (0 = no expiry)

    Usage
    -----
        cache = InMemoryResponseCache(max_entries=500, default_ttl=3600.0)
        cache.put("SetValue:standard_mutation:a3f2bc7d", response_text)
        text  = cache.get("SetValue:standard_mutation:a3f2bc7d")
    """

    def __init__(
        self,
        max_entries:  int   = 1000,
        default_ttl:  float = 3600.0,   # 1 hour
    ) -> None:
        self._max_entries  = max_entries
        self._default_ttl  = default_ttl
        self._data:  OrderedDict[str, CacheEntry] = OrderedDict()
        self._stats: CacheStats                   = CacheStats()
        self._lock   = threading.RLock()

    # ── IResponseCache ────────────────────────────────────────────────────────

    def get(self, key: str) -> str | None:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self._stats.misses += 1
                return None

            if entry.is_expired:
                del self._data[key]
                self._stats.expirations += 1
                self._stats.misses      += 1
                self._stats.entries      = len(self._data)
                return None

            # Move to end (most recently used)
            self._data.move_to_end(key)

            # Update hit count (replace frozen entry with incremented one)
            updated = CacheEntry(
                key=entry.key, value=entry.value,
                stored_at=entry.stored_at, ttl=entry.ttl,
                hit_count=entry.hit_count + 1,
            )
            self._data[key] = updated
            self._stats.hits += 1
            return entry.value

    def put(self, key: str, value: str) -> None:
        if not value or not value.strip():
            return   # never cache empty/error responses

        with self._lock:
            # If key exists, update in-place and move to end
            if key in self._data:
                self._data.move_to_end(key)

            entry = CacheEntry(
                key       = key,
                value     = value,
                stored_at = time.time(),
                ttl       = self._default_ttl,
            )
            self._data[key] = entry
            self._data.move_to_end(key)

            # Evict LRU if over capacity
            while len(self._data) > self._max_entries:
                self._data.popitem(last=False)  # pop oldest (least recently used)
                self._stats.evictions += 1

            self._stats.entries = len(self._data)

    def invalidate(self, key: str) -> bool:
        with self._lock:
            existed = key in self._data
            self._data.pop(key, None)
            self._stats.entries = len(self._data)
            return existed

    def invalidate_prefix(self, prefix: str) -> int:
        with self._lock:
            to_remove = [k for k in self._data if k.startswith(prefix)]
            for k in to_remove:
                del self._data[k]
            self._stats.entries = len(self._data)
            return len(to_remove)

    def stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(
                hits        = self._stats.hits,
                misses      = self._stats.misses,
                evictions   = self._stats.evictions,
                expirations = self._stats.expirations,
                entries     = len(self._data),
            )

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._stats = CacheStats()

    # ── Introspection ─────────────────────────────────────────────────────────

    def all_keys(self) -> list[str]:
        with self._lock:
            return list(self._data.keys())

    def entry_count(self) -> int:
        with self._lock:
            return len(self._data)

    def oldest_entry(self) -> CacheEntry | None:
        with self._lock:
            if not self._data:
                return None
            return next(iter(self._data.values()))

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"InMemoryResponseCache("
                f"entries={len(self._data)}/{self._max_entries}, "
                f"hit_rate={self._stats.hit_rate:.1%})"
            )


# ── File Response Cache ───────────────────────────────────────────────────────

class FileResponseCache(IResponseCache):
    """
    File-backed response cache using a JSON store.
    Persists across process restarts. Suitable for long-lived servers.

    Writes are synchronous (immediate consistency).
    Reads are served from memory (loaded on init or first access).
    Background compaction removes expired entries on load.
    """

    def __init__(
        self,
        file_path:    str,
        max_entries:  int   = 2000,
        default_ttl:  float = 86400.0,   # 24 hours
    ) -> None:
        self._file       = file_path
        self._max        = max_entries
        self._ttl        = default_ttl
        self._lock       = threading.RLock()
        self._data:      OrderedDict[str, CacheEntry] = OrderedDict()
        self._stats:     CacheStats                   = CacheStats()
        self._dirty:     bool                         = False
        self._load()

    def get(self, key: str) -> str | None:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self._stats.misses += 1
                return None
            if entry.is_expired:
                del self._data[key]
                self._stats.expirations += 1
                self._stats.misses      += 1
                self._dirty = True
                return None
            self._data.move_to_end(key)
            self._stats.hits += 1
            return entry.value

    def put(self, key: str, value: str) -> None:
        if not value or not value.strip():
            return
        with self._lock:
            self._data[key] = CacheEntry(
                key=key, value=value, stored_at=time.time(), ttl=self._ttl
            )
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)
                self._stats.evictions += 1
            self._dirty = True
            self._flush()

    def invalidate(self, key: str) -> bool:
        with self._lock:
            existed = key in self._data
            self._data.pop(key, None)
            if existed:
                self._dirty = True
                self._flush()
            return existed

    def invalidate_prefix(self, prefix: str) -> int:
        with self._lock:
            keys = [k for k in self._data if k.startswith(prefix)]
            for k in keys:
                del self._data[k]
            if keys:
                self._dirty = True
                self._flush()
            return len(keys)

    def stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(
                hits=self._stats.hits, misses=self._stats.misses,
                evictions=self._stats.evictions, expirations=self._stats.expirations,
                entries=len(self._data),
            )

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._stats = CacheStats()
            self._flush()

    def _load(self) -> None:
        try:
            if not os.path.exists(self._file):
                return
            with open(self._file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            for key, rec in raw.items():
                entry = CacheEntry(
                    key=key, value=rec["v"],
                    stored_at=rec["t"], ttl=rec.get("ttl", self._ttl),
                )
                if not entry.is_expired:
                    self._data[key] = entry
        except (OSError, json.JSONDecodeError, KeyError):
            pass  # corrupt file → start fresh

    def _flush(self) -> None:
        try:
            payload = {
                k: {"v": e.value, "t": e.stored_at, "ttl": e.ttl}
                for k, e in self._data.items()
            }
            tmp = self._file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, separators=(",", ":"))
            os.replace(tmp, self._file)
            self._dirty = False
        except OSError:
            pass


# ── Public ResponseCache façade ───────────────────────────────────────────────

class ResponseCache:
    """
    Public façade used by InferenceAdapter.
    Wraps an IResponseCache backend with skip-cache logic for
    response types that must never be cached.

    Usage
    -----
        cache = ResponseCache()           # default in-memory
        cache = ResponseCache(FileResponseCache("/var/xace/resp_cache.json"))

        text = cache.get(key)
        if text:
            return cached_response(text)
        response = call_model(...)
        cache.put(key, response.text)
    """

    # Intent types whose responses must NOT be cached
    # (diagnostic, debug, and unknown intents depend on runtime state)
    _NEVER_CACHE_INTENTS = frozenset({
        "DebugIssue", "QueryExplain", "Unknown",
    })

    def __init__(
        self,
        backend: IResponseCache | None = None,
    ) -> None:
        self._backend = backend or InMemoryResponseCache()

    def get(self, key: str) -> str | None:
        """Returns cached response text or None."""
        if not key:
            return None
        return self._backend.get(key)

    def put(self, key: str, value: str) -> None:
        """
        Stores a response. Skips storage for empty or error responses.
        Checks the key's intent class component to skip non-cacheable types.
        """
        if not key or not value or not value.strip():
            return
        # Check intent class from key prefix
        intent_class = key.split(":")[0] if ":" in key else ""
        if intent_class in self._NEVER_CACHE_INTENTS:
            return
        self._backend.put(key, value)

    def invalidate(self, key: str) -> bool:
        return self._backend.invalidate(key)

    def invalidate_for_cgs(self, structural_hash_prefix: str) -> int:
        """
        Invalidates all cache entries for a given CGS structural hash prefix.
        Call after any CGS mutation is committed to evict stale entries.
        The hash prefix is the last component of the cache key.
        """
        # Keys are: {intent}:{model}:{hash_prefix}
        # We search for keys ending with :{hash_prefix}
        count = 0
        for key in self._backend.all_keys() if hasattr(self._backend, "all_keys") else []:
            if key.endswith(f":{structural_hash_prefix}"):
                self._backend.invalidate(key)
                count += 1
        return count

    def stats(self) -> CacheStats:
        return self._backend.stats()

    def clear(self) -> None:
        self._backend.clear()

    def __repr__(self) -> str:
        return f"ResponseCache(backend={self._backend!r})"