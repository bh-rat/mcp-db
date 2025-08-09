from __future__ import annotations

import json
import typing as t
from dataclasses import asdict

from mcp_db.core.models import MCPEvent, MCPSession

from .base import StorageAdapter

# Prefer redis.asyncio (modern) and fall back to aioredis for compatibility
_redis_lib: t.Any | None = None
try:  # Modern redis-py asyncio interface
    import redis.asyncio as _redis_lib  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    try:
        import aioredis as _redis_lib  # type: ignore
    except Exception:
        _redis_lib = None


class RedisStorage(StorageAdapter):
    """Redis-backed storage adapter.

    - Sessions are stored as JSON strings at key: `{prefix}:session:{id}`
    - Events are stored in Redis Streams at key: `{prefix}:events:{session_id}`
    - Locks use `SET NX PX` with key: `{prefix}:lock:{key}`
    """

    def __init__(
        self,
        url: str = "redis://localhost:6379/0",
        *,
        prefix: str = "mcp",
        stream_maxlen: int | None = None,
    ) -> None:
        if _redis_lib is None:  # pragma: no cover
            raise ImportError("Redis asyncio client is required. Install with: pip install redis (or aioredis)")
        self._url = url
        self._prefix = prefix.rstrip(":")
        self._stream_maxlen = stream_maxlen
        # Both redis.asyncio and aioredis expose from_url
        self._redis = _redis_lib.from_url(url, decode_responses=True)

    def _session_key(self, session_id: str) -> str:
        return f"{self._prefix}:session:{session_id}"

    def _events_key(self, session_id: str) -> str:
        return f"{self._prefix}:events:{session_id}"

    def _lock_key(self, key: str) -> str:
        return f"{self._prefix}:lock:{key}"

    async def create_session(self, session: MCPSession) -> None:
        payload = json.dumps(asdict(session))
        await self._redis.set(self._session_key(session.id), payload)

    async def get_session(self, session_id: str) -> t.Optional[MCPSession]:
        raw = await self._redis.get(self._session_key(session_id))
        if raw is None:
            return None
        data = json.loads(raw)
        return MCPSession(**data)

    async def update_session(self, session_id: str, updates: dict) -> None:
        key = self._session_key(session_id)
        raw = await self._redis.get(key)
        if raw is None:
            return
        data = json.loads(raw)
        data.update(updates)
        await self._redis.set(key, json.dumps(data))

    async def delete_session(self, session_id: str) -> None:
        await self._redis.delete(self._session_key(session_id))
        await self._redis.delete(self._events_key(session_id))

    async def append_event(self, event: MCPEvent) -> None:
        key = self._events_key(event.session_id)
        entry = {
            "event": json.dumps(asdict(event)),
            "event_id": event.event_id,
        }
        # Ensure stream key exists by creating the session stream bucket if needed
        if self._stream_maxlen is not None:
            await self._redis.xadd(key, entry, maxlen=self._stream_maxlen, approximate=True)
        else:
            await self._redis.xadd(key, entry)

    async def get_events(self, session_id: str, after_event_id: t.Optional[str] = None) -> t.AsyncIterator[MCPEvent]:
        key = self._events_key(session_id)
        start = "-"
        if after_event_id is not None:
            # We need to find the first entry after an event with matching event_id field.
            # Since Redis Streams query by stream IDs, we scan forward and filter by our event_id field.
            # For simplicity, do a range and filter in memory in batches.
            last_id = "-"
            # Initial scan to locate the stream ID after the target event_id
            while True:
                entries = await self._redis.xrange(key, min=last_id, max="+", count=100)
                if not entries:
                    break
                for sid, fields in entries:
                    if fields.get("event_id") == after_event_id:
                        start = sid  # start from this stream id
                        break
                if start != "-" and start != last_id:
                    break
                last_id = entries[-1][0]
            # Begin from the next stream id strictly after the found one
            if start != "-":
                # Redis streams use `(id` syntax to mean exclusive
                start = f"({start}"

        # Stream forward from `start`
        last = start
        while True:
            entries = await self._redis.xrange(key, min=last, max="+", count=100)
            if not entries:
                break
            for sid, fields in entries:
                data_raw = fields.get("event")
                if not data_raw:
                    continue
                data = json.loads(data_raw)
                # Ensure event_id is set (prefer stored value)
                data["event_id"] = fields.get("event_id", data.get("event_id", sid))
                # Coerce to dataclass
                yield MCPEvent(**data)
            last = entries[-1][0]

    async def acquire_lock(self, key: str, ttl_seconds: float) -> bool:
        ttl_ms = int(ttl_seconds * 1000)
        ok = await self._redis.set(self._lock_key(key), "1", nx=True, px=ttl_ms)
        return bool(ok)

    async def release_lock(self, key: str) -> None:
        await self._redis.delete(self._lock_key(key))

    async def is_healthy(self) -> bool:
        try:
            pong = await self._redis.ping()
            return bool(pong)
        except Exception:
            return False

    async def close(self) -> None:  # pragma: no cover - convenience
        try:
            await self._redis.close()
        except Exception:
            pass
