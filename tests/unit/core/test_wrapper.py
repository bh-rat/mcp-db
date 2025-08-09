"""Unit tests for MCPStorageWrapper."""

from unittest.mock import AsyncMock, Mock

import pytest

from mcp_db.core.wrapper import MCPStorageWrapper


class TestMCPStorageWrapper:
    """Test MCPStorageWrapper composition."""

    def test_wrapper_initialization_with_server(self, mock_interceptor):
        """Test wrapper initializes with server and interceptor."""
        mock_server = Mock()
        mock_server.handle_message = AsyncMock()

        wrapper = MCPStorageWrapper(server=mock_server, interceptor=mock_interceptor)

        assert wrapper._server == mock_server
        assert wrapper._interceptor == mock_interceptor

    def test_wrapper_requires_handle_message(self, mock_interceptor):
        """Test wrapper requires server to have handle_message method."""
        mock_server = Mock(spec=[])  # No handle_message attribute

        with pytest.raises(TypeError, match="must have an async handle_message"):
            MCPStorageWrapper(server=mock_server, interceptor=mock_interceptor)

    @pytest.mark.asyncio
    async def test_handle_raw_with_valid_json(self, mock_interceptor):
        """Test handle_raw with valid JSON message."""
        mock_server = Mock()
        mock_server.handle_message = AsyncMock(return_value={"result": "ok"})

        wrapper = MCPStorageWrapper(server=mock_server, interceptor=mock_interceptor)

        mock_interceptor.handle_incoming.return_value = {"method": "test"}
        mock_interceptor._extract_session_id.return_value = "sess-123"
        mock_interceptor.handle_outgoing.return_value = {"result": "modified"}

        _ = await wrapper.handle_raw('{"method": "test"}', {"headers": {}})

        # Should process through interceptor and server
        mock_interceptor.handle_incoming.assert_called_once()
        mock_server.handle_message.assert_called_once_with({"method": "test"})
        mock_interceptor.handle_outgoing.assert_called_once()
