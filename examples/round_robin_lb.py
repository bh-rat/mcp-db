#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

import anyio
import click
import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import StreamingResponse
from starlette.routing import Route


logger = logging.getLogger(__name__)


class RoundRobin:
    def __init__(self, backends: list[str]) -> None:
        if len(backends) < 2:
            raise ValueError("Provide at least two backends")
        self._backends = backends
        self._index = 0
        self._lock = anyio.Lock()

    async def next(self) -> str:
        async with self._lock:
            url = self._backends[self._index]
            self._index = (self._index + 1) % len(self._backends)
            return url


def _filtered_response_headers(upstream: httpx.Response) -> dict[str, str]:
    hop_by_hop = {
        "connection",
        "transfer-encoding",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "upgrade",
        # Content-Length will be managed by Starlette when needed
        "content-length",
    }
    headers: dict[str, str] = {}
    for k, v in upstream.headers.items():
        if k.lower() in hop_by_hop:
            continue
        headers[k] = v
    return headers


async def proxy_handler(request: Request) -> StreamingResponse:
    rr: RoundRobin = request.app.state.rr  # type: ignore[attr-defined]
    client: httpx.AsyncClient = request.app.state.client  # type: ignore[attr-defined]

    backend_base = await rr.next()
    upstream_url = f"{backend_base}{request.url.path}"
    if request.url.query:
        upstream_url += f"?{request.url.query}"

    # Build sanitized headers for upstream (preserve MCP headers, drop hop-by-hop)
    incoming = dict(request.headers)
    hop_by_hop_req = {
        "connection",
        "proxy-connection",
        "keep-alive",
        "transfer-encoding",
        "te",
        "trailer",
        "upgrade",
        "host",
        "content-length",
    }
    headers: dict[str, str] = {}
    for k, v in incoming.items():
        if k.lower() in hop_by_hop_req:
            continue
        headers[k] = v
    # Ensure required MCP headers are present
    if "accept" not in {k.lower() for k in headers.keys()}:
        headers["Accept"] = "application/json, text/event-stream"
    # If we have a JSON body and no content-type, set it
    # (httpx will also set this when using 'content' bytes, but we make it explicit)
    if "content-type" not in {k.lower() for k in headers.keys()}:
        headers["Content-Type"] = "application/json"

    body = await request.body()
    # Pass raw bytes; if empty but method expects JSON, forward as-is
    method = request.method.upper()

    logger.info("LB: %s %s -> %s (bytes=%d)", method, request.url.path, upstream_url, len(body))

    # Use explicit send(stream=True) so we control when the stream is closed
    req = client.build_request(method, upstream_url, headers=headers, content=body)
    upstream = await client.send(req, stream=True, follow_redirects=True)

    headers_out = _filtered_response_headers(upstream)
    media_type = upstream.headers.get("content-type")
    status = upstream.status_code

    async def aiter() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_raw():
                if chunk:
                    yield chunk
        finally:
            await upstream.aclose()

    return StreamingResponse(aiter(), status_code=status, media_type=media_type, headers=headers_out)


@click.command()
@click.option("--listen-port", default=3000, help="Port for the LB to listen on")
@click.option("--backend", multiple=True, default=["http://127.0.0.1:3001", "http://127.0.0.1:3002"], help="Backend base URLs (at least two)")
@click.option("--log-level", default="INFO", help="Logging level")
def main(listen_port: int, backend: list[str], log_level: str) -> int:
    logging.basicConfig(level=getattr(logging, log_level.upper()), format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    rr = RoundRobin(list(backend))

    async def lifespan(app: Starlette):
        async with httpx.AsyncClient(timeout=None) as client:
            app.state.rr = rr
            app.state.client = client
            yield

    app = Starlette(
        routes=[Route("/{path:path}", proxy_handler, methods=["GET", "POST", "DELETE"])],
        lifespan=lifespan,
    )

    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=listen_port)
    return 0


if __name__ == "__main__":
    main()


