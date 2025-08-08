from __future__ import annotations

import json
import logging
import typing as t

from .admission import TransportAdmissionController
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

    def __init__(
        self,
        interceptor: ProtocolInterceptor,
        admission_controller: t.Optional[TransportAdmissionController] = None,
        *,
        session_lookup: t.Optional[t.Callable[[str], t.Awaitable[t.Optional[t.Dict[str, t.Any]]]]] = None,
    ) -> None:
        self._interceptor = interceptor
        self._admission = admission_controller
        # warmed sessions on this node to avoid duplicate internal warming
        self._warmed: set[str] = set()
        # Optional injector for fetching session objects without importing storage here
        self._session_lookup = session_lookup
        self._logger = logging.getLogger(__name__)

    def wrap(self, inner_app: t.Callable[[Scope, Receive, Send], t.Awaitable[None]]):
        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            if scope.get("type") != "http":
                # Pass through non-HTTP scopes untouched (e.g., lifespan)
                await inner_app(scope, receive, send)
                return

            try:
                self._logger.info(
                    "ASGIWrapper: http request method=%s path=%s",
                    scope.get("method"),
                    scope.get("path"),
                )
            except Exception:
                pass

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
                    payload_text = original_body.decode("utf-8", errors="ignore")
                    self._logger.info("ASGIWrapper: incoming body bytes=%d", len(original_body))
                    forwarded = await self._interceptor.handle_incoming(payload_text, context=context)
                    if "_raw" in forwarded:
                        # Keep raw bytes
                        modified_body_bytes = (
                            forwarded["_raw"].encode("utf-8")
                            if isinstance(forwarded["_raw"], str)
                            else forwarded["_raw"]
                        )
                    else:
                        modified_body_bytes = json.dumps(forwarded).encode("utf-8")
                    # Best-effort extraction for outgoing interception
                    session_id = self._interceptor._extract_session_id(
                        forwarded if isinstance(forwarded, dict) else {}, context
                    )
                    if not session_id and context and "_mcp_db_session_id" in context:
                        session_id = t.cast(str, context.get("_mcp_db_session_id"))
                    self._logger.info("ASGIWrapper: extracted sid from incoming=%s", session_id)
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

            # Create a custom receive that replays the modified body once, then passthrough
            first_receive_done: bool = False

            async def wrapped_receive() -> t.Dict[str, t.Any]:
                nonlocal modified_body_bytes, first_receive_done
                if not first_receive_done:
                    first_receive_done = True
                    body = modified_body_bytes
                    modified_body_bytes = b""
                    self._logger.info(
                        "ASGIWrapper: wrapped_receive -> http.request bytes=%d more=False",
                        len(body),
                    )
                    return {"type": "http.request", "body": body, "more_body": False}
                # After first request body, forward original receive (disconnect, etc.)
                msg = await receive()
                self._logger.debug("ASGIWrapper: passthrough receive type=%s", msg.get("type"))
                return msg

            # Intercept outgoing send calls
            response_headers: list[tuple[bytes, bytes]] | None = None
            content_type: str = ""

            async def wrapped_send(message: t.Dict[str, t.Any]) -> None:
                nonlocal response_headers, content_type, session_id
                if message.get("type") == "http.response.start":
                    response_headers = message.get("headers") or []
                    # Determine content type if present
                    try:
                        header_map = {
                            k.lower(): v
                            for k, v in ((k.decode("latin1"), v.decode("latin1")) for k, v in response_headers)
                        }
                        content_type = header_map.get("content-type", "")
                        # Capture server-provided session id as early as possible
                        sid = header_map.get("mcp-session-id") or header_map.get("x-mcp-session-id")
                        if sid:
                            session_id = sid
                            # Persist on context for downstream consumers
                            if isinstance(context, dict):
                                context["_mcp_db_session_id"] = sid
                        self._logger.info(
                            "ASGIWrapper: response.start content_type=%s sid=%s headers=%s",
                            content_type,
                            session_id,
                            header_map,
                        )
                    except Exception:
                        content_type = ""
                    await send(message)
                    return

                if message.get("type") == "http.response.body":
                    body: bytes = message.get("body", b"")
                    more = bool(message.get("more_body", False))
                    self._logger.info(
                        "ASGIWrapper: response.body bytes=%d more=%s content_type=%s sid=%s",
                        len(body),
                        more,
                        content_type,
                        session_id,
                    )

                    # JSON mode: try to intercept once when body is complete
                    if content_type and "application/json" in content_type and not more:
                        # Capture server-provided session id header on initialize
                        try:
                            if not session_id and response_headers:
                                header_map = {
                                    k.lower(): v
                                    for k, v in ((k.decode("latin1"), v.decode("latin1")) for k, v in response_headers)
                                }
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
                                            self._logger.debug("ASGIWrapper: SSE data line len=%d", len(data))
                                            parsed = json.loads(data)
                                            if session_id:
                                                await self._interceptor.handle_outgoing(
                                                    session_id, parsed, context=context
                                                )
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

            # Admission + warming: if applicable, attempt reconstruction BEFORE forwarding
            # Only for non-initialize, non-initialized requests with a known session id
            async def maybe_admit_and_warm() -> None:
                if self._admission is None:
                    return
                try:
                    # Determine method from buffered body if available
                    method: str | None = None
                    try:
                        payload = json.loads(original_body.decode("utf-8")) if original_body else {}
                        method = payload.get("method")
                    except Exception:
                        method = None

                    # Skip only for initialize; for initialized/notifications we must admit
                    if method == "initialize":
                        return

                    if not session_id:
                        # Try grabbing from headers (GET/SSE)
                        try:
                            session_id_local = self._interceptor._extract_session_id({}, context)
                        except Exception:
                            session_id_local = None
                    else:
                        session_id_local = session_id

                    if not session_id_local:
                        return

                    # If already present in SDK, nothing to do
                    if self._admission.has_session(session_id_local):
                        self._logger.info(
                            "ASGIWrapper: admission skip; session already present sid=%s", session_id_local
                        )
                        return

                    # Consult storage (if provided) to check status and decide warming
                    sess_obj: t.Optional[t.Dict[str, t.Any]] = None
                    if self._session_lookup is not None:
                        try:
                            sess_obj = await self._session_lookup(session_id_local)
                        except Exception:
                            sess_obj = None

                    # Reconstruct transport for INITIALIZED/ACTIVE; if unknown, best-effort reconstruct
                    if sess_obj is not None:
                        status = str(sess_obj.get("status", "")).upper()
                        self._logger.info("ASGIWrapper: admission storage status=%s sid=%s", status, session_id_local)
                        if status in {"INITIALIZED", "ACTIVE"}:
                            await self._admission.ensure_session_transport(session_id_local)
                            # Warm only if ACTIVE and not yet warmed on this node
                            if status == "ACTIVE" and session_id_local not in self._warmed:
                                self._logger.info("ASGIWrapper: warming ACTIVE session sid=%s", session_id_local)
                                await self._send_internal_initialized(inner_app, scope, session_id_local)
                                self._warmed.add(session_id_local)
                        # For INITIALIZING/CLOSED, do nothing here
                    else:
                        # No record in storage: still reconstruct to let SDK admit for initialized/other calls
                        self._logger.info(
                            "ASGIWrapper: admission without storage record; reconstruct sid=%s", session_id_local
                        )
                        await self._admission.ensure_session_transport(session_id_local)
                        # Do not auto-warm without DB truth
                except Exception:
                    # Never block request on admission errors
                    pass

            await maybe_admit_and_warm()

            await inner_app(scope, wrapped_receive, wrapped_send)

        return app

    async def _send_internal_initialized(
        self,
        inner_app: t.Callable[[Scope, Receive, Send], t.Awaitable[None]],
        scope: Scope,
        session_id: str,
    ) -> None:
        """Send a one-shot internal notifications/initialized to warm this node.

        This request is not exposed to the client; we synthesize a POST with the
        correct header and consume the response locally.
        """
        # Clone scope with adjusted headers to include the session id
        headers_list: list[tuple[bytes, bytes]] = []
        try:
            headers_list = list(scope.get("headers", []))
        except Exception:
            headers_list = []
        # Ensure mcp-session-id header present
        headers_lower = {k.decode("latin1").lower(): v for k, v in headers_list}
        if "mcp-session-id" not in headers_lower and "x-mcp-session-id" not in headers_lower:
            headers_list.append((b"mcp-session-id", session_id.encode("latin1")))

        warm_scope = dict(scope)
        warm_scope["headers"] = headers_list

        warm_payload = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        body_bytes = json.dumps(warm_payload).encode("utf-8")

        async def warm_receive() -> t.Dict[str, t.Any]:
            nonlocal body_bytes
            b = body_bytes
            body_bytes = b""
            return {"type": "http.request", "body": b, "more_body": False}

        async def warm_send(_message: t.Dict[str, t.Any]) -> None:  # consume silently
            return

        try:
            await inner_app(warm_scope, warm_receive, warm_send)
            self._logger.debug("ASGIWrapper: internal initialized sent for sid=%s", session_id)
        except Exception:
            # Do not propagate warming errors
            pass
