"""Multi-key rotation with quota failover. Stdlib only.

A KeyPool spreads calls round-robin across equivalent API keys; any key
that reports quota exhaustion cools down (60s, doubling to 1h) and is
skipped until then. Thread-safe: UI background tasks share process pools.

Cooldown state is in-memory only (process lifetime). Server-side quotas
reset on their own schedule; persisting cooldowns to disk would go stale.
"""
from __future__ import annotations

import threading
import time

BASE_COOLDOWN = 60.0
MAX_COOLDOWN = 3600.0


def split_keys(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    """'k1, k2' -> ['k1', 'k2']. Single values, lists, and tuples pass through."""
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        parts = list(value)
    else:
        parts = str(value).split(",")
    return [str(p).strip() for p in parts if p and str(p).strip()]


def count_keys(value: str | list[str] | None) -> int:
    return len(split_keys(value))


def is_quota_error(err: Exception | None) -> bool:
    """Shared quota detector: numeric 429 code or rate-limit wording."""
    if err is None:
        return False
    if getattr(err, "code", None) == 429:
        return True
    low = str(err).lower()
    return ("429" in low or "quota" in low or "rate limit" in low
            or "too many requests" in low)


class KeyPool:
    """Round-robin pool with per-key quota cooldown. All methods thread-safe."""

    def __init__(self, keys: str | list[str] | None):
        self.keys = split_keys(keys)
        self._cooldown_until: dict[str, float] = {}
        self._backoff: dict[str, float] = {}
        self._cursor = 0
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self.keys)

    def __bool__(self) -> bool:
        return bool(self.keys)

    def _available(self, now: float) -> list[str]:
        return [k for k in self.keys if self._cooldown_until.get(k, 0.0) <= now]

    def next(self) -> str:
        """Next usable key (round-robin). If all cooling, the soonest to
        recover (caller decides whether to wait or fail)."""
        with self._lock:
            if not self.keys:
                raise ValueError("Key pool is empty.")
            now = time.monotonic()
            avail = self._available(now)
            if avail:
                key = avail[self._cursor % len(avail)]
                self._cursor += 1
                return key
            soonest = min(self.keys, key=lambda k: self._cooldown_until.get(k, now))
            self._cursor += 1
            return soonest

    def report_quota(self, key: str) -> None:
        """Mark key exhausted: cooldown doubles per consecutive hit (1h cap)."""
        with self._lock:
            prev = self._backoff.get(key, 0.0)
            wait = BASE_COOLDOWN if prev <= 0 else min(prev * 2, MAX_COOLDOWN)
            self._backoff[key] = wait
            self._cooldown_until[key] = time.monotonic() + wait

    def report_success(self, key: str) -> None:
        """Clear backoff after a good call."""
        with self._lock:
            self._backoff.pop(key, None)
            self._cooldown_until.pop(key, None)


# Process-global pools keyed by provider, rebuilt only when the key set
# changes (so cooldown state survives across calls in long-lived processes).
_POOLS: dict[str, tuple[tuple[str, ...], KeyPool]] = {}
_POOLS_LOCK = threading.Lock()


def get_pool(provider: str, keys: str | list[str] | None) -> KeyPool:
    wanted = tuple(split_keys(keys))
    with _POOLS_LOCK:
        cached = _POOLS.get(provider)
        if cached is not None and cached[0] == wanted:
            return cached[1]
        pool = KeyPool(list(wanted))
        _POOLS[provider] = (wanted, pool)
        return pool
