"""In-memory rate limiting, short TTL quote caching, and credential safety guards."""
from __future__ import annotations

import hashlib
import time
from collections import deque
from collections.abc import Iterable, Mapping
from threading import Lock
from typing import Any


class SlidingWindowLimiter:
    """Thread-safe per-key sliding-window rate limiter."""

    def __init__(self, max_requests: int = 30, window_seconds: float = 60.0):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = Lock()

    def allow(self, key: str, now: float | None = None) -> tuple[bool, int]:
        ts = time.monotonic() if now is None else now
        cutoff = ts - self.window_seconds
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self.max_requests:
                retry_after = max(1, int(self.window_seconds - (ts - bucket[0])) + 1)
                return False, retry_after
            bucket.append(ts)
            if len(self._hits) > 2048:
                stale = [k for k, dq in self._hits.items() if not dq or dq[-1] <= cutoff]
                for k in stale:
                    del self._hits[k]
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


class QuoteTTLCache:
    """Short-lived in-memory quote cache to avoid hammering provider APIs."""

    def __init__(self, ttl_seconds: float = 45.0, max_entries: int = 256):
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._store: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._lock = Lock()

    @staticmethod
    def build_key(
        pickup: dict[str, Any] | None,
        drop: dict[str, Any] | None,
        env_fingerprint: str,
    ) -> str | None:
        if not (pickup and drop and pickup.get("lat") is not None and drop.get("lat") is not None):
            return None
        return (
            f"{round(float(pickup['lat']), 4)}:{round(float(pickup['lng']), 4)}->"
            f"{round(float(drop['lat']), 4)}:{round(float(drop['lng']), 4)}|{env_fingerprint}"
        )

    @staticmethod
    def env_fingerprint(env: Mapping[str, str], keys: Iterable[str]) -> str:
        raw = "|".join(f"{k}={env.get(k, '')}" for k in sorted(keys))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]

    def get(self, key: str | None, now: float | None = None) -> list[dict[str, Any]] | None:
        if key is None or self.ttl_seconds <= 0:
            return None
        ts = time.monotonic() if now is None else now
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            expires_at, data = entry
            if ts >= expires_at:
                del self._store[key]
                return None
            return [dict(item) for item in data]

    def set(self, key: str | None, quotes: list[dict[str, Any]], now: float | None = None) -> None:
        if key is None or self.ttl_seconds <= 0:
            return
        # Only cache responses that include at least one live/estimate quote to avoid sticky failures.
        if not any(q.get("quoteType") in {"LIVE_QUOTE", "FARE_ESTIMATE"} for q in quotes):
            return
        ts = time.monotonic() if now is None else now
        with self._lock:
            if len(self._store) >= self.max_entries:
                oldest = min(self._store, key=lambda k: self._store[k][0])
                del self._store[oldest]
            self._store[key] = (ts + self.ttl_seconds, [dict(item) for item in quotes])

    def reset(self) -> None:
        with self._lock:
            self._store.clear()
