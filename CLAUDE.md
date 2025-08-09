# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

MCP-DB is a distributed session coordination layer for Model Context Protocol (MCP) servers. It enables stateless MCP servers to run behind load balancers by providing:

- **Transport-level interception** of MCP Streamable HTTP traffic (JSON + SSE)
- **Session persistence** to Redis or in-memory storage
- **Event sourcing** for complete session history
- **Cross-node session rehydration** allowing any node to serve any existing session
- **Optional local caching** for performance optimization
- **Resilience utilities** with retry logic and circuit breakers

The key value proposition: Deploy MCP servers in a stateless, horizontally-scalable manner while maintaining session continuity across nodes.

## Installation

```bash
# Using uv (recommended)
uv pip install -e .

# Install with Redis support
uv pip install -e ".[redis]"

# Install development dependencies (includes testing)
uv pip install -e ".[dev]"

# Install test dependencies only
uv pip install -e ".[test]"
```

## Development Commands

### Running Redis Locally
```bash
# Start Redis container (required for distributed features)
docker compose up -d redis

# Check Redis is running
docker compose ps

# Monitor Redis activity (useful for debugging)
python -m examples.redis_monitor
```

### Code Quality
```bash
# Run linting
uv run ruff check src/

# Fix linting issues automatically
uv run ruff check --fix src/

# Format code
uv run ruff format src/

# Run all checks before committing
uv run ruff check --fix src/ && uv run ruff format src/
```

### Testing
```bash
# Run unit tests (no Redis required)
uv run pytest tests/integration/test_simple_session.py -v

# Run integration tests (requires Redis)
uv run pytest tests/integration/test_distributed_sessions.py -v -m "not skip"

# Run all tests
uv run pytest tests/ -v

# Run tests excluding those requiring Redis
uv run pytest tests/ -v -m "not requires_redis"
```

## Architecture

### Core Components

1. **Storage Layer** (`src/mcp_db/storage/`)
   - `StorageAdapter`: Abstract interface for storage backends
   - `InMemoryStorage`: Development/testing storage
   - `RedisStorage`: Production storage with Redis Streams

2. **Caching Layer** (`src/mcp_db/cache/`)
   - `LocalCache`: Optional LRU + TTL cache (configurable via `use_local_cache`)

3. **Session Management** (`src/mcp_db/core/`)
   - `SessionManager`: Manages session lifecycle with optional caching
   - `EventStore`: Event sourcing for session history
   - `ProtocolInterceptor`: Intercepts JSON-RPC messages
   - Session states: INITIALIZED → ACTIVE → CLOSED

4. **Transport Wrapping** (`src/mcp_db/core/`)
   - `ASGITransportWrapper`: ASGI middleware for HTTP/SSE
   - `MCPStorageWrapper`: Generic wrapper for handler-based servers

5. **Admission Control** (`src/mcp_db/core/admission.py`)
   - `StreamableHTTPAdmissionController`: Rehydrates SDK transport for unknown sessions
   - Handles session warming for ACTIVE sessions

6. **Data Models** (`src/mcp_db/core/models.py`)
   - `MCPSession`, `MCPEvent`/`BaseEvent`, `SessionStatus`

### Integration Pattern

```python
# 1. Setup storage and persistence
storage = RedisStorage(url="redis://localhost:6379/0", prefix="mcp")
db_event_store = EventStore(storage)
db_sessions = SessionManager(
    storage=storage, 
    event_store=db_event_store,
    use_local_cache=True  # Optional: enable local caching
)

# 2. Create interceptor and admission controller
interceptor = ProtocolInterceptor(db_sessions)
admission = StreamableHTTPAdmissionController(manager=session_manager, app=app)

# 3. Wrap the ASGI transport
wrapped_asgi = ASGITransportWrapper(
    interceptor,
    admission_controller=admission,
    session_lookup=db_sessions.get,
).wrap(handle_streamable_http)

# 4. Mount in your ASGI app
starlette_app = Starlette(
    routes=[Mount("/mcp", app=wrapped_asgi)],
    lifespan=lifespan
)
```

## Examples

### Available Example Scripts

1. **`streamable_http_server.py`** - MCP server with mcp-db wrapper
   ```bash
   python -m examples.streamable_http_server --port 3000 --json-response
   ```

2. **`streamable_http_client.py`** - Test client for MCP servers
   ```bash
   python -m examples.streamable_http_client --base http://127.0.0.1:3000/mcp/ --no-shttp
   ```

3. **`continue_session.py`** - Continue an existing session (tests cross-node capability)
   ```bash
   python -m examples.continue_session <SESSION_ID> --base http://127.0.0.1:3000/mcp/
   ```

4. **`round_robin_lb.py`** - Simple load balancer for testing distributed deployment
   ```bash
   python -m examples.round_robin_lb \
     --listen-port 3000 \
     --backend http://127.0.0.1:3001 \
     --backend http://127.0.0.1:3002
   ```

5. **`redis_monitor.py`** - Monitor Redis for debugging
   ```bash
   python -m examples.redis_monitor
   ```

### Distributed Deployment Demo

```bash
# Terminal 1: Start first server
python -m examples.streamable_http_server --port 3001

# Terminal 2: Start second server
python -m examples.streamable_http_server --port 3002

# Terminal 3: Start load balancer
python -m examples.round_robin_lb \
  --listen-port 3000 \
  --backend http://127.0.0.1:3001 \
  --backend http://127.0.0.1:3002

# Terminal 4: Run client through load balancer
python -m examples.streamable_http_client --base http://127.0.0.1:3000/mcp/

# Terminal 5: Continue session on different node
# (use session ID from Terminal 4 output)
python -m examples.continue_session <SESSION_ID> --base http://127.0.0.1:3000/mcp/
```

## Distributed Deployment

### How Session Migration Works

1. **Session Creation**: Server A creates session, stores in Redis via mcp-db
2. **Session ID**: Client receives `Mcp-Session-Id` header from server
3. **Request to Different Node**: Client sends request with session ID to Server B
4. **Admission Control**: Server B's admission controller detects unknown session
5. **Session Rehydration**: mcp-db reconstructs SDK transport from Redis data
6. **Request Processing**: Server B handles request as if session was local
7. **Session Warming**: For ACTIVE sessions, synthetic `notifications/initialized` sent internally

### Requirements for Distributed Setup

- **Redis**: Required for shared session storage (Redis 7+ for Streams support)
- **Load Balancer**: Any HTTP load balancer (nginx, HAProxy, ALB, etc.)
- **No Sticky Sessions**: mcp-db eliminates need for session affinity
- **Shared Storage**: All nodes must connect to same Redis instance/cluster

### Redis Configuration

```python
# Production Redis with connection pooling
storage = RedisStorage(
    url="redis://redis.example.com:6379/0",
    prefix="mcp_prod",  # Namespace for keys
    stream_maxlen=10000  # Limit event stream size
)

# Development with local Redis
storage = RedisStorage(url="redis://localhost:6379/0", prefix="mcp_dev")
```

## Key Design Decisions

1. **Transport-agnostic**: Works at ASGI/transport layer, not application layer
2. **Non-intrusive**: MCP handlers remain unaware of wrapper
3. **Server-provided IDs**: Never generates session IDs, uses server's IDs
4. **Event sourcing**: Complete audit trail of all protocol messages
5. **Optional local caching**: `use_local_cache` parameter for performance tuning
6. **Resilience patterns**: Built-in retries and circuit breakers
7. **Cross-node warming**: Automatic session rehydration on new nodes
8. **No code changes**: Existing MCP servers work without modification

## Troubleshooting

### Common Issues

1. **"Task group is not initialized" error in tests**
   - Cause: Using Starlette TestClient with StreamableHTTPSessionManager
   - Solution: Use real HTTP clients or test components directly

2. **Session not found on different node**
   - Cause: Redis not running or not shared between nodes
   - Solution: Ensure all nodes connect to same Redis instance

3. **Invalid request parameters (-32602) error**
   - Cause: Session not properly rehydrated on new node
   - Solution: Check admission controller configuration and Redis connectivity

4. **Tests failing with "Redis not available"**
   - Cause: Redis not running
   - Solution: Run `docker compose up -d redis`

5. **Linting errors for relative imports**
   - Cause: Ruff enforces absolute imports from parent modules
   - Solution: Use absolute imports like `from mcp_db.storage import ...`

### Testing Requirements

- **Unit tests**: No external dependencies required
- **Integration tests**: Require Redis running locally
- **Distributed tests**: Require Redis and ability to spawn multiple processes

### Performance Considerations

- **Local caching**: Enable for read-heavy workloads
- **Redis connection pooling**: Built into redis-py client
- **Event stream size**: Configure `stream_maxlen` to limit memory usage
- **Circuit breaker**: Prevents cascading failures on storage issues

## Dependencies

Core dependencies (from pyproject.toml):
- `mcp>=1.12.4` - MCP SDK for protocol implementation
- `starlette>=0.47.2` - ASGI framework for HTTP/SSE
- `redis>=5.0.0` - Redis client for distributed storage
- `pydantic>=2.11.7` - Data validation and models
- `anyio>=4.10.0` - Async utilities
- `httpx>=0.28.1` - HTTP client for examples
- `click>=8.2.1` - CLI for example scripts
- `uvicorn>=0.35.0` - ASGI server for running examples

## Important Notes

- Always use `uv run` for running examples to ensure correct environment
- Session IDs are extracted from headers (`Mcp-Session-Id`) or params
- The wrapper is transparent - MCP handlers don't know it exists
- Local cache is per-instance, Redis is shared across all instances
- Event sourcing provides complete audit trail but increases storage usage