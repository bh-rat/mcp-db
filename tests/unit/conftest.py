"""Shared fixtures and mocks for unit tests."""

from __future__ import annotations

import json
import typing as t
import uuid
from unittest.mock import AsyncMock, Mock

import pytest

from mcp_db.core.models import BaseEvent, MCPSession, SessionStatus


@pytest.fixture
def mock_storage():
    """Mock storage adapter."""
    storage = AsyncMock()
    storage.is_healthy = AsyncMock(return_value=True)
    storage.get_session = AsyncMock(return_value=None)
    storage.set_session = AsyncMock(return_value=None)
    storage.delete_session = AsyncMock(return_value=None)
    storage.append_event = AsyncMock(return_value=None)
    storage.list_events = AsyncMock(return_value=[])
    storage.acquire_lock = AsyncMock(return_value="lock-token-123")
    storage.release_lock = AsyncMock(return_value=None)
    return storage


@pytest.fixture
def sample_session():
    """Create a sample MCP session."""
    return MCPSession(
        id="test-session-123",
        status=SessionStatus.INITIALIZED,
        client_id="test-client",
        server_id="test-server",
        capabilities={"tools": True},
        metadata={"test": "data"},
    )


@pytest.fixture
def sample_event():
    """Create a sample event."""
    return BaseEvent(
        event_id=str(uuid.uuid4()),
        session_id="test-session-123",
        event_type="MessageReceivedEvent",
        payload={"method": "tools/call", "params": {}},
    )


@pytest.fixture
def mock_interceptor():
    """Mock protocol interceptor."""
    interceptor = AsyncMock()
    interceptor.handle_incoming = AsyncMock(return_value={"jsonrpc": "2.0"})
    interceptor.handle_outgoing = AsyncMock(return_value=None)
    return interceptor


@pytest.fixture
def mock_admission_controller():
    """Mock admission controller."""
    controller = AsyncMock()
    controller.has_session = AsyncMock(return_value=False)
    controller.ensure_session_transport = AsyncMock(return_value=None)
    return controller


@pytest.fixture
def mock_session_manager():
    """Mock session manager."""
    manager = AsyncMock()
    manager.get = AsyncMock(return_value=None)
    manager.create = AsyncMock(return_value=None)
    manager.update = AsyncMock(return_value=None)
    manager.delete = AsyncMock(return_value=None)
    manager.append_event = AsyncMock(return_value=None)
    # Add internal attributes for admission tests
    manager._server_instances = {}
    manager._task_group = AsyncMock()
    manager._task_group.start = AsyncMock()
    return manager


@pytest.fixture
def mock_event_store():
    """Mock event store."""
    store = AsyncMock()
    store.append = AsyncMock(return_value=None)
    store.stream = AsyncMock(return_value=AsyncIterator([]))
    return store


@pytest.fixture
def mock_asgi_app():
    """Mock ASGI application."""

    async def app(scope, receive, send):
        # Echo back for testing
        _ = await receive()
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [[b"content-type", b"application/json"]],
            }
        )
        await send({"type": "http.response.body", "body": b'{"result": "ok"}'})

    return app


@pytest.fixture
def http_scope():
    """Create a sample HTTP scope."""
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/mcp",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"content-type", b"application/json"),
            (b"mcp-session-id", b"test-session-123"),
        ],
        "server": ("127.0.0.1", 8000),
        "client": ("127.0.0.1", 12345),
        "state": {},
    }


@pytest.fixture
def mock_receive():
    """Mock ASGI receive callable."""

    async def receive():
        return {
            "type": "http.request",
            "body": b'{"jsonrpc": "2.0", "method": "initialize", "id": 1}',
            "more_body": False,
        }

    return receive


@pytest.fixture
def mock_send():
    """Mock ASGI send callable."""
    send_mock = AsyncMock()
    return send_mock


@pytest.fixture
def mock_redis_client():
    """Mock Redis client."""
    client = AsyncMock()
    client.ping = AsyncMock(return_value=True)
    client.get = AsyncMock(return_value=None)
    client.set = AsyncMock(return_value=True)
    client.delete = AsyncMock(return_value=1)
    client.xadd = AsyncMock(return_value=b"1234567890-0")
    client.xrange = AsyncMock(return_value=[])
    client.xread = AsyncMock(return_value=[])
    client.set = AsyncMock(return_value=True)  # For locks
    client.eval = AsyncMock(return_value=1)  # For lock release
    return client


@pytest.fixture
def mock_transport():
    """Mock MCP transport."""
    transport = AsyncMock()
    transport.connect = AsyncMock()
    transport.__aenter__ = AsyncMock(return_value=transport)
    transport.__aexit__ = AsyncMock(return_value=None)
    return transport


@pytest.fixture
def mock_mcp_app():
    """Mock MCP application."""
    app = Mock()
    app.create_initialization_options = Mock(return_value={})
    app.run = AsyncMock()
    return app


class AsyncIterator:
    """Helper for creating async iterators in tests."""

    def __init__(self, items):
        self.items = items

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.items:
            raise StopAsyncIteration
        return self.items.pop(0)


@pytest.fixture
def fake_session_lookup():
    """Fake session lookup function."""
    sessions = {}

    async def lookup(session_id: str) -> t.Optional[t.Dict[str, t.Any]]:
        return sessions.get(session_id)

    lookup.sessions = sessions  # For test manipulation
    return lookup


@pytest.fixture
def initialize_request():
    """Sample initialize request."""
    return {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "clientInfo": {"name": "test-client", "version": "1.0"},
            "capabilities": {"tools": {"call": True}},
        },
        "id": 1,
    }


@pytest.fixture
def initialize_response():
    """Sample initialize response."""
    return {
        "jsonrpc": "2.0",
        "result": {
            "protocolVersion": "2025-06-18",
            "serverInfo": {"name": "test-server", "version": "1.0"},
            "capabilities": {"tools": {"list": True}},
        },
        "id": 1,
    }


@pytest.fixture
def initialized_notification():
    """Sample initialized notification."""
    return {"jsonrpc": "2.0", "method": "notifications/initialized"}


@pytest.fixture
def tools_call_request():
    """Sample tools/call request."""
    return {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "test-tool", "arguments": {"arg1": "value1"}},
        "id": 2,
    }


@pytest.fixture
def server_disconnect():
    """Sample server disconnect notification."""
    return {"jsonrpc": "2.0", "method": "server/disconnect"}


@pytest.fixture
def sse_chunks():
    """Sample SSE response chunks."""
    return [
        b"data: " + json.dumps({"jsonrpc": "2.0", "method": "test"}).encode() + b"\n\n",
        b"data: " + json.dumps({"jsonrpc": "2.0", "result": "ok"}).encode() + b"\n\n",
        b": comment line\n\n",
        b"data: not-json\n\n",
    ]


# Helper functions for tests
def create_session(
    session_id: str = None,
    status: SessionStatus = SessionStatus.INITIALIZED,
    client_id: str = "test-client",
    server_id: str = "test-server",
) -> MCPSession:
    """Helper to create test sessions."""
    return MCPSession(
        id=session_id or str(uuid.uuid4()),
        status=status,
        client_id=client_id,
        server_id=server_id,
        capabilities={},
    )


def create_event(session_id: str, event_type: str, payload: dict = None) -> BaseEvent:
    """Helper to create test events."""
    return BaseEvent(
        event_id=str(uuid.uuid4()),
        session_id=session_id,
        event_type=event_type,
        payload=payload or {},
    )


@pytest.fixture
def mock_circuit_breaker():
    """Mock circuit breaker for resilience tests."""
    breaker = Mock()
    breaker.is_open = False
    breaker.call = AsyncMock(side_effect=lambda func, *args, **kwargs: func(*args, **kwargs))
    breaker.record_success = Mock()
    breaker.record_failure = Mock()
    return breaker


@pytest.fixture
def mock_retry_policy():
    """Mock retry policy for resilience tests."""
    policy = Mock()
    policy.execute = AsyncMock(side_effect=lambda func, *args, **kwargs: func(*args, **kwargs))
    return policy
