"""Unit tests for EventStore (new resumability API)."""

import pytest

from mcp_db.event.inmemory import InMemoryEventStore
from mcp_db.event.types import EventMessage, JSONRPCMessage


@pytest.mark.asyncio
async def test_store_event_generates_unique_ids_per_stream():
    store = InMemoryEventStore()
    a1 = await store.store_event("s-a", JSONRPCMessage(jsonrpc="2.0", id=1, method="ping"))
    a2 = await store.store_event("s-a", JSONRPCMessage(jsonrpc="2.0", id=2, method="pong"))
    b1 = await store.store_event("s-b", JSONRPCMessage(jsonrpc="2.0", id=3, method="ping"))
    assert a1 != a2 and a1 != b1 and a2 != b1


@pytest.mark.asyncio
async def test_replay_only_after_last_event_id_same_stream():
    store = InMemoryEventStore()
    s = "stream-1"
    e1 = await store.store_event(s, JSONRPCMessage(jsonrpc="2.0", id=1, method="a"))
    e2 = await store.store_event(s, JSONRPCMessage(jsonrpc="2.0", id=2, method="b"))
    _ = await store.store_event("stream-2", JSONRPCMessage(jsonrpc="2.0", id=3, method="x"))

    seen: list[EventMessage] = []

    async def cb(ev: EventMessage):
        seen.append(ev)

    rstream = await store.replay_events_after(e1, cb)
    assert rstream == s
    assert [ev.event_id for ev in seen] == [e2]
    assert all(isinstance(ev.message, JSONRPCMessage) for ev in seen)


@pytest.mark.asyncio
async def test_replay_missing_event_returns_none():
    store = InMemoryEventStore()

    async def cb(_ev: EventMessage):
        pytest.fail("callback should not be invoked for missing last_event_id")

    assert await store.replay_events_after("does-not-exist", cb) is None
