from __future__ import annotations

import enum
import time
import typing as t
from dataclasses import dataclass, field


class SessionStatus(str, enum.Enum):
    INITIALIZING = "INITIALIZING"
    INITIALIZED = "INITIALIZED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RECOVERING = "RECOVERING"
    CLOSED = "CLOSED"


Capabilities = t.Dict[str, t.Any]


@dataclass
class MCPSession:
    id: str
    status: SessionStatus
    client_id: str
    server_id: str
    capabilities: Capabilities
    metadata: t.Dict[str, t.Any] = field(default_factory=dict)
    created_at: float = field(default_factory=lambda: time.time())
    updated_at: float = field(default_factory=lambda: time.time())
    last_event_id: t.Optional[str] = None


# Event sourcing model
@dataclass
class BaseEvent:
    event_id: str
    session_id: str
    event_type: str
    timestamp: float = field(default_factory=lambda: time.time())
    payload: t.Dict[str, t.Any] = field(default_factory=dict)


MCPEvent = BaseEvent
