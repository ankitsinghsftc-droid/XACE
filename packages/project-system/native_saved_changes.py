"""Host-only saved-revision batching; never authorizes or publishes a change.

Restart discards notification state and requires fresh observations. Canonical and
native source bytes remain authoritative. A notification is not a review token.
"""
import math
import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class SavedRevision:
    cgs: str
    native: str
    mapping: str

    def __post_init__(self):
        for value in (self.cgs, self.native, self.mapping):
            if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
                raise ValueError('Saved revision requires SHA256 identities')


class SavedChangeBatcher:
    def __init__(self, quiet_seconds=0.5):
        if type(quiet_seconds) not in (int, float) or not math.isfinite(quiet_seconds) or quiet_seconds <= 0:
            raise ValueError('Positive finite quiet interval required')
        self.quiet_seconds = quiet_seconds
        self._candidate = None
        self._since = None
        self._last_time = None
        self._notified = None
        self._lock = threading.RLock()

    def invalidate(self):
        with self._lock:
            self._candidate = None
            self._since = None

    def observe(self, revision, now):
        if type(revision) is not SavedRevision:
            raise ValueError('Typed saved revision required')
        if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
            raise ValueError('Finite monotonic time required')
        with self._lock:
            if self._last_time is not None and now < self._last_time:
                self.invalidate()
                raise ValueError('Observation clock moved backwards')
            self._last_time = now
            if revision != self._candidate:
                self._candidate, self._since = revision, now
                return 'waiting'
            if now - self._since < self.quiet_seconds:
                return 'waiting'
            if revision == self._notified:
                return 'unchanged'
            self._notified = revision
            return 'review_available'
