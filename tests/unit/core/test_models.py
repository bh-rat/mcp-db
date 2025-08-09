"""Unit tests for data models."""

import json
import time
from dataclasses import asdict

from mcp_db.core.models import BaseEvent, MCPEvent, MCPSession, SessionStatus


class TestSessionStatus:
    """Test SessionStatus enum."""

    def test_session_status_values(self):
        """Test that SessionStatus has correct string values."""
        assert SessionStatus.INITIALIZING.value == "INITIALIZING"
        assert SessionStatus.INITIALIZED.value == "INITIALIZED"
        assert SessionStatus.ACTIVE.value == "ACTIVE"
        assert SessionStatus.SUSPENDED.value == "SUSPENDED"
        assert SessionStatus.RECOVERING.value == "RECOVERING"
        assert SessionStatus.CLOSED.value == "CLOSED"

    def test_session_status_comparison(self):
        """Test SessionStatus comparisons."""
        assert SessionStatus.INITIALIZED == SessionStatus.INITIALIZED
        assert SessionStatus.INITIALIZED != SessionStatus.ACTIVE
        assert SessionStatus.CLOSED != SessionStatus.ACTIVE


class TestMCPSession:
    """Test MCPSession dataclass."""

    def test_session_creation_with_defaults(self):
        """Test creating session with default values."""
        session = MCPSession(
            id="test-123",
            status=SessionStatus.INITIALIZED,
            client_id="client-1",
            server_id="server-1",
            capabilities={"tools": True},
        )

        assert session.id == "test-123"
        assert session.status == SessionStatus.INITIALIZED
        assert session.client_id == "client-1"
        assert session.server_id == "server-1"
        assert session.capabilities == {"tools": True}
        assert session.metadata == {}
        assert session.last_event_id is None
        assert isinstance(session.created_at, float)
        assert isinstance(session.updated_at, float)

    def test_session_creation_with_all_fields(self):
        """Test creating session with all fields specified."""
        created_time = time.time()
        session = MCPSession(
            id="test-456",
            status=SessionStatus.ACTIVE,
            client_id="client-2",
            server_id="server-2",
            capabilities={"prompts": True},
            metadata={"key": "value"},
            created_at=created_time,
            updated_at=created_time + 10,
            last_event_id="event-789",
        )

        assert session.id == "test-456"
        assert session.status == SessionStatus.ACTIVE
        assert session.metadata == {"key": "value"}
        assert session.created_at == created_time
        assert session.updated_at == created_time + 10
        assert session.last_event_id == "event-789"

    def test_session_serialization(self):
        """Test session can be serialized to dict."""
        session = MCPSession(
            id="test-serialize",
            status=SessionStatus.CLOSED,
            client_id="client-3",
            server_id="server-3",
            capabilities={},
        )

        data = asdict(session)
        assert data["id"] == "test-serialize"
        assert data["status"] == SessionStatus.CLOSED
        assert data["client_id"] == "client-3"
        assert "created_at" in data
        assert "updated_at" in data

    def test_session_json_round_trip(self):
        """Test session survives JSON serialization round-trip."""
        original = MCPSession(
            id="json-test",
            status=SessionStatus.ACTIVE,
            client_id="client-json",
            server_id="server-json",
            capabilities={"nested": {"feature": True}},
            metadata={"test": "data"},
        )

        # Convert to JSON and back
        json_str = json.dumps(asdict(original))
        data = json.loads(json_str)

        # Reconstruct (with status enum conversion)
        data["status"] = SessionStatus(data["status"])
        reconstructed = MCPSession(**data)

        assert reconstructed.id == original.id
        assert reconstructed.status == original.status
        assert reconstructed.capabilities == original.capabilities
        assert reconstructed.metadata == original.metadata


class TestBaseEvent:
    """Test BaseEvent/MCPEvent dataclass."""

    def test_event_creation_with_defaults(self):
        """Test creating event with default values."""
        event = BaseEvent(
            event_id="evt-123",
            session_id="sess-456",
            event_type="TestEvent",
        )

        assert event.event_id == "evt-123"
        assert event.session_id == "sess-456"
        assert event.event_type == "TestEvent"
        assert event.payload == {}
        assert isinstance(event.timestamp, float)

    def test_event_creation_with_payload(self):
        """Test creating event with custom payload."""
        payload = {"method": "tools/call", "params": {"name": "test"}}
        event = BaseEvent(
            event_id="evt-789",
            session_id="sess-000",
            event_type="MessageReceivedEvent",
            payload=payload,
        )

        assert event.payload == payload
        assert event.event_type == "MessageReceivedEvent"

    def test_event_timestamp_auto_set(self):
        """Test that timestamp is automatically set."""
        before = time.time()
        event = BaseEvent(
            event_id="evt-time",
            session_id="sess-time",
            event_type="TimeTest",
        )
        after = time.time()

        assert before <= event.timestamp <= after

    def test_mcp_event_alias(self):
        """Test that MCPEvent is an alias for BaseEvent."""
        assert MCPEvent is BaseEvent

        # Can create using either name
        event1 = BaseEvent(
            event_id="evt-1",
            session_id="sess-1",
            event_type="Test",
        )
        event2 = MCPEvent(
            event_id="evt-2",
            session_id="sess-1",
            event_type="Test",
        )

        assert type(event1) is type(event2)
