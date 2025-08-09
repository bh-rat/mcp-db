from __future__ import annotations

import json
from typing import AsyncIterator

import anyio
from mcp.types import JSONRPCMessage
from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse, StreamingResponse
from starlette.routing import Route

from mcp_db.event.inmemory import InMemoryEventStore

# Simple SSE demo using EventStore to assign per-stream event IDs and support
# Last-Event-ID based resumability. This is not a full MCP server; it focuses
# solely on the resumability mechanism described in the spec.

event_store = InMemoryEventStore()
STREAM_ID = "demo-stream"


async def sse(request):
    last_event_id = request.headers.get("Last-Event-ID")

    async def event_publisher() -> AsyncIterator[str]:
        # 1) If resuming, replay events that occurred after last_event_id on the SAME stream
        if last_event_id:
            send, recv = anyio.create_memory_object_stream[str](50)

            async def _enqueue(ev):
                try:
                    data = json.dumps(ev.message.model_dump(by_alias=True))
                    await send.send(f"id: {ev.event_id}\ndata: {data}\n\n")
                except Exception:
                    # Skip events that fail to serialize
                    pass

            await event_store.replay_events_after(last_event_id, _enqueue)
            await send.aclose()

            async with recv:
                async for item in recv:
                    yield item

        # 2) After replay, keep streaming live events pushed by /publish
        live_send, live_recv = anyio.create_memory_object_stream[str](100)
        request.app.state.live_sse_send = live_send

        async with live_recv:
            async for item in live_recv:
                yield item

    return StreamingResponse(
        event_publisher(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


async def publish(request):
    # Accept JSON-RPC messages; store as events on STREAM_ID with a unique event id
    payload = await request.json()
    message = JSONRPCMessage.model_validate(payload)
    eid = await event_store.store_event(STREAM_ID, message)

    # Broadcast to any connected SSE client(s)
    live_send = getattr(request.app.state, "live_sse_send", None)
    if live_send is not None:
        try:
            data = json.dumps(message.model_dump(by_alias=True))
            await live_send.send(f"id: {eid}\ndata: {data}\n\n")
        except Exception:
            # Connection might be closed, ignore
            pass

    return JSONResponse({"stored_event_id": eid})


async def root(_):
    return PlainTextResponse(
        "Resumability demo: POST /publish with a JSON-RPC message; GET /sse (optionally with Last-Event-ID)"
    )


app = Starlette(
    routes=[
        Route("/", root, methods=["GET"]),
        Route("/sse", sse, methods=["GET"]),
        Route("/publish", publish, methods=["POST"]),
    ]
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=5050)
