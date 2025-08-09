"""Unit tests for ProtocolInterceptor."""

import json

import pytest

from mcp_db.core.interceptor import ProtocolInterceptor
from mcp_db.core.models import MCPSession, SessionStatus


@pytest.mark.asyncio
class TestProtocolInterceptor:
    """Test ProtocolInterceptor functionality."""

    async def test_handle_incoming_invalid_json(self, mock_session_manager):
        """Test handling invalid JSON input."""
        interceptor = ProtocolInterceptor(mock_session_manager)

        result = await interceptor.handle_incoming("not-valid-json{", {})

        assert "_raw" in result
        assert result["_raw"] == "not-valid-json{"

    async def test_handle_incoming_initialize(self, mock_session_manager, initialize_request):
        """Test handling initialize request."""
        interceptor = ProtocolInterceptor(mock_session_manager)

        context = {"headers": {"mcp-session-id": "sess-123"}}
        _ = await interceptor.handle_incoming(json.dumps(initialize_request), context)

        # Should not create session on initialize (waits for response)
        mock_session_manager.create.assert_not_called()

        # Should stash params in context
        assert context.get("_mcp_db_init_params") == initialize_request["params"]

        # Should record event if session exists
        mock_session_manager.append_event.assert_called_once()
        event = mock_session_manager.append_event.call_args[0][0]
        assert event.event_type == "MessageReceivedEvent"
        assert event.session_id == "sess-123"

    async def test_handle_incoming_initialized_notification(self, mock_session_manager, initialized_notification):
        """Test handling initialized notification."""
        # Setup existing session
        existing_session = MCPSession(
            id="sess-456",
            status=SessionStatus.INITIALIZED,
            client_id="client",
            server_id="server",
            capabilities={},
        )
        mock_session_manager.get.return_value = existing_session

        interceptor = ProtocolInterceptor(mock_session_manager)

        context = {"headers": {"mcp-session-id": "sess-456"}}
        _ = await interceptor.handle_incoming(json.dumps(initialized_notification), context)

        # Should update session to ACTIVE
        mock_session_manager.update.assert_called_once()
        call_args = mock_session_manager.update.call_args[0]
        assert call_args[0] == "sess-456"  # session_id
        assert call_args[1]["status"] == SessionStatus.ACTIVE  # updates dict

        # Should append SessionInitializedEvent
        events = [call[0][0] for call in mock_session_manager.append_event.call_args_list]
        assert any(e.event_type == "SessionInitializedEvent" for e in events)

    async def test_handle_incoming_other_methods(self, mock_session_manager, tools_call_request):
        """Test handling other JSON-RPC methods."""
        interceptor = ProtocolInterceptor(mock_session_manager)

        context = {"headers": {"mcp-session-id": "sess-789"}}
        _ = await interceptor.handle_incoming(json.dumps(tools_call_request), context)

        # Should append MessageReceivedEvent
        mock_session_manager.append_event.assert_called_once()
        event = mock_session_manager.append_event.call_args[0][0]
        assert event.event_type == "MessageReceivedEvent"
        assert event.session_id == "sess-789"
        assert event.payload["method"] == "tools/call"

    async def test_handle_outgoing_after_initialize(self, mock_session_manager, initialize_response):
        """Test handling outgoing response after initialize."""
        interceptor = ProtocolInterceptor(mock_session_manager)

        # No existing session
        mock_session_manager.get.return_value = None

        context = {
            "_mcp_db_last_method": "initialize",
            "_mcp_db_init_params": {
                "clientInfo": {"name": "test-client"},
                "capabilities": {"tools": True},
            },
            "server_id": "server-1",
        }

        await interceptor.handle_outgoing("new-sess", initialize_response, context)

        # Should create new session with INITIALIZED status
        mock_session_manager.create.assert_called_once()
        created_session = mock_session_manager.create.call_args[0][0]
        assert created_session.id == "new-sess"
        assert created_session.status == SessionStatus.INITIALIZED
        assert created_session.client_id == "test-client"
        assert created_session.capabilities == {"tools": True}

        # Should append events
        assert mock_session_manager.append_event.call_count >= 1

    async def test_handle_outgoing_update_existing_session(self, mock_session_manager, initialize_response):
        """Test updating existing session on initialize response."""
        # Existing session
        existing = MCPSession(
            id="existing-sess",
            status=SessionStatus.INITIALIZING,
            client_id="old-client",
            server_id="server-1",
            capabilities={},
        )
        mock_session_manager.get.return_value = existing

        interceptor = ProtocolInterceptor(mock_session_manager)

        context = {
            "_mcp_db_last_method": "initialize",
            "_mcp_db_init_params": {
                "clientInfo": {"name": "new-client"},
                "capabilities": {"prompts": True},
            },
        }

        await interceptor.handle_outgoing("existing-sess", initialize_response, context)

        # Should update, not create
        mock_session_manager.create.assert_not_called()
        mock_session_manager.update.assert_called_once()
        call_args = mock_session_manager.update.call_args[0]
        assert call_args[0] == "existing-sess"  # session_id
        updates = call_args[1]
        assert updates["status"] == SessionStatus.INITIALIZED  # Updated status
        assert updates["client_id"] == "new-client"  # Updated client

    async def test_handle_outgoing_server_disconnect(self, mock_session_manager, server_disconnect):
        """Test handling server disconnect notification."""
        # Existing active session
        existing = MCPSession(
            id="disc-sess",
            status=SessionStatus.ACTIVE,
            client_id="client",
            server_id="server",
            capabilities={},
        )
        mock_session_manager.get.return_value = existing

        interceptor = ProtocolInterceptor(mock_session_manager)

        await interceptor.handle_outgoing("disc-sess", server_disconnect, {})

        # Should update session to CLOSED
        mock_session_manager.update.assert_called_once()
        call_args = mock_session_manager.update.call_args[0]
        assert call_args[0] == "disc-sess"  # session_id
        assert call_args[1]["status"] == SessionStatus.CLOSED  # updates dict

        # Should append SessionClosedEvent
        events = [call[0][0] for call in mock_session_manager.append_event.call_args_list]
        assert any(e.event_type == "SessionClosedEvent" for e in events)

    async def test_extract_session_id_from_params(self, mock_session_manager):
        """Test extracting session ID from request params."""
        interceptor = ProtocolInterceptor(mock_session_manager)

        request = {"params": {"session_id": "params-sess-id"}}
        context = {}

        session_id = interceptor._extract_session_id(request, context)
        assert session_id == "params-sess-id"

    async def test_extract_session_id_from_headers(self, mock_session_manager):
        """Test extracting session ID from headers."""
        interceptor = ProtocolInterceptor(mock_session_manager)

        request = {}
        context = {"headers": {"mcp-session-id": "header-sess-id"}}

        session_id = interceptor._extract_session_id(request, context)
        assert session_id == "header-sess-id"

        # Test alternate header
        context = {"headers": {"x-mcp-session-id": "x-header-sess-id"}}
        session_id = interceptor._extract_session_id(request, context)
        assert session_id == "x-header-sess-id"

    async def test_extract_session_id_from_sse_headers(self, mock_session_manager):
        """Test extracting session ID from SSE Last-Event-ID."""
        interceptor = ProtocolInterceptor(mock_session_manager)

        request = {}
        context = {"headers": {"last-event-id": "sse-sess-id"}}

        session_id = interceptor._extract_session_id(request, context)
        assert session_id == "sse-sess-id"

    async def test_extract_session_id_none(self, mock_session_manager):
        """Test when no session ID is present."""
        interceptor = ProtocolInterceptor(mock_session_manager)

        request = {}
        context = {"headers": {}}

        session_id = interceptor._extract_session_id(request, context)
        assert session_id is None
