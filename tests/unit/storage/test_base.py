"""Unit tests for StorageAdapter and InMemoryStorage."""

import pytest

from mcp_db.core.models import BaseEvent, MCPSession, SessionStatus
from mcp_db.storage.base import InMemoryStorage, StorageAdapter


class TestStorageAdapterInterface:
    """Test StorageAdapter abstract interface."""

    def test_interface_conformance(self):
        """Test that StorageAdapter has all required abstract methods."""
        required_methods = [
            "is_healthy",
            "get_session",
            "create_session",
            "update_session",
            "delete_session",
            "append_event",
            "get_events",
            "acquire_lock",
            "release_lock",
        ]

        for method_name in required_methods:
            assert hasattr(StorageAdapter, method_name)

        # Verify they're abstract (can't instantiate StorageAdapter directly)
        with pytest.raises(TypeError):
            StorageAdapter()


@pytest.mark.asyncio
class TestInMemoryStorage:
    """Test InMemoryStorage implementation."""

    async def test_is_healthy_always_true(self):
        """Test that InMemoryStorage is always healthy."""
        storage = InMemoryStorage()
        assert await storage.is_healthy() is True

    async def test_session_crud_operations(self):
        """Test session create, read, update, delete operations."""
        storage = InMemoryStorage()

        session = MCPSession(
            id="test-123",
            status=SessionStatus.INITIALIZED,
            client_id="client-1",
            server_id="server-1",
            capabilities={"tools": True},
        )

        # Create
        await storage.create_session(session)

        # Read (get)
        retrieved = await storage.get_session(session.id)
        assert retrieved is not None
        assert retrieved.id == "test-123"
        assert retrieved.client_id == "client-1"
        assert retrieved.capabilities == {"tools": True}

        # Update
        await storage.update_session(session.id, {"status": SessionStatus.ACTIVE, "metadata": {"updated": True}})

        updated = await storage.get_session(session.id)
        assert updated.status == SessionStatus.ACTIVE
        assert updated.metadata == {"updated": True}

        # Delete
        await storage.delete_session(session.id)
        deleted = await storage.get_session(session.id)
        assert deleted is None

    async def test_get_nonexistent_session(self):
        """Test getting a non-existent session returns None."""
        storage = InMemoryStorage()
        result = await storage.get_session("nonexistent")
        assert result is None

    async def test_delete_nonexistent_session(self):
        """Test deleting non-existent session doesn't raise."""
        storage = InMemoryStorage()
        # Should not raise
        await storage.delete_session("nonexistent")

    async def test_event_append_and_list(self):
        """Test appending and listing events."""
        storage = InMemoryStorage()

        events = []
        for i in range(5):
            event = BaseEvent(
                event_id=f"evt-{i}",
                session_id="sess-123",
                event_type="TestEvent",
                timestamp=float(i),
                payload={"index": i},
            )
            events.append(event)
            await storage.append_event(event)

        # Get all events
        listed = []
        async for event in storage.get_events("sess-123"):
            listed.append(event)
        assert len(listed) == 5

        # Verify order preserved
        for i, event in enumerate(listed):
            assert event.event_id == f"evt-{i}"
            assert event.payload["index"] == i

    async def test_list_events_empty_session(self):
        """Test listing events for session with no events."""
        storage = InMemoryStorage()
        events = []
        async for event in storage.get_events("empty-session"):
            events.append(event)
        assert events == []

    async def test_list_events_with_from_id(self):
        """Test listing events from a specific event ID."""
        storage = InMemoryStorage()

        # Add events 0-9
        for i in range(10):
            event = BaseEvent(
                event_id=f"evt-{i}",
                session_id="sess-456",
                event_type="TestEvent",
            )
            await storage.append_event(event)

        # Get events after evt-4
        events = []
        async for event in storage.get_events("sess-456", after_event_id="evt-4"):
            events.append(event)

        # Should get events 5-9
        assert len(events) == 5
        assert events[0].event_id == "evt-5"
        assert events[-1].event_id == "evt-9"

    async def test_acquire_lock_basic(self):
        """Test basic lock acquisition."""
        storage = InMemoryStorage()

        acquired = await storage.acquire_lock("resource-1", ttl_seconds=10)
        assert acquired is True

    async def test_acquire_lock_contention(self):
        """Test lock contention between concurrent acquirers."""
        storage = InMemoryStorage()

        # First acquire succeeds
        acquired1 = await storage.acquire_lock("resource-2", ttl_seconds=10)
        assert acquired1 is True

        # Second acquire for same resource fails
        acquired2 = await storage.acquire_lock("resource-2", ttl_seconds=10)
        assert acquired2 is False

    async def test_release_lock_with_correct_token(self):
        """Test releasing lock."""
        storage = InMemoryStorage()

        acquired = await storage.acquire_lock("resource-3", ttl_seconds=10)
        assert acquired is True

        # Release
        await storage.release_lock("resource-3")

        # Can now acquire again
        acquired_again = await storage.acquire_lock("resource-3", ttl_seconds=10)
        assert acquired_again is True

    async def test_release_lock_idempotent(self):
        """Test that releasing is idempotent."""
        storage = InMemoryStorage()

        acquired = await storage.acquire_lock("resource-4", ttl_seconds=10)
        assert acquired is True

        # Release once
        await storage.release_lock("resource-4")

        # Release again (should not error)
        await storage.release_lock("resource-4")

        # Can acquire again
        acquired_again = await storage.acquire_lock("resource-4", ttl_seconds=10)
        assert acquired_again is True
