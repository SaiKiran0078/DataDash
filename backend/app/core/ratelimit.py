"""Tiny in-memory sliding-window rate limiter (per process).

Good enough to slow down password guessing on a single instance. With several
instances, move the counters to Redis.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, max_calls: int, window_seconds: float, clock=time.monotonic):
        self.max_calls = max_calls
        self.window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self._clock()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] >= self.window:
                q.popleft()
            if len(q) >= self.max_calls:
                return False
            q.append(now)
            if not q:  # pragma: no cover
                del self._hits[key]
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
