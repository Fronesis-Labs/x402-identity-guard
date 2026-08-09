"""Minimal in-memory TTL cache.

Deliberately not Redis/anything external for v1 — a single-process
in-memory cache is enough for one demo server, and swapping this out
for something shared is a v1.x concern, not a day-1 one.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass
class _Entry(Generic[T]):
    value: T
    expires_at: float


class TTLCache(Generic[T]):
    def __init__(self, ttl_seconds: float = 120.0):
        self._ttl = ttl_seconds
        self._store: dict[str, _Entry[T]] = {}

    def get(self, key: str) -> T | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        if entry.expires_at < time.monotonic():
            del self._store[key]
            return None
        return entry.value

    def set(self, key: str, value: T) -> None:
        self._store[key] = _Entry(value=value, expires_at=time.monotonic() + self._ttl)

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)
