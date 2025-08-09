"""Unit tests for EventStore."""

import pytest

from mcp_db.core.event_store import EventStore
from mcp_db.core.models import BaseEvent


@pytest.mark.asyncio
class TestEventStore:
    """Test EventStore functionality."""

    async def test_append_event(self, mock_storage):
        """Test appending events to storage."""
        event_store = EventStore(mock_storage)

        event = BaseEvent(
            event_id="evt-123",
            session_id="sess-456",
            event_type="TestEvent",
            payload={"data": "test"},
        )

        await event_store.append(event)

        # Verify storage was called correctly
        mock_storage.append_event.assert_called_once_with(event)

    async def test_append_event_with_storage_failure(self, mock_storage):
        """Test handling storage failures during append."""
        mock_storage.append_event.side_effect = Exception("Storage error")
        event_store = EventStore(mock_storage)

        event = BaseEvent(
            event_id="evt-fail",
            session_id="sess-fail",
            event_type="FailEvent",
        )

        # Should propagate the exception
        with pytest.raises(Exception, match="Storage error"):
            await event_store.append(event)

    async def test_stream_events_empty(self, mock_storage):
        """Test streaming events when none exist."""

        async def empty_events(*args, **kwargs):
            # Empty generator - don't yield anything
            for _ in []:
                yield

        mock_storage.get_events = empty_events
        event_store = EventStore(mock_storage)

        events = []
        async for event in event_store.stream("session-empty"):
            events.append(event)

        assert events == []

    async def test_stream_events_ordered(self, mock_storage):
        """Test streaming events returns them in order."""
        test_events = [
            BaseEvent(
                event_id=f"evt-{i}",
                session_id="sess-123",
                event_type="TestEvent",
                timestamp=float(i),
            )
            for i in range(5)
        ]

        async def events_generator(*args, **kwargs):
            for event in test_events:
                yield event

        mock_storage.get_events = events_generator
        event_store = EventStore(mock_storage)

        events = []
        async for event in event_store.stream("sess-123"):
            events.append(event)

        assert len(events) == 5
        assert all(events[i].event_id == f"evt-{i}" for i in range(5))
        # Verify they're in timestamp order
        assert all(events[i].timestamp == float(i) for i in range(5))

    async def test_stream_events_with_from_id(self, mock_storage):
        """Test streaming events from a specific event ID."""
        test_events = [
            BaseEvent(
                event_id=f"evt-{i}",
                session_id="sess-456",
                event_type="TestEvent",
            )
            for i in range(3, 8)  # Events 3-7
        ]

        async def events_generator(*args, **kwargs):
            for event in test_events:
                yield event

        mock_storage.get_events = events_generator
        event_store = EventStore(mock_storage)

        events = []
        async for event in event_store.stream("sess-456", after_event_id="evt-2"):
            events.append(event)

        assert len(events) == 5
        assert events[0].event_id == "evt-3"
        assert events[-1].event_id == "evt-7"

    async def test_stream_events_resilience(self, mock_storage):
        """Test that streaming handles storage errors gracefully."""

        async def failing_generator(*args, **kwargs):
            raise Exception("Storage unavailable")
            yield  # pragma: no cover

        mock_storage.get_events = failing_generator
        event_store = EventStore(mock_storage)

        # Should propagate the exception
        with pytest.raises(Exception, match="Storage unavailable"):
            events = []
            async for event in event_store.stream("sess-error"):
                events.append(event)
