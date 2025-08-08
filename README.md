## mcp-db

Session storage wrapper for Model Context Protocol (MCP) servers. Provides protocol interception, session persistence, event sourcing, basic caching, and resilience utilities.

### Install

```bash
pip install mcp-db
```

### Quick Start (Streamable HTTP)

1. Create your MCP server using the MCP SDK (e.g., `StreamableHTTPSessionManager`).
2. Wrap the ASGI endpoint with `ASGITransportWrapper(interceptor).wrap(asgi_app)`.
3. Use any `StorageAdapter` (memory, Redis) via `SessionManager` + `EventStore`.

Example wiring:

```python
from mcp_db.core.event_store import EventStore
from mcp_db.core.session_manager import SessionManager
from mcp_db.core.interceptor import ProtocolInterceptor
from mcp_db.core.asgi_wrapper import ASGITransportWrapper
from mcp_db.storage import InMemoryStorage, RedisStorage

# For development
storage = InMemoryStorage()
# Or use Redis for persistence
# storage = RedisStorage(url="redis://localhost:6379/0", prefix="mcp")
event_store = EventStore(storage)
sessions = SessionManager(storage=storage, event_store=event_store)
interceptor = ProtocolInterceptor(sessions)
wrapped_asgi = ASGITransportWrapper(interceptor).wrap(streamable_http_app)
```

### Run Redis locally

```bash
docker compose up -d redis
```

Then configure your app to use:

```python
from mcp_db.storage import RedisStorage
storage = RedisStorage(url="redis://localhost:6379/0", prefix="mcp")
```

### Notes
- Transport-agnostic: wrap any server endpoint (ASGI HTTP/SSE) or handler-based servers.
- Redis adapter uses aioredis. Install with `pip install aioredis`.

