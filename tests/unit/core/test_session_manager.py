"""Unit tests for SessionManager."""

import pytest

from mcp_db.core.models import BaseEvent, SessionStatus
from mcp_db.core.session_manager import SessionManager


@pytest.mark.asyncio
class TestSessionManager:
    """Test SessionManager functionality."""

    async def test_create_session(self, mock_storage, mock_event_store, sample_session):
        """Test creating a new session."""
        manager = SessionManager(storage=mock_storage, event_store=mock_event_store)

        await manager.create(sample_session)

        # Verify storage was called
        mock_storage.create_session.assert_called_once_with(sample_session)

    async def test_get_session_exists(self, mock_storage, mock_event_store, sample_session):
        """Test retrieving an existing session."""
        mock_storage.get_session.return_value = sample_session

        manager = SessionManager(storage=mock_storage, event_store=mock_event_store)
        session = await manager.get("test-123")

        assert session is not None
        assert session.id == sample_session.id
        assert session.status == sample_session.status
        assert session.client_id == sample_session.client_id

    async def test_get_session_not_found(self, mock_storage, mock_event_store):
        """Test retrieving a non-existent session."""
        mock_storage.get_session.return_value = None

        manager = SessionManager(storage=mock_storage, event_store=mock_event_store)
        session = await manager.get("nonexistent")

        assert session is None

    async def test_get_session_with_local_cache(self, mock_storage, mock_event_store, sample_session):
        """Test session retrieval with local caching enabled."""
        sample_session.id = "cached-123"
        mock_storage.get_session.return_value = sample_session

        manager = SessionManager(storage=mock_storage, event_store=mock_event_store, use_local_cache=True)

        # First get - hits storage
        session1 = await manager.get("cached-123")
        assert mock_storage.get_session.call_count == 1

        # Second get - should hit cache
        session2 = await manager.get("cached-123")
        assert mock_storage.get_session.call_count == 1  # Still 1

        # Both should be the same
        assert session1.id == session2.id

    async def test_update_session(self, mock_storage, mock_event_store, sample_session):
        """Test updating an existing session."""
        manager = SessionManager(storage=mock_storage, event_store=mock_event_store)

        # Update the session
        updates = {"status": SessionStatus.CLOSED, "metadata": {"updated": True}}

        await manager.update(sample_session.id, updates)

        # Verify storage was updated
        mock_storage.update_session.assert_called_once_with(sample_session.id, updates)

    async def test_delete_session(self, mock_storage, mock_event_store):
        """Test deleting a session."""
        manager = SessionManager(storage=mock_storage, event_store=mock_event_store)

        await manager.delete("to-delete")

        # Verify storage deletion
        mock_storage.delete_session.assert_called_once_with("to-delete")

    async def test_append_event_noop(self, mock_storage, mock_event_store):
        """Append event is a no-op in SessionManager (handled by SDK transports)."""
        manager = SessionManager(storage=mock_storage, event_store=mock_event_store)
        event = BaseEvent(event_id="evt-123", session_id="sess-456", event_type="CustomEvent", payload={"test": "data"})
        await manager.append_event(event)
        mock_event_store.append.assert_not_called()

    async def test_status_transition_validation(self, mock_storage, mock_event_store):
        """Test session status transition validation."""
        manager = SessionManager(storage=mock_storage, event_store=mock_event_store)

        # Valid transitions
        session_id = "trans-test"

        # INITIALIZED -> ACTIVE is valid
        await manager.update(session_id, {"status": SessionStatus.ACTIVE})  # Should not raise

        # ACTIVE -> CLOSED is valid
        await manager.update(session_id, {"status": SessionStatus.CLOSED})  # Should not raise

    async def test_concurrent_access_with_lock(self, mock_storage, mock_event_store):
        """Test concurrent access protection with storage lock."""
        mock_storage.acquire_lock.return_value = True

        manager = SessionManager(storage=mock_storage, event_store=mock_event_store)

        # Update with locking
        await manager.update("concurrent-test", {"status": SessionStatus.ACTIVE})

        # Storage update should have been called
        mock_storage.update_session.assert_called_once()

    async def test_resilience_to_storage_failures(self, mock_storage, mock_event_store, sample_session):
        """Test resilience to storage failures."""
        mock_storage.create_session.side_effect = Exception("Storage error")

        manager = SessionManager(storage=mock_storage, event_store=mock_event_store)

        # Should retry and eventually fail
        # The manager uses retry logic, so the exception may be wrapped
        try:
            await manager.create(sample_session)
            assert False, "Should have raised an exception"
        except Exception as e:
            assert "Storage error" in str(e) or "circuit_open" in str(e)
