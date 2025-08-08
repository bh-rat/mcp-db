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
- [ ] Examples
  - [ ] Round-robin LB example (done) – refine and document
  - [ ] Multi-node docker-compose example (2 servers + Redis + LB)
- [ ] Documentation
  - [ ] Architecture overview, state diagrams, failure modes
  - [ ] Troubleshooting guide (400s, SSE stalls, header requirements)
- [ ] Custom MCP transport implementation 


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


