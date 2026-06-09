"""Hot state — current best lines and alert throttling.

Backed by Redis when reachable (so state survives restarts and can be shared
across processes), with a transparent in-process fallback so the system runs in
development and single-process deployments without Redis (proposal §4.5).

The hot store holds nothing that needs to be durable — it is a cache and a
throttle. Durable truth lives in DuckDB (:mod:`middler.store.history`).
"""

from __future__ import annotations

import json
import time
from typing import Any

from middler.logging_setup import get_logger

log = get_logger(__name__)


class _MemoryBackend:
    """A tiny TTL key-value store used when Redis is unavailable."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[float | None, str]] = {}

    def _expired(self, key: str) -> bool:
        item = self._data.get(key)
        if item is None:
            return True
        expiry, _ = item
        if expiry is not None and time.monotonic() > expiry:
            del self._data[key]
            return True
        return False

    def set_nx_ex(self, key: str, value: str, ttl_sec: int) -> bool:
        if not self._expired(key):
            return False
        self._data[key] = (time.monotonic() + ttl_sec, value)
        return True

    def set_ex(self, key: str, value: str, ttl_sec: int | None) -> None:
        expiry = time.monotonic() + ttl_sec if ttl_sec else None
        self._data[key] = (expiry, value)

    def get(self, key: str) -> str | None:
        if self._expired(key):
            return None
        return self._data[key][1]


class HotStore:
    """Current-state cache and alert throttle, Redis-backed with memory fallback."""

    def __init__(self, redis_url: str | None = None) -> None:
        """Connect to Redis if possible, otherwise use the in-memory backend.

        Args:
            redis_url: A ``redis://`` URL, or None / unreachable to force memory.
        """
        self._redis: Any | None = None
        if redis_url:
            try:
                import redis

                client = redis.Redis.from_url(redis_url, decode_responses=True)
                client.ping()
                self._redis = client
                log.info("hot store: using Redis at %s", redis_url)
            except Exception as exc:  # noqa: BLE001 - any failure means fall back
                log.warning("hot store: Redis unavailable (%s); using in-memory backend", exc)
        if self._redis is None:
            self._memory = _MemoryBackend()
            log.info("hot store: using in-memory backend")

    @property
    def backend(self) -> str:
        """Return ``"redis"`` or ``"memory"`` — useful for healthchecks/tests."""
        return "redis" if self._redis is not None else "memory"

    def should_alert(self, signature: str, cooldown_sec: int = 1800) -> bool:
        """Return True at most once per ``cooldown_sec`` for a given signature.

        Used to avoid re-alerting on the same structural opportunity every poll.

        Args:
            signature: The opportunity signature (see :attr:`Opportunity.signature`).
            cooldown_sec: Suppression window in seconds.

        Returns:
            True if this is the first time the signature has been seen within the
            window (i.e. an alert should fire), False otherwise.
        """
        key = f"alert:{signature}"
        if self._redis is not None:
            # SET key value NX EX ttl → truthy only if the key was newly set.
            return bool(self._redis.set(key, "1", nx=True, ex=cooldown_sec))
        return self._memory.set_nx_ex(key, "1", cooldown_sec)

    def set_json(self, key: str, obj: Any, ttl_sec: int | None = None) -> None:
        """Store a JSON-serialisable object under a key with an optional TTL."""
        payload = json.dumps(obj, default=str)
        if self._redis is not None:
            self._redis.set(key, payload, ex=ttl_sec)
        else:
            self._memory.set_ex(key, payload, ttl_sec)

    def get_json(self, key: str) -> Any | None:
        """Fetch and decode a JSON object stored under a key, or None."""
        raw = self._redis.get(key) if self._redis is not None else self._memory.get(key)
        return json.loads(raw) if raw else None
