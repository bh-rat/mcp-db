from __future__ import annotations

import json
import time
from typing import Optional

from redis.asyncio import Redis

from .base import EventStore
from .types import EventCallback, EventId, EventMessage, JSONRPCMessage, StreamId


class RedisEventStore(EventStore):
    def __init__(self, url: str = "redis://localhost:6379/0", prefix: str = "mcp") -> None:
        self._client = Redis.from_url(url)
        self._prefix = prefix

    def _stream_key(self, stream_id: StreamId) -> str:
        return f"{self._prefix}:events:{stream_id}"

    def _index_key(self) -> str:
        return f"{self._prefix}:event_index"

    async def store_event(self, stream_id: StreamId, message: JSONRPCMessage) -> EventId:
        message_dict = (
            message.model_dump(by_alias=True, exclude_none=True) if hasattr(message, "model_dump") else dict(message)
        )  # type: ignore
        payload = json.dumps(message_dict)
        ts = int(time.time() * 1000)
        fields = {"message": payload, "ts": str(ts)}
        event_id: EventId = await self._client.xadd(self._stream_key(stream_id), fields)  # type: ignore
        await self._client.hset(self._index_key(), event_id, stream_id)
        return event_id

    async def replay_events_after(self, last_event_id: EventId, send_callback: EventCallback) -> StreamId | None:
        stream_id: Optional[StreamId] = await self._client.hget(self._index_key(), last_event_id)  # type: ignore
        if not stream_id:
            return None
        stream_id_str = stream_id.decode() if isinstance(stream_id, (bytes, bytearray)) else str(stream_id)
        stream_key = self._stream_key(stream_id_str)
        # Start strictly after last_event_id per SSE semantics
        rows = await self._client.xrange(stream_key, min=f"({last_event_id}", max="+")  # type: ignore
        for eid, data in rows:
            payload = data.get(b"message") if isinstance(data, dict) else data["message"]
            msg_json = payload.decode() if isinstance(payload, (bytes, bytearray)) else payload
            msg_dict = json.loads(msg_json)
            message = (
                JSONRPCMessage.model_validate(msg_dict)
                if hasattr(JSONRPCMessage, "model_validate")
                else JSONRPCMessage(**msg_dict)
            )  # type: ignore
            await send_callback(
                EventMessage(message, eid.decode() if isinstance(eid, (bytes, bytearray)) else str(eid))
            )
        return stream_id_str
