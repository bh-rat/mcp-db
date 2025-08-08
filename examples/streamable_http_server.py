#!/usr/bin/env python3

import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Optional

import anyio
import click
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from pydantic import AnyUrl
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.types import Receive, Scope, Send

from mcp_db.core.event_store import EventStore as DbEventStore
from mcp_db.core.session_manager import SessionManager as DbSessionManager
from mcp_db.core.interceptor import ProtocolInterceptor
from mcp_db.core.asgi_wrapper import ASGITransportWrapper
from mcp_db.core.admission import StreamableHTTPAdmissionController
from mcp_db.storage.redis_adapter import RedisStorage


logger = logging.getLogger(__name__)


@click.command()
@click.option("--port", default=3000, help="Port to listen on for HTTP")
@click.option(
    "--log-level",
    default="INFO",
    help="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
)
@click.option(
    "--json-response",
    is_flag=True,
    default=False,
    help="Enable JSON responses instead of SSE streams",
)
def main(port: int, log_level: str, json_response: bool) -> int:
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    # Enable debug logs for wrapper to trace SSE
    logging.getLogger("mcp_db.core.asgi_wrapper").setLevel(logging.DEBUG)

    app = Server("mcp-streamable-http-with-db")

    @app.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.ContentBlock]:
        interval = arguments.get("interval", 1.0)
        count = arguments.get("count", 3)
        caller = arguments.get("caller", "unknown")

        for i in range(count):
            notification_msg = (
                f"[{i + 1}/{count}] Event from '{caller}' - Use Last-Event-ID to resume if disconnected"
            )
            await app.request_context.session.send_log_message(
                level="info",
                data=notification_msg,
                logger="notification_stream",
                related_request_id=app.request_context.request_id,
            )
            if i < count - 1:
                await anyio.sleep(interval)

        await app.request_context.session.send_resource_updated(uri=AnyUrl("http:///test_resource"))
        return [
            types.TextContent(
                type="text",
                text=(
                    f"Sent {count} notifications with {interval}s interval for caller: {caller}"
                ),
            )
        ]

    @app.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="start-notification-stream",
                description=(
                    "Sends a stream of notifications with configurable count and interval"
                ),
                inputSchema={
                    "type": "object",
                    "required": ["interval", "count", "caller"],
                    "properties": {
                        "interval": {
                            "type": "number",
                            "description": "Interval between notifications in seconds",
                        },
                        "count": {
                            "type": "number",
                            "description": "Number of notifications to send",
                        },
                        "caller": {
                            "type": "string",
                            "description": (
                                "Identifier of the caller to include in notifications"
                            ),
                        },
                    },
                },
            )
        ]

    # Streamable HTTP session manager from MCP SDK
    session_manager = StreamableHTTPSessionManager(
        app=app,
        event_store=None,  # For resumability, plug in the SDK's InMemoryEventStore or a persistent one
        json_response=json_response,
    )

    async def handle_streamable_http(scope: Scope, receive: Receive, send: Send) -> None:
        await session_manager.handle_request(scope, receive, send)

    @contextlib.asynccontextmanager
    async def lifespan(starlette_app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            logger.info("Application started with StreamableHTTP session manager!")
            try:
                yield
            finally:
                logger.info("Application shutting down...")

    # mcp-db storage wrapper components (transport-level only; handlers remain unaware)
    storage = RedisStorage(url="redis://localhost:6379/0", prefix="mcp")
    db_event_store = DbEventStore(storage)
    db_sessions = DbSessionManager(storage=storage, event_store=db_event_store)
    interceptor = ProtocolInterceptor(db_sessions)

    # Admission controller for the SDK manager
    admission = StreamableHTTPAdmissionController(manager=session_manager, app=app)

    # Helper to let wrapper consult storage without importing adapters
    async def lookup_session(session_id: str):
        sess = await db_sessions.get(session_id)
        return None if sess is None else {
            "id": sess.id,
            "status": getattr(sess.status, "value", str(sess.status)),
            "client_id": sess.client_id,
            "server_id": sess.server_id,
            "capabilities": sess.capabilities,
            "metadata": sess.metadata,
        }

    # Wrap the ASGI transport for the mounted MCP endpoint
    wrapped_mcp_asgi = ASGITransportWrapper(
        interceptor,
        admission_controller=admission,
        session_lookup=lookup_session,
    ).wrap(handle_streamable_http)

    starlette_app = Starlette(
        debug=True,
        routes=[Mount("/mcp", app=wrapped_mcp_asgi)],
        lifespan=lifespan,
    )

    import uvicorn

    uvicorn.run(starlette_app, host="127.0.0.1", port=port)
    return 0


if __name__ == "__main__":
    main()


