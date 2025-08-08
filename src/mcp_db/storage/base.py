from __future__ import annotations

import typing as t
from abc import ABC, abstractmethod

from ..core.models import MCPSession, MCPEvent


class StorageAdapter(ABC):
    @abstractmethod
    async def create_session(self, session: MCPSession) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    @abstractmethod
    async def get_session(self, session_id: str) -> t.Optional[MCPSession]:  # pragma: no cover - interface
        raise NotImplementedError

    @abstractmethod
    async def update_session(self, session_id: str, updates: dict) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    @abstractmethod
    async def delete_session(self, session_id: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    @abstractmethod
    async def append_event(self, event: MCPEvent) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    @abstractmethod
    async def get_events(self, session_id: str, after_event_id: t.Optional[str] = None) -> t.AsyncIterator[MCPEvent]:  # pragma: no cover - interface
        raise NotImplementedError

    @abstractmethod
    async def acquire_lock(self, key: str, ttl_seconds: float) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    @abstractmethod
    async def release_lock(self, key: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    @abstractmethod
    async def is_healthy(self) -> bool:  # pragma: no cover - interface
        raise NotImplementedError


class InMemoryStorage(StorageAdapter):
    """A simple in-memory adapter for dev/test and as a resilience fallback.

    Not intended for production, but implements the same async interface.
    """

    def __init__(self) -> None:
        self._sessions: t.Dict[str, MCPSession] = {}
        self._events: t.Dict[str, t.List[MCPEvent]] = {}
        self._locks: t.Set[str] = set()

    async def create_session(self, session: MCPSession) -> None:
        self._sessions[session.id] = session
        self._events.setdefault(session.id, [])

    async def get_session(self, session_id: str) -> t.Optional[MCPSession]:
        return self._sessions.get(session_id)

    async def update_session(self, session_id: str, updates: dict) -> None:
        session = self._sessions.get(session_id)
        if not session:
            return
        for key, value in updates.items():
            setattr(session, key, value)

    async def delete_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        self._events.pop(session_id, None)

    async def append_event(self, event: MCPEvent) -> None:
        self._events.setdefault(event.session_id, []).append(event)

    async def get_events(self, session_id: str, after_event_id: t.Optional[str] = None) -> t.AsyncIterator[MCPEvent]:
        events = self._events.get(session_id, [])
        start_index = 0
        if after_event_id is not None:
            for idx, ev in enumerate(events):
                if ev.event_id == after_event_id:
                    start_index = idx + 1
                    break
        for ev in events[start_index:]:
            yield ev

    async def acquire_lock(self, key: str, ttl_seconds: float) -> bool:
        # Simplified non-expiring lock for in-memory usage.
        if key in self._locks:
            return False
        self._locks.add(key)
        return True

    async def release_lock(self, key: str) -> None:
        self._locks.discard(key)

    async def is_healthy(self) -> bool:
        return True


