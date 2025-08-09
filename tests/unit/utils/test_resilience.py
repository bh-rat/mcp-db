"""Unit tests for resilience utilities."""

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from mcp_db.utils.resilience import CircuitBreaker, CircuitBreakerConfig, with_retries


@pytest.mark.asyncio
class TestWithRetries:
    """Test with_retries retry functionality."""

    async def test_retry_success_first_attempt(self):
        """Test successful execution on first attempt."""
        mock_func = AsyncMock(return_value="success")

        result = await with_retries(mock_func, attempts=3)

        assert result == "success"
        assert mock_func.call_count == 1

    async def test_retry_transient_failure_then_success(self):
        """Test retry on transient failure followed by success."""
        call_count = 0

        async def func_with_failures():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception(f"Temporary error {call_count}")
            return "success"

        result = await with_retries(
            func_with_failures,
            attempts=3,
            backoff_ms=[10, 10, 10],  # Fast backoff for testing
        )

        assert result == "success"
        assert call_count == 3

    async def test_retry_max_attempts_exceeded(self):
        """Test that retry stops after max attempts."""
        mock_func = AsyncMock(side_effect=Exception("Persistent error"))

        with pytest.raises(Exception, match="Persistent error"):
            await with_retries(mock_func, attempts=3, backoff_ms=[10, 10])

        assert mock_func.call_count == 3

    async def test_retry_with_custom_backoff(self):
        """Test retry with custom backoff sequence."""
        call_times = []

        async def track_timing():
            call_times.append(time.time())
            if len(call_times) < 3:
                raise Exception("Retry needed")
            return "success"

        result = await with_retries(
            track_timing,
            attempts=3,
            backoff_ms=[50, 100],  # 50ms, then 100ms
        )

        assert result == "success"
        assert len(call_times) == 3

        # Check delays (approximate due to async scheduling)
        if len(call_times) >= 2:
            delay1 = call_times[1] - call_times[0]
            assert 0.04 < delay1 < 0.08  # ~50ms
        if len(call_times) >= 3:
            delay2 = call_times[2] - call_times[1]
            assert 0.09 < delay2 < 0.15  # ~100ms


class TestCircuitBreaker:
    """Test CircuitBreaker functionality."""

    @pytest.mark.asyncio
    async def test_circuit_initially_closed(self):
        """Test that circuit starts in closed state and allows calls."""
        config = CircuitBreakerConfig(failure_threshold=3)
        breaker = CircuitBreaker(config)

        mock_func = AsyncMock(return_value="result")
        result = await breaker.run(mock_func)

        assert result == "result"
        mock_func.assert_called_once()

    @pytest.mark.asyncio
    async def test_circuit_opens_after_threshold(self):
        """Test circuit opens after failure threshold."""
        config = CircuitBreakerConfig(failure_threshold=3, reset_timeout_seconds=1)
        breaker = CircuitBreaker(config)

        # Fail 3 times to open circuit
        failing_func = AsyncMock(side_effect=Exception("fail"))

        for _ in range(3):
            with pytest.raises(Exception, match="fail"):
                await breaker.run(failing_func)

        # Circuit should now be open
        with pytest.raises(RuntimeError, match="circuit_open"):
            await breaker.run(failing_func)

    @pytest.mark.asyncio
    async def test_circuit_blocks_when_open(self):
        """Test that open circuit blocks calls."""
        config = CircuitBreakerConfig(failure_threshold=1, reset_timeout_seconds=10)
        breaker = CircuitBreaker(config)

        # Open the circuit with one failure
        failing_func = AsyncMock(side_effect=Exception("fail"))
        with pytest.raises(Exception, match="fail"):
            await breaker.run(failing_func)

        # Try to call through open circuit
        mock_func = AsyncMock(return_value="result")

        with pytest.raises(RuntimeError, match="circuit_open"):
            await breaker.run(mock_func)

        # Function should not be called
        mock_func.assert_not_called()

    @pytest.mark.asyncio
    async def test_circuit_half_open_after_cooldown(self):
        """Test circuit moves to half-open after cooldown."""
        config = CircuitBreakerConfig(failure_threshold=1, reset_timeout_seconds=0.1)
        breaker = CircuitBreaker(config)

        # Open the circuit
        failing_func = AsyncMock(side_effect=Exception("fail"))
        with pytest.raises(Exception, match="fail"):
            await breaker.run(failing_func)

        # Wait for cooldown
        await asyncio.sleep(0.15)

        # Circuit should allow one test call (half-open)
        mock_func = AsyncMock(return_value="success")
        result = await breaker.run(mock_func)

        assert result == "success"
        # After success, circuit is closed again

    @pytest.mark.asyncio
    async def test_circuit_reopens_on_half_open_failure(self):
        """Test circuit reopens if half-open test fails."""
        config = CircuitBreakerConfig(failure_threshold=1, reset_timeout_seconds=0.1)
        breaker = CircuitBreaker(config)

        # Open the circuit
        failing_func = AsyncMock(side_effect=Exception("fail"))
        with pytest.raises(Exception, match="fail"):
            await breaker.run(failing_func)

        # Wait for cooldown
        await asyncio.sleep(0.15)

        # Half-open test fails
        still_failing = AsyncMock(side_effect=Exception("Still failing"))

        with pytest.raises(Exception, match="Still failing"):
            await breaker.run(still_failing)

        # Circuit should be open again
        with pytest.raises(RuntimeError, match="circuit_open"):
            await breaker.run(still_failing)

    @pytest.mark.asyncio
    async def test_circuit_success_resets_failure_count(self):
        """Test successful calls reset failure count."""
        config = CircuitBreakerConfig(failure_threshold=3)
        breaker = CircuitBreaker(config)

        # Record 2 failures (not enough to open)
        failing_func = AsyncMock(side_effect=Exception("fail"))
        for _ in range(2):
            with pytest.raises(Exception, match="fail"):
                await breaker.run(failing_func)

        # Success resets count
        success_func = AsyncMock(return_value="success")
        await breaker.run(success_func)

        # Can now fail 2 more times without opening
        for _ in range(2):
            with pytest.raises(Exception, match="fail"):
                await breaker.run(failing_func)

        # Still works
        await breaker.run(success_func)

    @pytest.mark.asyncio
    async def test_circuit_idempotence_when_open(self):
        """Test that wrapped callable is not invoked while circuit is open."""
        config = CircuitBreakerConfig(failure_threshold=1, reset_timeout_seconds=10)
        breaker = CircuitBreaker(config)

        # Open the circuit
        failing_func = AsyncMock(side_effect=Exception("fail"))
        with pytest.raises(Exception, match="fail"):
            await breaker.run(failing_func)

        call_count = 0

        async def tracked_func():
            nonlocal call_count
            call_count += 1
            return "result"

        # Multiple attempts while open
        for _ in range(5):
            with pytest.raises(RuntimeError, match="circuit_open"):
                await breaker.run(tracked_func)

        # Function never called
        assert call_count == 0
