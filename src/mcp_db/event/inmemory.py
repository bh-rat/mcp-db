from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict
from uuid import uuid4

from .base import EventStore
from .types import EventCallback, EventId, EventMessage, JSONRPCMessage, StreamId

_logger = logging.getLogger(__name__)


@dataclass
class EventEntry:
    event_id: EventId
    stream_id: StreamId
    message: JSONRPCMessage


class InMemoryEventStore(EventStore):
    def __init__(self, max_events_per_stream: int = 100) -> None:
        self._max_events_per_stream = max_events_per_stream
        self._streams: Dict[StreamId, Deque[EventEntry]] = {}
        self._event_index: Dict[EventId, EventEntry] = {}

    async def store_event(self, stream_id: StreamId, message: JSONRPCMessage) -> EventId:
        event_id: EventId = str(uuid4())
        entry = EventEntry(event_id=event_id, stream_id=stream_id, message=message)

        if stream_id not in self._streams:
            self._streams[stream_id] = deque(maxlen=self._max_events_per_stream)

        stream_deque = self._streams[stream_id]
        # If about to reach cap, preemptively remove oldest from index
        if len(stream_deque) == self._max_events_per_stream and stream_deque:
            oldest = stream_deque[0]
            self._event_index.pop(oldest.event_id, None)

        stream_deque.append(entry)
        self._event_index[event_id] = entry
        return event_id

    async def replay_events_after(self, last_event_id: EventId, send_callback: EventCallback) -> StreamId | None:
        last_entry = self._event_index.get(last_event_id)
        if last_entry is None:
            _logger.warning("Event ID %s not found in store", last_event_id)
            return None

        stream_id = last_entry.stream_id
        stream_events = self._streams.get(stream_id)
        if not stream_events:
            return stream_id

        found_last = False
        for entry in stream_events:
            if found_last:
                await send_callback(EventMessage(entry.message, entry.event_id))
            elif entry.event_id == last_event_id:
                found_last = True

        return stream_id
