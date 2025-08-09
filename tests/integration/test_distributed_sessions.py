"""Integration tests for distributed session coordination with mcp-db.

These tests validate the core functionality of mcp-db in enabling stateless
MCP servers to run behind load balancers with session persistence and
cross-node rehydration.
"""

from typing import Any

import pytest
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient
from starlette.types import Receive, Scope, Send

from mcp_db.core.admission import StreamableHTTPAdmissionController
from mcp_db.core.asgi_wrapper import ASGITransportWrapper
from mcp_db.core.event_store import EventStore as DbEventStore
from mcp_db.core.interceptor import ProtocolInterceptor
from mcp_db.core.session_manager import SessionManager as DbSessionManager
from mcp_db.storage import InMemoryStorage
from mcp_db.storage.redis_adapter import RedisStorage


class MockMCPServer:
    """Mock MCP server for testing."""

    def __init__(self, server_id: str, storage: Any):
        self.server_id = server_id
        self.storage = storage
        self.app = Server(f"test-server-{server_id}")
        self.sessions_handled = set()

        # Register test tools
        @self.app.list_tools()
        async def list_tools() -> list[types.Tool]:
            return [
                types.Tool(
                    name="test-tool",
                    description="Test tool for integration tests",
                    inputSchema={"type": "object", "properties": {"message": {"type": "string"}}},
                )
            ]

        @self.app.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[types.ContentBlock]:
            return [
                types.TextContent(
                    type="text", text=f"Server {self.server_id} processed: {arguments.get('message', '')}"
                )
            ]

    def create_asgi_app(self, json_response: bool = False) -> Any:
        """Create ASGI app with mcp-db wrapper."""
        # Create session manager
        self.session_manager = StreamableHTTPSessionManager(
            app=self.app,
            event_store=None,  # Will be replaced with SDK-compatible store
            json_response=json_response,
        )

        # Create mcp-db components
        db_event_store = DbEventStore(self.storage)
        db_sessions = DbSessionManager(storage=self.storage, event_store=db_event_store)
        interceptor = ProtocolInterceptor(db_sessions)
        admission = StreamableHTTPAdmissionController(manager=self.session_manager, app=self.app)

        async def lookup_session(session_id: str):
            sess = await db_sessions.get(session_id)
            return (
                None
                if sess is None
                else {
                    "id": sess.id,
                    "status": getattr(sess.status, "value", str(sess.status)),
                    "client_id": sess.client_id,
                    "server_id": sess.server_id,
                    "capabilities": sess.capabilities,
                    "metadata": sess.metadata,
                }
            )

        # Original handler
        async def handle_streamable_http(scope: Scope, receive: Receive, send: Send) -> None:
            await self.session_manager.handle_request(scope, receive, send)

        # Wrap with mcp-db
        wrapped_asgi = ASGITransportWrapper(
            interceptor,
            admission_controller=admission,
            session_lookup=lookup_session,
        ).wrap(handle_streamable_http)

        # We need to initialize the session manager's task group
        # For testing, we'll use a lifespan context
        import contextlib

        @contextlib.asynccontextmanager
        async def lifespan(app):
            async with self.session_manager.run():
                yield

        # Create Starlette app with lifespan
        starlette_app = Starlette(routes=[Mount("/mcp", app=wrapped_asgi)], lifespan=lifespan)

        return starlette_app


@pytest.fixture
async def redis_storage():
    """Provide Redis storage for tests (skip if not available)."""
    try:
        storage = RedisStorage(url="redis://localhost:6379/15", prefix="test_mcp")
        # Clear test data
        if await storage.is_healthy():
            return storage
    except Exception:
        pytest.skip("Redis not available")


@pytest.fixture
def memory_storage():
    """Provide in-memory storage for tests."""
    return InMemoryStorage()


class TestSessionMigration:
    """Test session migration between servers."""

    @pytest.mark.asyncio
    async def test_graceful_server_migration(self, memory_storage):
        """Test session migration after graceful server shutdown."""
        # Create two mock servers sharing storage
        server_a = MockMCPServer("A", memory_storage)
        server_b = MockMCPServer("B", memory_storage)

        app_a = server_a.create_asgi_app(json_response=True)
        app_b = server_b.create_asgi_app(json_response=True)

        # Client connects to Server A
        with TestClient(app_a) as client_a:
            # Initialize session
            init_response = client_a.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "clientInfo": {"name": "test-client", "version": "test"},
                        "capabilities": {},
                    },
                    "id": 1,
                },
                headers={"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18"},
            )
            assert init_response.status_code == 200
            session_id = init_response.headers.get("Mcp-Session-Id")
            assert session_id is not None

            # Send initialized notification
            init_notif = client_a.post(
                "/mcp",
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers={"Mcp-Session-Id": session_id, "Accept": "application/json, text/event-stream"},
            )
            assert init_notif.status_code == 202

            # Perform operations on Server A within same lifespan
            tools_response = client_a.post(
                "/mcp",
                json={"jsonrpc": "2.0", "method": "tools/list", "id": 2},
                headers={
                    "Mcp-Session-Id": session_id,
                    "Accept": "application/json, text/event-stream",
                    "MCP-Protocol-Version": "2025-06-18",
                },
            )
            assert tools_response.status_code == 200

        # Simulate graceful shutdown of Server A (no actual shutdown needed for test)
        # Session state is already persisted via mcp-db

        # Client now connects to Server B with same session
        with TestClient(app_b) as client_b:
            # Warm server B by sending initialized for this session id
            client_b.post(
                "/mcp",
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers={"Mcp-Session-Id": session_id, "Accept": "application/json, text/event-stream"},
            )
            # Send request to Server B using same session ID
            tool_call = client_b.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {"name": "test-tool", "arguments": {"message": "Hello from migrated session"}},
                    "id": 3,
                },
                headers={
                    "Mcp-Session-Id": session_id,
                    "Accept": "application/json, text/event-stream",
                    "MCP-Protocol-Version": "2025-06-18",
                },
            )

            # Server B should successfully handle the request
            assert tool_call.status_code == 200
            result = tool_call.json()
            assert "result" in result
            assert "Server B processed" in str(result["result"])

    @pytest.mark.asyncio
    async def test_sudden_server_failure_recovery(self, memory_storage):
        """Test session recovery after sudden server crash."""
        server_a = MockMCPServer("A", memory_storage)
        server_b = MockMCPServer("B", memory_storage)

        app_a = server_a.create_asgi_app(json_response=True)
        app_b = server_b.create_asgi_app(json_response=True)

        with TestClient(app_a) as client_a:
            # Initialize and activate session
            init_response = client_a.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "clientInfo": {"name": "test-client", "version": "test"},
                        "capabilities": {},
                    },
                    "id": 1,
                },
                headers={"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18"},
            )
            session_id = init_response.headers.get("Mcp-Session-Id")

            # Send initialized notification
            client_a.post(
                "/mcp",
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers={"Mcp-Session-Id": session_id, "Accept": "application/json, text/event-stream"},
            )
            # Perform operation that might be in-flight during crash
            client_a.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {"name": "test-tool", "arguments": {"message": "pre-crash"}},
                    "id": 2,
                },
                headers={"Mcp-Session-Id": session_id, "Accept": "application/json, text/event-stream"},
            )

        # Simulate sudden crash (no graceful shutdown)
        # In real scenario, Server A would be gone

        # Client attempts to continue on Server B
        with TestClient(app_b) as client_b:
            # Warm server B
            client_b.post(
                "/mcp",
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers={"Mcp-Session-Id": session_id, "Accept": "application/json, text/event-stream"},
            )
            recovery_response = client_b.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {"name": "test-tool", "arguments": {"message": "post-crash recovery"}},
                    "id": 3,
                },
                headers={"Mcp-Session-Id": session_id, "Accept": "application/json, text/event-stream"},
            )

        # Server B should recover the session from storage
        assert recovery_response.status_code == 200
        result = recovery_response.json()
        assert "Server B processed" in str(result.get("result", ""))


class TestConcurrentAccess:
    """Test concurrent session access from multiple servers."""

    @pytest.mark.asyncio
    async def test_concurrent_requests_consistency(self, memory_storage):
        """Test concurrent access to same session from multiple servers."""
        server_b = MockMCPServer("B", memory_storage)
        server_c = MockMCPServer("C", memory_storage)

        app_b = server_b.create_asgi_app(json_response=True)
        app_c = server_c.create_asgi_app(json_response=True)

        # Initialize session on Server B and keep both clients open
        import contextlib

        with contextlib.ExitStack() as stack:
            client_b = stack.enter_context(TestClient(app_b))
            client_c = stack.enter_context(TestClient(app_c))
            init_response = client_b.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "clientInfo": {"name": "test-client", "version": "test"},
                        "capabilities": {},
                    },
                    "id": 1,
                },
                headers={"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18"},
            )
            session_id = init_response.headers.get("Mcp-Session-Id")

            # Activate session
            client_b.post(
                "/mcp",
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers={"Mcp-Session-Id": session_id, "Accept": "application/json, text/event-stream"},
            )
            # Warm server C with initialized before its first request
            client_c.post(
                "/mcp",
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers={"Mcp-Session-Id": session_id, "Accept": "application/json, text/event-stream"},
            )
            # Perform requests while both are active
            response_b = client_b.post(
                "/mcp",
                json={"jsonrpc": "2.0", "method": "tools/list", "id": 2},
                headers={"Mcp-Session-Id": session_id, "Accept": "application/json, text/event-stream"},
            )
            response_c = client_c.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {"name": "test-tool", "arguments": {"message": "concurrent"}},
                    "id": 3,
                },
                headers={"Mcp-Session-Id": session_id, "Accept": "application/json, text/event-stream"},
            )

        # Both should succeed
        assert response_b.status_code == 200
        assert response_c.status_code == 200

        # Verify both servers processed their requests
        assert "result" in response_b.json()
        assert "Server C processed" in str(response_c.json().get("result", ""))


class TestSSEResumability:
    """Test SSE stream resumability with event replay."""

    @pytest.mark.skip(reason="Requires SDK-compatible EventStore for SSE resumability")
    @pytest.mark.asyncio
    async def test_sse_stream_resume_after_disconnect(self, redis_storage):
        """Test SSE stream resumption with Last-Event-ID."""
        # This test requires:
        # 1. SDK EventStore implementation compatible with StreamableHTTPSessionManager
        # 2. Event ID generation and tracking in the wrapper
        # 3. Proper cursor management for stream replay

        server = MockMCPServer("A", redis_storage)
        _ = server.create_asgi_app(json_response=False)  # SSE mode

        # Would test:
        # 1. Open SSE stream via GET
        # 2. Receive events with IDs
        # 3. Disconnect
        # 4. Resume with Last-Event-ID header
        # 5. Verify only missed events are replayed
        pass

    @pytest.mark.skip(reason="Requires SDK-compatible EventStore")
    @pytest.mark.asyncio
    async def test_sse_no_duplicate_replay_across_streams(self, redis_storage):
        """Test that events from other streams are not replayed."""
        # Ensures cursor management is per-stream, not global
        pass


class TestSessionTermination:
    """Test session termination scenarios."""

    @pytest.mark.asyncio
    async def test_client_initiated_termination(self, memory_storage):
        """Test client-initiated session termination via DELETE."""
        server = MockMCPServer("A", memory_storage)
        app = server.create_asgi_app(json_response=True)
        with TestClient(app) as client:
            # Initialize session
            init_response = client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "clientInfo": {"name": "test-client", "version": "test"},
                        "capabilities": {},
                    },
                    "id": 1,
                },
                headers={"Accept": "application/json, text/event-stream"},
            )
            session_id = init_response.headers.get("Mcp-Session-Id")

            # Terminate session via DELETE
            delete_response = client.delete("/mcp", headers={"Mcp-Session-Id": session_id})

            # Server may return 405 if it doesn't support client termination
            # or 200/204 if it does
            assert delete_response.status_code in [200, 204, 405]

            if delete_response.status_code != 405:
                # Subsequent request should get 404
                post_delete = client.post(
                    "/mcp",
                    json={"jsonrpc": "2.0", "method": "tools/list", "id": 2},
                    headers={"Mcp-Session-Id": session_id, "Accept": "application/json, text/event-stream"},
                )
                assert post_delete.status_code == 404

                # Client should be able to start new session
                new_init = client.post(
                    "/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-06-18",
                            "clientInfo": {"name": "test-client"},
                            "capabilities": {},
                        },
                        "id": 3,
                    },
                    headers={"Accept": "application/json, text/event-stream"},
                )
                assert new_init.status_code == 200
                new_session_id = new_init.headers.get("Mcp-Session-Id")
                assert new_session_id != session_id

    @pytest.mark.skip(reason="Requires server-side termination signal propagation")
    @pytest.mark.asyncio
    async def test_server_initiated_termination_propagation(self, redis_storage):
        """Test server-initiated termination propagates across cluster."""
        # This test requires:
        # 1. Server-side session termination API
        # 2. Wrapper monitoring of 404 responses
        # 3. Status propagation to storage

        # Would test:
        # 1. Server A terminates session (timeout/error)
        # 2. mcp-db detects termination
        # 3. Server B also returns 404 for same session
        pass


class TestProtocolCompliance:
    """Test protocol version and backwards compatibility."""

    @pytest.mark.asyncio
    async def test_protocol_version_header(self, memory_storage):
        """Test that protocol version header is handled correctly."""
        server = MockMCPServer("A", memory_storage)
        app = server.create_asgi_app(json_response=True)
        with TestClient(app) as client:
            # Initialize session
            init_response = client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "clientInfo": {"name": "test-client", "version": "test"},
                        "capabilities": {},
                    },
                    "id": 1,
                },
                headers={"Accept": "application/json, text/event-stream"},
            )
            session_id = init_response.headers.get("Mcp-Session-Id")

            # Send request with protocol version header
            with_version = client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "method": "tools/list", "id": 2},
                headers={
                    "Mcp-Session-Id": session_id,
                    "MCP-Protocol-Version": "2025-06-18",
                    "Accept": "application/json, text/event-stream",
                },
            )
            assert with_version.status_code == 200

            # Without version header should still work (backwards compat)
            without_version = client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "method": "tools/list", "id": 3},
                headers={"Mcp-Session-Id": session_id, "Accept": "application/json, text/event-stream"},
            )
            assert without_version.status_code == 200


class TestLoadBalancing:
    """Test load balancer scenarios."""

    @pytest.mark.asyncio
    async def test_round_robin_session_persistence(self, memory_storage):
        """Test session works correctly with round-robin load balancing."""
        servers = [MockMCPServer(str(i), memory_storage) for i in range(3)]
        apps = [s.create_asgi_app(json_response=True) for s in servers]

        # Open clients for all servers first, then initialize on the first
        import contextlib

        with contextlib.ExitStack() as stack:
            clients = [stack.enter_context(TestClient(app)) for app in apps]
            c0 = clients[0]
            init_response = c0.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "clientInfo": {"name": "test-client", "version": "test"},
                        "capabilities": {},
                    },
                    "id": 1,
                },
                headers={"Accept": "application/json, text/event-stream"},
            )
            session_id = init_response.headers.get("Mcp-Session-Id")
            c0.post(
                "/mcp",
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers={"Mcp-Session-Id": session_id, "Accept": "application/json, text/event-stream"},
            )

            # Round-robin requests across all servers using persistent clients (run() once per app)
            for i, client in enumerate(clients):
                # Warm each server with initialized before first call
                client.post(
                    "/mcp",
                    json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                    headers={"Mcp-Session-Id": session_id, "Accept": "application/json, text/event-stream"},
                )
                response = client.post(
                    "/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "method": "tools/call",
                        "params": {"name": "test-tool", "arguments": {"message": f"request-{i}"}},
                        "id": i + 2,
                    },
                    headers={"Mcp-Session-Id": session_id, "Accept": "application/json, text/event-stream"},
                )
                assert response.status_code == 200
                result = response.json()
                assert "processed" in str(result.get("result", "")).lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
