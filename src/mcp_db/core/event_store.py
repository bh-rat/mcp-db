from __future__ import annotations

import typing as t

from mcp_db.storage import StorageAdapter

from .models import MCPEvent


class EventStore:
    """Thin wrapper providing event sourcing operations over a storage adapter."""

    def __init__(self, storage: StorageAdapter) -> None:
        self._storage = storage

    async def append(self, event: MCPEvent) -> None:
        await self._storage.append_event(event)

    async def stream(self, session_id: str, after_event_id: t.Optional[str] = None) -> t.AsyncIterator[MCPEvent]:
        async for event in self._storage.get_events(session_id, after_event_id=after_event_id):
            yield event
