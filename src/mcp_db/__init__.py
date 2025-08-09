"""mcp_db

A standalone storage wrapper for MCP servers providing session persistence,
event sourcing, caching, and resilience utilities.

This package is self-contained and does not import non-stdlib dependencies.
"""

from .core.admission import (
    StreamableHTTPAdmissionController,
    TransportAdmissionController,
)
from .core.asgi_wrapper import ASGITransportWrapper
from .core.interceptor import ProtocolInterceptor
from .core.models import (
    MCPEvent,
    MCPSession,
    SessionStatus,
)
from .core.session_manager import SessionManager
from .core.wrapper import MCPStorageWrapper
from .event import (
    EventCallback,
    EventId,
    EventMessage,
    EventStore,
    InMemoryEventStore,
    RedisEventStore,
    StreamId,
)
from .session import (
    InMemoryStorage,
    StorageAdapter,
)

__all__ = [
    "MCPStorageWrapper",
    "ASGITransportWrapper",
    "ProtocolInterceptor",
    "SessionManager",
    "EventStore",
    "EventId",
    "StreamId",
    "EventMessage",
    "EventCallback",
    "InMemoryEventStore",
    "RedisEventStore",
    "StorageAdapter",
    "InMemoryStorage",
    "MCPSession",
    "SessionStatus",
    "MCPEvent",
    "TransportAdmissionController",
    "StreamableHTTPAdmissionController",
]

__version__ = "0.1.0"
