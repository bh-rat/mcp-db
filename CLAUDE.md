# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

MCP-DB is a session storage wrapper for Model Context Protocol (MCP) servers that provides protocol interception, session persistence, event sourcing, basic caching, and resilience utilities. It's transport-agnostic and can wrap any MCP server endpoint (ASGI HTTP/SSE) or handler-based servers.

## Development Commands

### Installation
```bash
# Install with pip (includes core dependencies)
pip install -e .

# Install with Redis support
pip install -e ".[redis]"
```

### Running Redis Locally
```bash
# Start Redis container for storage backend
docker compose up -d redis

# Monitor Redis (examples/redis_monitor.py available for debugging)
python examples/redis_monitor.py
```

### Code Quality
```bash
# Run linting with ruff
ruff check src/

# Fix linting issues
ruff check --fix src/

# Format code
ruff format src/
```

### Running Examples
```bash
# Start example server with Redis storage
python examples/streamable_http_server.py --port 3000

# Run example client
python examples/streamable_http_client.py
```

## Architecture

### Core Components

1. **Storage Layer** (`src/mcp_db/storage/`)
   - `InMemoryStorage`: Development storage adapter
   - `RedisStorage`: Production-ready persistent storage using Redis
   - All adapters implement the base `StorageAdapter` interface

2. **Interception Layer** (`src/mcp_db/core/`)
   - `ProtocolInterceptor`: Intercepts JSON-RPC messages at transport boundary
   - `ASGITransportWrapper`: ASGI middleware for wrapping HTTP/SSE endpoints
   - `MCPStorageWrapper`: Generic wrapper for handler-based servers

3. **Session Management** (`src/mcp_db/core/`)
   - `SessionManager`: Manages MCP session lifecycle and state
   - `EventStore`: Implements event sourcing for session history
   - Sessions are identified by server-provided IDs (from headers or params)

4. **Data Models** (`src/mcp_db/core/models.py`)
   - `MCPSession`: Session state and metadata
   - `MCPEvent`/`BaseEvent`: Event sourcing models
   - `SessionStatus`: Session lifecycle states (INITIALIZING, ACTIVE, CLOSED)

### Integration Pattern

The library wraps MCP servers at the transport layer:

1. Create storage adapter (InMemory or Redis)
2. Initialize EventStore and SessionManager with storage
3. Create ProtocolInterceptor with SessionManager
4. Wrap ASGI app with ASGITransportWrapper
5. Mount wrapped app in your server framework

Session IDs are extracted from:
- Message params (`session_id`)
- HTTP headers (`mcp-session-id`, `x-mcp-session-id`)
- SSE headers (`last-event-id`)

The interceptor tracks all JSON-RPC messages, storing them as events while sessions are persisted to the configured storage backend.

## Key Design Decisions

- **Transport-agnostic**: Works with any MCP transport (HTTP, SSE, WebSocket via adapters)
- **Non-intrusive**: Wraps at transport boundary; MCP handlers remain unaware
- **Event sourcing**: All protocol messages stored as events for audit/replay
- **Session tracking**: Uses server-provided session IDs, never generates own IDs
- **Resilience**: Built-in retry logic and circuit breaker patterns in utils

## Dependencies

Core dependencies (from pyproject.toml):
- `mcp>=1.12.4` - MCP SDK
- `starlette>=0.47.2` - ASGI framework
- `redis>=5.0.0` - Redis client (optional)
- `pydantic>=2.11.7` - Data validation
- `anyio>=4.10.0` - Async utilities