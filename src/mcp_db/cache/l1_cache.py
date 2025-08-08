from __future__ import annotations

import time
import typing as t
from collections import OrderedDict


class TTLCache:
    """Simple LRU + TTL cache for per-instance L1.

    No external deps; suitable for small working sets.
    """

    def __init__(self, max_size: int = 1000, ttl_seconds: float = 60.0) -> None:
        self._store: "OrderedDict[str, tuple[float, t.Any]]" = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl_seconds

    def get(self, key: str) -> t.Optional[t.Any]:
        now = time.time()
        item = self._store.get(key)
        if item is None:
            return None
        expires_at, value = item
        if expires_at < now:
            self._store.pop(key, None)
            return None
        # mark as recently used
        self._store.move_to_end(key)
        return value

    def set(self, key: str, value: t.Any, ttl_seconds: t.Optional[float] = None) -> None:
        ttl = self._ttl if ttl_seconds is None else ttl_seconds
        expires_at = time.time() + ttl
        self._store[key] = (expires_at, value)
        self._store.move_to_end(key)
        if len(self._store) > self._max_size:
            # evict LRU
            self._store.popitem(last=False)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()


