# Project Roadmap

This roadmap outlines the vision, milestones, and priorities for mcp-db (session and event persistence for MCP) and the distributed transport layers.

## Vision

Enable any MCP server to run statelessly behind a load balancer, with protocol-compliant session persistence, event sourcing, and zero-code changes in application handlers. Any node can accept any request for an existing MCP session.

## Status (alpha)

- Pre-1.0: minor releases may introduce breaking changes.

- Transport wrapper: ASGI transport-level interception (JSON + SSE) [alpha]
- Redis storage adapter, event streams, session records [alpha]
- Distributed admission controller (rehydrate SDK transport) [alpha]
- Streamable HTTP examples + round-robin LB demo [alpha]

Target maturity for beta: end-to-end resiliency (locks, idempotency), metrics.


## Themes & Milestones

### v0.2.x – Stabilization and UX

- [ ] Admission controller hardening
  - [ ] Handle initialized/notifications/initialized flows reliably across nodes
  - [ ] Defensive admission under partial DB/state conditions
- [ ] SSE correctness and backpressure
  - [ ] Ensure wrapper never interferes with SSE chunking and disconnect semantics
  - [ ] Client examples for both JSON and SHTTP (SSE on POST)
- [ ] Session Lifecycle Management
  - [ ] Fix session creation race condition between header processing and body handling
  - [ ] Implement comprehensive session closure handling (client disconnects, timeouts, DELETE requests)
  - [ ] Add session expiry/TTL mechanism for abandoned sessions in Redis
- [ ] Streamable HTTP Compliance
  - [ ] Ensure proper session state transitions (INITIALIZING → INITIALIZED → ACTIVE → CLOSED) are maintained consistently across distributed nodes
  - [ ] Ensure session state transitions are atomic and consistent across nodes
  - [ ] **[IMPORTANT]** Add validation for session state before processing requests - prevent processing requests for sessions in wrong states
- [ ] Examples
  - [ ] Round-robin LB example (done) – refine and document
  - [ ] Multi-node docker-compose example (2 servers + Redis + LB)
- [ ] Documentation
  - [ ] Architecture overview, state diagrams, failure modes
  - [ ] Troubleshooting guide (400s, SSE stalls, header requirements)
- [ ] Testing Infrastructure
  - [ ] Integration test suite for distributed scenarios
  - [ ] Test harness for multi-node session migration
  - [ ] Automated tests for crash recovery scenarios
  - [ ] Load testing framework for concurrent access patterns
- [ ] Custom MCP transport implementation 


### v0.3.0 – Advanced Distribution Features

- [ ] **SDK-compatible EventStore** (Required for SSE resumability tests)
  - [ ] Implement Redis-backed EventStore compatible with `StreamableHTTPSessionManager(event_store=...)`
  - [ ] Support Last-Event-ID replay across instances for SSE stream resumption
  - [ ] Per-stream cursor management (not global replay)
  - [ ] Event ID generation and tracking in wrapper
- [ ] **Session Termination Handling**
  - [ ] Support HTTP DELETE for client-initiated termination
  - [ ] Detect and propagate server-initiated termination (monitor 404 responses)
  - [ ] Clean up terminated sessions from storage
  - [ ] Return proper 404 for terminated sessions across all nodes
- [ ] **Concurrent Access Control**
  - [ ] Implement optimistic concurrency control for session updates
  - [ ] Add distributed locking for critical session state changes
  - [ ] Ensure consistency during concurrent rehydration from multiple nodes
- [ ] Session ownership map: persist `session_id -> instance_id` and add ASGI request forwarding to the owner for all Streamable HTTP requests; instance selection should happen based on this map
- [ ] Admission concurrency: use storage `acquire_lock` around admission and make `ensure_session_transport` idempotent to prevent duplicate transports
- [ ] Status policy: return 404 for unknown/expired sessions (configurable)


## Compatibility

- Python: >= 3.10
- MCP SDK: 1.12.x (tracked; provide matrix as part of CI)
- Redis: >= 7 (streams required)
- Starlette/Uvicorn/AnyIO

## Contribution Guidelines (summary)

- Issues
  - Use labels: bug, enhancement, storage, admission, sse, docs, good-first-issue
  - For significant changes, open an RFC issue first (template upcoming in `.github/`)
- Pull Requests
  - Include tests where feasible (unit/integration)
  - Keep public interfaces typed and documented
  - Note any performance or compatibility considerations
- Testing
  - Unit tests: storage adapters, interceptor, admission controller
  - Integration: examples with Redis + LB (docker-compose)
  - Performance: basic load smoke tests (follow-up tooling)

## How to read this roadmap

Milestones are directional and may shift as we gather feedback. If something you need isn’t on the near-term plan, please open an issue to discuss.


