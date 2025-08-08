from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Iterable, List, Optional, TypeVar

T = TypeVar("T")


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5
    reset_timeout_seconds: float = 30.0


class CircuitState:
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(self, config: Optional[CircuitBreakerConfig] = None) -> None:
        self._config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._opened_at = 0.0

    def _can_attempt(self) -> bool:
        if self._state == CircuitState.CLOSED:
            return True
        if self._state == CircuitState.OPEN:
            if (time.time() - self._opened_at) >= self._config.reset_timeout_seconds:
                self._state = CircuitState.HALF_OPEN
                return True
            return False
        if self._state == CircuitState.HALF_OPEN:
            return True
        return True

    def _on_success(self) -> None:
        self._state = CircuitState.CLOSED
        self._failures = 0

    def _on_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._config.failure_threshold:
            self._state = CircuitState.OPEN
            self._opened_at = time.time()

    async def run(self, fn: Callable[[], Awaitable[T]]) -> T:
        if not self._can_attempt():
            raise RuntimeError("circuit_open")
        try:
            result = await fn()
        except Exception:
            self._on_failure()
            raise
        else:
            self._on_success()
            return result


async def with_retries(
    coro_factory: Callable[[], Awaitable[T]],
    attempts: int = 3,
    backoff_ms: Optional[Iterable[int]] = None,
) -> T:
    backoff_seq: List[int] = list(backoff_ms or [100, 500, 2000])
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return await coro_factory()
        except Exception as exc:  # noqa: BLE001 - broad for retry wrapper
            last_exc = exc
            if attempt == attempts - 1:
                break
            delay_ms = backoff_seq[min(attempt, len(backoff_seq) - 1)]
            await asyncio.sleep(delay_ms / 1000.0)
    assert last_exc is not None
    raise last_exc
