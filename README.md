# mcp-db - session and event storage implementations for MCP servers

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
![Project Status: Experimental](https://img.shields.io/badge/status-experimental-red)

> ⚠️ **Experimental Library**: This project is in an experimental phase and is not yet published to PyPI. To use it, you'll need to install directly from the source.

---

Distributed session coordination for Model Context Protocol (MCP) servers. It intercepts MCP Streamable HTTP traffic (JSON + SSE), persists sessions and events, and enables cross-node admission/warming so any node can serve any existing session behind a load balancer.

### Features
- Transport-level interception (ASGI) — no handler changes
- Persistent sessions (uses server-provided `Mcp-Session-Id`) + event sourcing
- Redis storage (sessions as JSON; events in Redis Streams)
- Cross-node admission — reconstruct SDK transport on any node
- Optional per-node warm-up for ACTIVE sessions (internal `notifications/initialized`)
- Examples: single node, round-robin load balancer, Redis monitor

### Use Cases

- **Persistent Session Storage**: Store MCP sessions and event streams in Redis or other backends. Sessions survive server restarts and can be queried for state reconstruction.

- **High Availability**: Eliminate single points of failure with automatic session failover. When servers crash or restart, other nodes seamlessly take over active sessions.

- **Zero-Downtime Deployments**: Perform rolling updates and blue-green deployments while preserving session continuity. New instances immediately serve existing sessions from Redis.

- **Horizontal Scaling**: Run MCP servers behind load balancers without sticky sessions. Any server instance can handle any request for existing sessions.

- **Audit & Compliance**: Capture complete session history through event sourcing. Every protocol message is persisted for debugging, monitoring, and regulatory compliance.

### Requirements
- Python >= 3.10
- MCP SDK 1.12.x
- Redis >= 7 (for streams)

### Install

Since this library is not yet published to PyPI, install from source:

```bash
# Clone the repository
git clone https://github.com/yourusername/mcp-db.git
cd mcp-db

# Install with uv (recommended)
uv pip install -e .

# Or install with pip
pip install -e .

# For Redis support
pip install -e ".[redis]"
```

### Quick Start (Streamable HTTP)

1) Create your MCP server using the MCP SDK (`StreamableHTTPSessionManager`).

2) Wire the wrapper with storage-backed `SessionManager` + `EventStore`:

```python
from mcp_db.core.session_manager import SessionManager
from mcp_db.core.interceptor import ProtocolInterceptor
from mcp_db.core.asgi_wrapper import ASGITransportWrapper
from mcp_db.core.admission import StreamableHTTPAdmissionController
from mcp_db.session import RedisStorage

# Assume you have MCP SDK session_manager from your app

# Setup mcp-db components
storage = RedisStorage(url="redis://localhost:6379/0", prefix="mcp")
db_session_manager = SessionManager(storage=storage, event_store=None)
interceptor = ProtocolInterceptor(db_session_manager)
admission = StreamableHTTPAdmissionController(manager=session_manager, app=app)

async def handle_streamable_http(scope, receive, send):
    await session_manager.handle_request(scope, receive, send)

wrapped_asgi = ASGITransportWrapper(
    interceptor,
    admission_controller=admission,
    session_lookup=db_session_manager.get,  # optional: lets the wrapper consult storage
).wrap(handle_streamable_http)
```

3) Mount `wrapped_asgi` to your ASGI app at your MCP endpoint path (e.g., `/mcp`).

### Distributed scaling quickstart

Run two servers and a simple round-robin LB that alternates requests:

```bash
# Terminals 1 & 2: run servers
uv run python -m examples.streamable_http_server --port 3001
uv run python -m examples.streamable_http_server --port 3002

# Terminal 3: run the LB
uv run python -m examples.round_robin_lb \
  --listen-port 3000 \
  --backend http://127.0.0.1:3001 \
  --backend http://127.0.0.1:3002

# Terminal 4: run the client via the LB
# Streamable HTTP (POST+SSE)
uv run python -m examples.streamable_http_client --base http://127.0.0.1:3000/mcp/ --shttp

# Or JSON mode
uv run python -m examples.streamable_http_client --base http://127.0.0.1:3000/mcp/ --no-shttp

# Exercise follow-up calls on an existing session (works across nodes)
uv run python -m examples.continue_session <SESSION_ID> --base http://127.0.0.1:3000/mcp/ --shttp
```

How it works:
- Initialize: SDK creates a transport and returns `Mcp-Session-Id`; wrapper persists a session record (INITIALIZED).
- notifications/initialized: wrapper marks the session ACTIVE in storage.
- Subsequent requests on any node: wrapper reconstructs the SDK transport for that session ID before the SDK checks its in-memory map. For ACTIVE sessions, the wrapper can warm the node once.


### Resumability demo (Last-Event-ID)

Run either the MCP example (uses SDK’s EventStore) or a minimal SSE demo:

```bash
# MCP example server (includes request-tied SSE and standalone GET stream)
# In-memory EventStore:
uv run python -m examples.streamable_http_server --port 3000 --event-store memory
# Or Redis-backed EventStore:
uv run python -m examples.streamable_http_server --port 3000 --event-store redis --redis-url redis://localhost:6379/0 --redis-prefix mcp
uv run python -m examples.streamable_http_client --base http://127.0.0.1:3000/mcp/ --shttp

# Minimal SSE-only demo
uv run python -m examples.resumability_demo

# Terminal A: stream SSE (no Last-Event-ID initially)
curl -N http://127.0.0.1:5050/sse

# Terminal B: publish some JSON-RPC messages (each becomes an SSE event with an id)
curl -s -X POST http://127.0.0.1:5050/publish \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# Simulate disconnect, then resume with Last-Event-ID=<last seen id> to receive only later events
curl -N -H 'Last-Event-ID: <paste-last-id-here>' http://127.0.0.1:5050/sse
```

Behavior:
- **Per-stream IDs**: IDs are assigned per stream and act as a cursor only within that stream.
- **Replay on resume**: When `Last-Event-ID` is provided, only events after that ID on the same stream are replayed; other streams are not replayed.
- **Live continuation**: After replay, new events are delivered live.

Short (quick try):

```bash
uv run python -m examples.resumability_demo
curl -N http://127.0.0.1:5050/sse
curl -N -H 'Last-Event-ID: <id>' http://127.0.0.1:5050/sse
```

### Limitations (concise)

- GET/SSE (Client features like sampling/elicitation) is per-node: live streams/queues exist only on the node that accepted GET;
- Persistence ≠ live streams: storing sessions/events doesn’t recreate anyio streams; use ownership routing or reconnect+`Last-Event-ID` replay.
- SDK supported `event_store` pending: sdk supported event store is still pending.

Planned
- Ownership routing example; SDK EventStore wiring; explore `mcp_db.transport` for enhanced cross-node continuity.


### Notes & tips
- Clients must send both `Accept: application/json, text/event-stream` and `Content-Type: application/json`.
- For Streamable HTTP, parse SSE `data:` lines for responses/events.
- The wrapper never generates session IDs; it stores the ID provided by the server transport.
- Prefer `uv run` for running examples.

### License
Apache-2.0

