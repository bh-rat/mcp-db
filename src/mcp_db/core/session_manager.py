from __future__ import annotations

import typing as t

from mcp_db.cache.local_cache import LocalCache
from mcp_db.event.base import EventStore
from mcp_db.session import StorageAdapter
from mcp_db.utils.resilience import CircuitBreaker, CircuitBreakerConfig, with_retries

from .models import MCPEvent, MCPSession


class SessionManager:
    """Manages session lifecycle with caching, event sourcing, and resilience."""

    def __init__(
        self,
        storage: StorageAdapter,
        event_store: t.Optional[EventStore],
        use_local_cache: bool = True,
        local_cache: t.Optional[LocalCache] = None,
        circuit_breaker: t.Optional[CircuitBreaker] = None,
        retry_attempts: int = 3,
        retry_backoff_ms: t.Optional[t.List[int]] = None,
    ) -> None:
        self._storage = storage
        self._event_store = event_store
        # Only use cache if explicitly enabled
        if use_local_cache:
            self._cache = local_cache or LocalCache()
        else:
            self._cache = None
        self._breaker = circuit_breaker or CircuitBreaker(CircuitBreakerConfig())
        self._retry_attempts = retry_attempts
        self._retry_backoff_ms = retry_backoff_ms or [100, 500, 2000]

    async def create(self, session: MCPSession) -> None:
        async def _op() -> None:
            await self._storage.create_session(session)

        await self._breaker.run(lambda: with_retries(_op, self._retry_attempts, self._retry_backoff_ms))
        if self._cache:
            self._cache.set(session.id, session)

    async def get(self, session_id: str) -> t.Optional[MCPSession]:
        # Check local cache first if enabled
        if self._cache:
            cached = self._cache.get(session_id)
            if cached is not None:
                return cached

        async def _op() -> t.Optional[MCPSession]:
            return await self._storage.get_session(session_id)

        session = await self._breaker.run(lambda: with_retries(_op, self._retry_attempts, self._retry_backoff_ms))
        if session is not None and self._cache:
            self._cache.set(session_id, session)
        return session

    async def update(self, session_id: str, updates: dict) -> None:
        async def _op() -> None:
            await self._storage.update_session(session_id, updates)

        await self._breaker.run(lambda: with_retries(_op, self._retry_attempts, self._retry_backoff_ms))
        if self._cache:
            session = await self._storage.get_session(session_id)
            if session:
                self._cache.set(session_id, session)

    async def delete(self, session_id: str) -> None:
        async def _op() -> None:
            await self._storage.delete_session(session_id)

        await self._breaker.run(lambda: with_retries(_op, self._retry_attempts, self._retry_backoff_ms))
        if self._cache:
            self._cache.delete(session_id)

    async def append_event(self, event: MCPEvent) -> None:
        # No backward-compat event appending here; event replay handled by SDK EventStore in transports
        return

    async def recover(self, session_id: str) -> t.Optional[MCPSession]:
        """Reconstruct session state from events if not present in storage.

        Here, we simply return the stored session if it exists; a full implementation
        would apply events to rebuild projections.
        """
        session = await self.get(session_id)
        if session is not None:
            return session
        # Attempt event-based recovery (placeholder for now)
        # Legacy event-based recovery removed; rely on persisted sessions
        return await self.get(session_id)
