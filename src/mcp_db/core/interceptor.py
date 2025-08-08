from __future__ import annotations

import json
import typing as t
import uuid

from .models import MCPSession, SessionStatus, MCPEvent, BaseEvent
from .session_manager import SessionManager


JSON = t.Dict[str, t.Any]


class ProtocolInterceptor:
    """Intercepts JSON-RPC messages for MCP over any transport.

    This class is transport-agnostic. It expects to be given callables to
    forward requests to the wrapped server and to send responses back.
    """

    def __init__(self, session_manager: SessionManager) -> None:
        self._sessions = session_manager

    async def handle_incoming(self, raw_message: str, context: t.Optional[dict] = None) -> JSON:
        """Handle an incoming client message.

        Returns a possibly augmented JSON-RPC message to forward to the server.
        """
        try:
            message: JSON = json.loads(raw_message)
        except json.JSONDecodeError:
            # Forward as-is but we can't intercept
            return {"_raw": raw_message}

        method = message.get("method")
        params = message.get("params", {})
        # Only ever use server/transport-provided session IDs. We do not generate them.
        session_id = self._extract_session_id(message, context)

        if session_id is None:
            # No session context, forward as-is
            return message

        if context is not None:
            try:
                context["_mcp_db_last_method"] = method
            except Exception:
                pass

        if method == "initialize":
            # Do not create session here; capture event if we already know a session
            if session_id:
                await self._append_event(session_id, "MessageReceivedEvent", {"method": method, "params": params})
            # Stash initialize request params for later session creation
            if isinstance(context, dict):
                context["_mcp_db_init_params"] = params
        elif method in {"initialized", "notifications/initialized"}:
            if session_id:
                await self._sessions.update(session_id, {"status": SessionStatus.ACTIVE})
                await self._append_event(session_id, "SessionInitializedEvent", {})
        elif method in {"tools/call", "resources/read", "prompts/get"}:
            if session_id:
                await self._append_event(session_id, "MessageReceivedEvent", {"method": method, "params": params})
        else:
            # Default path: still track
            if session_id:
                await self._append_event(session_id, "MessageReceivedEvent", {"method": method, "params": params})

        return message

    async def handle_outgoing(self, session_id: str, response: JSON, context: t.Optional[dict] = None) -> JSON:
        """Handle a server response before sending to client."""
        # If this is the initialize response, register the session using server-provided id
        last_method = context.get("_mcp_db_last_method") if isinstance(context, dict) else None
        # Ensure session exists based on server-provided session id
        existing = await self._sessions.get(session_id) if session_id else None
        if not existing and session_id:
            init_params = context.get("_mcp_db_init_params") if isinstance(context, dict) else None
            session = MCPSession(
                id=session_id,
                status=SessionStatus.INITIALIZING,
                client_id=str((init_params or {}).get("clientInfo", {}).get("name", "unknown")),
                server_id=str(context.get("server_id") if context else "unknown"),
                capabilities=(init_params or {}).get("capabilities", {}),
                metadata={"from": "interceptor", "created_fallback": True},
            )
            await self._sessions.create(session)
            await self._append_event(session_id, "SessionCreatedEvent", {"response": response})
            

        if last_method == "initialize":
            init_params = context.get("_mcp_db_init_params") if isinstance(context, dict) else None
            session = MCPSession(
                id=session_id,
                status=SessionStatus.INITIALIZING,
                client_id=str((init_params or {}).get("clientInfo", {}).get("name", "unknown")),
                server_id=str(context.get("server_id") if context else "unknown"),
                capabilities=(init_params or {}).get("capabilities", {}),
                metadata={"from": "interceptor"},
            )
            await self._sessions.create(session)
            await self._append_event(session_id, "SessionCreatedEvent", {"response": response})
            

        await self._append_event(session_id, "MessageSentEvent", {"response": response})
        if response.get("method") == "server/disconnect":
            await self._sessions.update(session_id, {"status": SessionStatus.CLOSED})
            await self._append_event(session_id, "SessionClosedEvent", {})
        return response

    def _extract_session_id(self, message: JSON, context: t.Optional[dict]) -> t.Optional[str]:
        # Try params, headers (in context), or previously established mapping
        params = message.get("params") or {}
        sid = params.get("session_id")
        if sid:
            return str(sid)
        if context and "headers" in context:
            headers = {k.lower(): v for k, v in context["headers"].items()}
            if "mcp-session-id" in headers:
                return headers["mcp-session-id"]
            if "x-mcp-session-id" in headers:
                return headers["x-mcp-session-id"]
            if "last-event-id" in headers:  # SSE
                return headers["last-event-id"]
        return None

    def _generate_session_id(self) -> str:
        return uuid.uuid4().hex

    async def _append_event(self, session_id: str, event_type: str, payload: JSON) -> None:
        event = BaseEvent(event_id=uuid.uuid4().hex, session_id=session_id, event_type=event_type, payload=payload)
        await self._sessions.append_event(event)


