"""A minimal in-process fixed-window rate limiter for auth endpoints.

This is an application-level *floor*, not a distributed anti-abuse platform:
production still fronts these endpoints with a reverse-proxy / WAF (documented in
the Phase 8 architecture notes). State is per-process and best-effort; it exists so
a single instance cannot be trivially brute-forced.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict


class RateLimiter:
    def __init__(self, max_attempts: int, window_seconds: int) -> None:
        self._max = max_attempts
        self._window = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def check(self, identifier: str) -> bool:
        """Record an attempt; return True if allowed, False if over the limit."""
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            hits = [t for t in self._hits[identifier] if t > cutoff]
            if len(hits) >= self._max:
                self._hits[identifier] = hits
                return False
            hits.append(now)
            self._hits[identifier] = hits
            return True

    def reset(self, identifier: str) -> None:
        with self._lock:
            self._hits.pop(identifier, None)
