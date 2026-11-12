"""A small in-memory token-bucket rate limiter (one bucket per key).

Good enough for a single-process demo server. Behind several processes, use a shared store.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

_PRUNE_AT = 5_000


class RateLimiter:
    def __init__(self, per_minute: int, clock: Callable[[], float] = time.monotonic) -> None:
        self._capacity = float(per_minute)
        self._refill_per_s = per_minute / 60.0
        self._clock = clock
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, last_seen)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """Take one token from ``key``'s bucket. False means the caller is going too fast."""
        now = self._clock()
        with self._lock:
            tokens, seen = self._buckets.get(key, (self._capacity, now))
            tokens = min(self._capacity, tokens + (now - seen) * self._refill_per_s)
            allowed = tokens >= 1.0
            self._buckets[key] = (tokens - 1.0 if allowed else tokens, now)
            if len(self._buckets) > _PRUNE_AT:
                self._prune(now)
            return allowed

    def _prune(self, now: float) -> None:
        full_after = self._capacity / self._refill_per_s if self._refill_per_s else 0.0
        for key in [k for k, (_, seen) in self._buckets.items() if now - seen > full_after]:
            del self._buckets[key]


class StreamLimiter:
    """Caps concurrent long-lived connections (live timelines): in total and per client."""

    def __init__(self, total: int, per_key: int) -> None:
        self._total, self._per_key = total, per_key
        self._open: dict[str, int] = {}
        self._lock = threading.Lock()

    def acquire(self, key: str) -> bool:
        with self._lock:
            if sum(self._open.values()) >= self._total or self._open.get(key, 0) >= self._per_key:
                return False
            self._open[key] = self._open.get(key, 0) + 1
            return True

    def release(self, key: str) -> None:
        with self._lock:
            remaining = self._open.get(key, 0) - 1
            if remaining > 0:
                self._open[key] = remaining
            else:
                self._open.pop(key, None)
