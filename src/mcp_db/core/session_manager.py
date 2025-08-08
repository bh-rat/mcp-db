from __future__ import annotations

import typing as t

from .models import MCPSession, SessionStatus, MCPEvent
from .event_store import EventStore
from ..cache.l1_cache import TTLCache
from ..storage import StorageAdapter
from ..utils.resilience import CircuitBreaker, CircuitBreakerConfig, with_retries


class SessionManager:
    """Manages session lifecycle with caching, event sourcing, and resilience."""

    def __init__(
        self,
        storage: StorageAdapter,
        event_store: EventStore,
        l1_cache: t.Optional[TTLCache] = None,
        circuit_breaker: t.Optional[CircuitBreaker] = None,
        retry_attempts: int = 3,
        retry_backoff_ms: t.Optional[t.List[int]] = None,
    ) -> None:
        self._storage = storage
        self._event_store = event_store
        self._cache = l1_cache or TTLCache()
        self._breaker = circuit_breaker or CircuitBreaker(CircuitBreakerConfig())
        self._retry_attempts = retry_attempts
        self._retry_backoff_ms = retry_backoff_ms or [100, 500, 2000]

    async def create(self, session: MCPSession) -> None:
        async def _op() -> None:
            await self._storage.create_session(session)
        await self._breaker.run(lambda: with_retries(_op, self._retry_attempts, self._retry_backoff_ms))
        self._cache.set(session.id, session)

    async def get(self, session_id: str) -> t.Optional[MCPSession]:
        cached = self._cache.get(session_id)
        if cached is not None:
            return cached

        async def _op() -> t.Optional[MCPSession]:
            return await self._storage.get_session(session_id)

        session = await self._breaker.run(lambda: with_retries(_op, self._retry_attempts, self._retry_backoff_ms))
        if session is not None:
            self._cache.set(session_id, session)
        return session

    async def update(self, session_id: str, updates: dict) -> None:
        async def _op() -> None:
            await self._storage.update_session(session_id, updates)
        await self._breaker.run(lambda: with_retries(_op, self._retry_attempts, self._retry_backoff_ms))
        session = await self._storage.get_session(session_id)
        if session:
            self._cache.set(session_id, session)

    async def delete(self, session_id: str) -> None:
        async def _op() -> None:
            await self._storage.delete_session(session_id)
        await self._breaker.run(lambda: with_retries(_op, self._retry_attempts, self._retry_backoff_ms))
        self._cache.delete(session_id)

    async def append_event(self, event: MCPEvent) -> None:
        async def _op() -> None:
            await self._event_store.append(event)
        await self._breaker.run(lambda: with_retries(_op, self._retry_attempts, self._retry_backoff_ms))

    async def recover(self, session_id: str) -> t.Optional[MCPSession]:
        """Reconstruct session state from events if not present in storage.

        Here, we simply return the stored session if it exists; a full implementation
        would apply events to rebuild projections.
        """
        session = await self.get(session_id)
        if session is not None:
            return session
        # Attempt event-based recovery (placeholder for now)
        async for _ in self._event_store.stream(session_id):
            pass
        return await self.get(session_id)


