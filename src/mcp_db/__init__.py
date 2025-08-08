"""mcp_db

A standalone storage wrapper for MCP servers providing session persistence,
event sourcing, caching, and resilience utilities.

This package is self-contained and does not import non-stdlib dependencies.
"""

from .core.wrapper import MCPStorageWrapper
from .core.asgi_wrapper import ASGITransportWrapper
from .core.interceptor import ProtocolInterceptor
from .core.session_manager import SessionManager
from .core.event_store import EventStore
from .core.admission import (
    TransportAdmissionController,
    StreamableHTTPAdmissionController,
)
from .core.models import (
    MCPSession,
    SessionStatus,
    MCPEvent,
)

__all__ = [
    "MCPStorageWrapper",
    "ASGITransportWrapper",
    "ProtocolInterceptor",
    "SessionManager",
    "EventStore",
    "MCPSession",
    "SessionStatus",
    "MCPEvent",
    "TransportAdmissionController",
    "StreamableHTTPAdmissionController",
]

__version__ = "0.1.0"


