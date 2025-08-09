"""Simplified integration test to verify mcp-db session persistence."""

import asyncio
import json
import uuid

import pytest

from mcp_db.core.event_store import EventStore
from mcp_db.core.interceptor import ProtocolInterceptor
from mcp_db.core.models import MCPSession, SessionStatus
from mcp_db.core.session_manager import SessionManager
from mcp_db.storage import InMemoryStorage


@pytest.mark.asyncio
async def test_session_persistence_basic():
    """Test basic session persistence and retrieval."""
    # Setup storage and components
    storage = InMemoryStorage()
    event_store = EventStore(storage)
    session_manager = SessionManager(storage=storage, event_store=event_store)
    interceptor = ProtocolInterceptor(session_manager)

    # Create a test session ID (normally provided by server)
    session_id = str(uuid.uuid4())

    # Simulate initialize request
    init_request = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "clientInfo": {"name": "test-client"}, "capabilities": {}},
        "id": 1,
    }

    # Context with session ID in headers
    context = {
        "headers": {"mcp-session-id": session_id},
        "server_id": "test-server-1",
        "_mcp_db_init_params": init_request["params"],
    }

    # Process incoming initialize request
    await interceptor.handle_incoming(json.dumps(init_request), context)

    # Simulate initialize response (this creates the session)
    init_response = {
        "jsonrpc": "2.0",
        "result": {"protocolVersion": "2025-06-18", "serverInfo": {"name": "test-server"}, "capabilities": {}},
        "id": 1,
    }

    # Mark that we just processed an initialize
    context["_mcp_db_last_method"] = "initialize"

    # Process outgoing response (creates session)
    await interceptor.handle_outgoing(session_id, init_response, context)

    # Verify session was created
    session = await session_manager.get(session_id)
    assert session is not None
    assert session.id == session_id
    assert session.status == SessionStatus.INITIALIZED
    assert session.client_id == "test-client"
    assert session.server_id == "test-server-1"

    # Simulate initialized notification to activate session
    initialized_notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}

    await interceptor.handle_incoming(json.dumps(initialized_notif), context)

    # Verify session is now active
    session = await session_manager.get(session_id)
    assert session.status == SessionStatus.ACTIVE

    # Verify events were stored
    events = []
    async for event in event_store.stream(session_id):
        events.append(event)

    assert len(events) > 0
    event_types = [e.event_type for e in events]
    assert "SessionCreatedEvent" in event_types
    assert "SessionInitializedEvent" in event_types


@pytest.mark.asyncio
async def test_session_recovery_on_different_node():
    """Test that a session can be recovered on a different 'node'."""
    # Shared storage simulating Redis
    shared_storage = InMemoryStorage()

    # Node 1 components
    event_store_1 = EventStore(shared_storage)
    session_manager_1 = SessionManager(storage=shared_storage, event_store=event_store_1)
    interceptor_1 = ProtocolInterceptor(session_manager_1)

    session_id = str(uuid.uuid4())

    # Initialize session on Node 1
    init_request = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "clientInfo": {"name": "test-client"}, "capabilities": {}},
        "id": 1,
    }

    context_1 = {
        "headers": {"mcp-session-id": session_id},
        "server_id": "node-1",
        "_mcp_db_init_params": init_request["params"],
        "_mcp_db_last_method": "initialize",
    }

    # Process on Node 1
    await interceptor_1.handle_incoming(json.dumps(init_request), context_1)

    init_response = {
        "jsonrpc": "2.0",
        "result": {"protocolVersion": "2025-06-18", "serverInfo": {"name": "node-1-server"}, "capabilities": {}},
        "id": 1,
    }

    await interceptor_1.handle_outgoing(session_id, init_response, context_1)

    # Activate session
    initialized = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    await interceptor_1.handle_incoming(json.dumps(initialized), context_1)

    # Verify session exists on Node 1
    session_from_node_1 = await session_manager_1.get(session_id)
    assert session_from_node_1 is not None
    assert session_from_node_1.status == SessionStatus.ACTIVE

    # Now create Node 2 components (simulating a different server)
    event_store_2 = EventStore(shared_storage)
    session_manager_2 = SessionManager(storage=shared_storage, event_store=event_store_2)
    interceptor_2 = ProtocolInterceptor(session_manager_2)

    # Node 2 retrieves the same session from shared storage
    session_from_node_2 = await session_manager_2.get(session_id)

    # Verify Node 2 can access the session
    assert session_from_node_2 is not None
    assert session_from_node_2.id == session_id
    assert session_from_node_2.status == SessionStatus.ACTIVE
    assert session_from_node_2.client_id == "test-client"

    # Node 2 can process requests for this session
    tool_call = {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "test-tool", "arguments": {}}, "id": 2}

    context_2 = {"headers": {"mcp-session-id": session_id}, "server_id": "node-2"}

    # Process on Node 2
    await interceptor_2.handle_incoming(json.dumps(tool_call), context_2)

    # Verify events from both nodes are in storage
    all_events = []
    async for event in event_store_2.stream(session_id):
        all_events.append(event)

    # Should have events from both nodes
    assert len(all_events) > 3  # At least: create, init, activate, tool call

    # Check that we have events from the tool call
    event_methods = []
    for event in all_events:
        if event.event_type == "MessageReceivedEvent":
            payload = event.payload
            if isinstance(payload, dict) and "method" in payload:
                event_methods.append(payload["method"])

    assert "tools/call" in event_methods


@pytest.mark.asyncio
async def test_session_closure():
    """Test session closure handling."""
    storage = InMemoryStorage()
    event_store = EventStore(storage)
    session_manager = SessionManager(storage=storage, event_store=event_store)
    interceptor = ProtocolInterceptor(session_manager)

    # Create an active session
    session = MCPSession(
        id="test-session",
        status=SessionStatus.ACTIVE,
        client_id="test-client",
        server_id="test-server",
        capabilities={},
    )
    await session_manager.create(session)

    # Simulate server disconnect
    disconnect_response = {"jsonrpc": "2.0", "method": "server/disconnect"}

    await interceptor.handle_outgoing("test-session", disconnect_response, {})

    # Verify session is closed
    closed_session = await session_manager.get("test-session")
    assert closed_session is not None
    assert closed_session.status == SessionStatus.CLOSED

    # Verify closure event was recorded
    events = []
    async for event in event_store.stream("test-session"):
        events.append(event)

    event_types = [e.event_type for e in events]
    assert "SessionClosedEvent" in event_types


if __name__ == "__main__":
    # Run the tests
    asyncio.run(test_session_persistence_basic())
    asyncio.run(test_session_recovery_on_different_node())
    asyncio.run(test_session_closure())
    print("✅ All basic tests passed!")
