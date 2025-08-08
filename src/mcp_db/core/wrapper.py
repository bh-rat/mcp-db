from __future__ import annotations

import typing as t

from .interceptor import ProtocolInterceptor

JSON = t.Dict[str, t.Any]


class MCPStorageWrapper:
    """Wraps an MCP server-like object by intercepting messages at the transport boundary.

    The wrapped server is expected to expose an async callable `handle_message(message: dict) -> dict`.
    This class stays transport-agnostic and does not import any server frameworks.
    """

    def __init__(
        self,
        server: t.Any,
        interceptor: ProtocolInterceptor,
    ) -> None:
        if not hasattr(server, "handle_message"):
            raise TypeError("wrapped server must have an async handle_message(message: dict) -> dict")
        self._server = server
        self._interceptor = interceptor

    async def handle_raw(self, raw_message: str, context: t.Optional[dict] = None) -> JSON:
        forwarded = await self._interceptor.handle_incoming(raw_message, context=context)
        # If parsing failed, `_raw` will be present; pass through to server handler if possible
        if "_raw" in forwarded:
            response = await self._server.handle_message(forwarded["_raw"])  # type: ignore[arg-type]
            return response
        response = await self._server.handle_message(forwarded)
        session_id = self._interceptor._extract_session_id(forwarded, context)  # internal use
        if session_id:
            response = await self._interceptor.handle_outgoing(session_id, response)
        return response
