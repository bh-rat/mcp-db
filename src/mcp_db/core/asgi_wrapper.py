from __future__ import annotations

import asyncio
import json
import typing as t

from .interceptor import ProtocolInterceptor


Scope = t.Dict[str, t.Any]
Receive = t.Callable[[], t.Awaitable[t.Dict[str, t.Any]]]
Send = t.Callable[[t.Dict[str, t.Any]], t.Awaitable[None]]


class ASGITransportWrapper:
    """ASGI transport-level wrapper for MCP Streamable HTTP servers.

    This wrapper intercepts incoming HTTP request bodies that carry JSON-RPC
    messages and outgoing responses (JSON or SSE) in order to persist session
    and event data via a `ProtocolInterceptor`. It does not require any changes
    to the wrapped server implementation.

    Usage:
        wrapper = ASGITransportWrapper(interceptor)
        # inner_app must be an ASGI app: (scope, receive, send) -> Awaitable
        asgi_app = wrapper.wrap(inner_app)
    """

    def __init__(self, interceptor: ProtocolInterceptor) -> None:
        self._interceptor = interceptor

    def wrap(self, inner_app: t.Callable[[Scope, Receive, Send], t.Awaitable[None]]):
        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            if scope.get("type") != "http":
                # Pass through non-HTTP scopes untouched (e.g., lifespan)
                await inner_app(scope, receive, send)
                return

            # Build headers dict for context
            headers_dict: dict[str, str] = {}
            try:
                for key_bytes, val_bytes in scope.get("headers", []) or []:
                    headers_dict[key_bytes.decode("latin1").lower()] = val_bytes.decode("latin1")
            except Exception:
                headers_dict = {}

            context = {"headers": headers_dict, "server_id": scope.get("server", ("", ""))[0] or "unknown"}

            # Buffer the full request body (Streamable HTTP uses normal POST for JSON-RPC)
            body_chunks: list[bytes] = []
            more_body = True
            while more_body:
                message = await receive()
                if message.get("type") == "http.request":
                    body_chunks.append(message.get("body", b""))
                    more_body = bool(message.get("more_body", False))
                    if not more_body:
                        break
                else:
                    # Non-body message; unlikely for HTTP requests, but pass through
                    body_chunks.append(b"")
                    more_body = False
                    break
            original_body = b"".join(body_chunks)

            # Intercept incoming JSON-RPC message if any
            modified_body_bytes = original_body
            session_id: str | None = None
            if original_body:
                try:
                    forwarded = await self._interceptor.handle_incoming(original_body.decode("utf-8"), context=context)
                    if "_raw" in forwarded:
                        # Keep raw bytes
                        modified_body_bytes = forwarded["_raw"].encode("utf-8") if isinstance(forwarded["_raw"], str) else forwarded["_raw"]
                    else:
                        modified_body_bytes = json.dumps(forwarded).encode("utf-8")
                    # Best-effort extraction for outgoing interception
                    session_id = self._interceptor._extract_session_id(forwarded if isinstance(forwarded, dict) else {}, context)
                    if not session_id and context and "_mcp_db_session_id" in context:
                        session_id = t.cast(str, context.get("_mcp_db_session_id"))
                except Exception:
                    # On parse/interceptor error, fall back to original body
                    modified_body_bytes = original_body
                    session_id = None

            # For GET/SSE or empty-body POSTs, derive session from headers if available
            if session_id is None:
                try:
                    session_id = self._interceptor._extract_session_id({}, context)
                except Exception:
                    session_id = None

            # Create a custom receive that replays the modified body once
            async def wrapped_receive() -> t.Dict[str, t.Any]:
                nonlocal modified_body_bytes
                body = modified_body_bytes
                modified_body_bytes = b""
                return {"type": "http.request", "body": body, "more_body": False}

            # Intercept outgoing send calls
            response_headers: list[tuple[bytes, bytes]] | None = None
            content_type: str = ""

            async def wrapped_send(message: t.Dict[str, t.Any]) -> None:
                nonlocal response_headers, content_type, session_id
                if message.get("type") == "http.response.start":
                    response_headers = message.get("headers") or []
                    # Determine content type if present
                    try:
                        header_map = {k.lower(): v for k, v in ((k.decode("latin1"), v.decode("latin1")) for k, v in response_headers)}
                        content_type = header_map.get("content-type", "")
                        # Capture server-provided session id as early as possible
                        sid = header_map.get("mcp-session-id") or header_map.get("x-mcp-session-id")
                        if sid:
                            session_id = sid
                            # Persist on context for downstream consumers
                            if isinstance(context, dict):
                                context["_mcp_db_session_id"] = sid
                    except Exception:
                        content_type = ""
                    await send(message)
                    return

                if message.get("type") == "http.response.body":
                    body: bytes = message.get("body", b"")
                    more = bool(message.get("more_body", False))

                    # JSON mode: try to intercept once when body is complete
                    if content_type and "application/json" in content_type and not more:
                        # Capture server-provided session id header on initialize
                        try:
                            if not session_id and response_headers:
                                header_map = {k.lower(): v for k, v in ((k.decode("latin1"), v.decode("latin1")) for k, v in response_headers)}
                                sid = header_map.get("mcp-session-id") or header_map.get("x-mcp-session-id")
                                if sid:
                                    session_id = sid
                        except Exception:
                            # ignore header parsing errors
                            pass
                        try:
                            resp_json = json.loads(body.decode("utf-8")) if body else {}
                            if session_id:
                                _ = await self._interceptor.handle_outgoing(session_id, resp_json, context=context)
                            # We do not rewrite the body to avoid altering server semantics
                        except Exception:
                            pass

                    # SSE mode: best-effort parse of data: lines when chunks complete
                    if content_type and "text/event-stream" in content_type:
                        # Naive parse; do not modify payload, only observe
                        try:
                            text = body.decode("utf-8", errors="ignore")
                            for line in text.splitlines():
                                if line.startswith("data:"):
                                    data = line[5:].strip()
                                    if data:
                                        try:
                                            parsed = json.loads(data)
                                            if session_id:
                                                await self._interceptor.handle_outgoing(session_id, parsed, context=context)
                                        except Exception:
                                            # Ignore non-JSON data lines
                                            pass
                        except Exception:
                            pass

                    await send(message)
                    return

                # Default pass-through
                try:
                    await send(message)
                except Exception:
                    # Ensure wrapper never raises to ASGI stack from here
                    raise

            await inner_app(scope, wrapped_receive, wrapped_send)

        return app


