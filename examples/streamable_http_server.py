#!/usr/bin/env python3

import contextlib
import logging
from collections.abc import AsyncIterator

import anyio
import click
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from pydantic import AnyUrl
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.types import Receive, Scope, Send

from mcp_db.core.admission import StreamableHTTPAdmissionController
from mcp_db.core.asgi_wrapper import ASGITransportWrapper
from mcp_db.event.inmemory import InMemoryEventStore as DbEventStore
from mcp_db.event.redis import RedisEventStore
from mcp_db.core.interceptor import ProtocolInterceptor
from mcp_db.core.session_manager import SessionManager as DbSessionManager
from mcp_db.session.redis_adapter import RedisStorage

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
@click.option(
    "--event-store",
    type=click.Choice(["memory", "redis"], case_sensitive=False),
    default="memory",
    help="Event store to use for resumability",
)
@click.option("--redis-url", default="redis://localhost:6379/0", help="Redis URL for RedisEventStore")
@click.option("--redis-prefix", default="mcp", help="Redis key prefix for RedisEventStore")
def main(port: int, log_level: str, json_response: bool, event_store: str, redis_url: str, redis_prefix: str) -> int:
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
            notification_msg = f"[{i + 1}/{count}] Event from '{caller}' - Use Last-Event-ID to resume if disconnected"
            await app.request_context.session.send_log_message(
                level="info",
                data=notification_msg,
                logger="notification_stream",
                related_request_id=app.request_context.request_id,
            )
            if i < count - 1:
                await anyio.sleep(interval)

        await app.request_context.session.send_resource_updated(uri=AnyUrl("http:///test_resource"))

        # Optional: broadcast on GET stream for resumability demo
        if name == "start-get-stream-broadcast":
            text = arguments.get("text", "demo")
            for i in range(count):
                await app.request_context.session.send_log_message(
                    level="info",
                    data=f"[GET stream] {text} #{i + 1}",
                    logger="get_stream",
                )
                if i < count - 1:
                    await anyio.sleep(interval)

        return [
            types.TextContent(
                type="text",
                text=(f"Sent {count} notifications with {interval}s interval for caller: {caller}"),
            )
        ]

    @app.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="start-notification-stream",
                description=("Sends a stream of notifications with configurable count and interval"),
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
                            "description": ("Identifier of the caller to include in notifications"),
                        },
                    },
                },
            ),
            types.Tool(
                name="start-get-stream-broadcast",
                description=(
                    "Emits notifications on the GET SSE stream (not tied to a request) to demo Last-Event-ID replay"
                ),
                inputSchema={
                    "type": "object",
                    "required": ["interval", "count", "text"],
                    "properties": {
                        "interval": {"type": "number", "description": "Interval between notifications in seconds"},
                        "count": {"type": "number", "description": "Number of notifications to send"},
                        "text": {"type": "string", "description": "Message base text"},
                    },
                },
            ),
        ]

    # Streamable HTTP session manager from MCP SDK
    selected_event_store = (
        DbEventStore() if event_store.lower() == "memory" else RedisEventStore(url=redis_url, prefix=redis_prefix)
    )
    session_manager = StreamableHTTPSessionManager(
        app=app, event_store=selected_event_store, json_response=json_response
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
    db_sessions = DbSessionManager(storage=storage, event_store=None)
    interceptor = ProtocolInterceptor(db_sessions)

    # Admission controller for the SDK manager
    admission = StreamableHTTPAdmissionController(manager=session_manager, app=app)

    # Helper to let wrapper consult storage without importing adapters
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
