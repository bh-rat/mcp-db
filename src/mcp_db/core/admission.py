from __future__ import annotations

import typing as t


class TransportAdmissionController:
    """Abstract admission controller for (re)hydrating transports in the SDK.

    Implementations provide a way for the wrapper to check whether a session's
    transport is already registered in the underlying SDK and, if not, to
    reconstruct it in a way that is compatible with the SDK's internal manager.
    """

    def has_session(self, session_id: str) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    async def ensure_session_transport(self, session_id: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class StreamableHTTPAdmissionController(TransportAdmissionController):
    """Admission controller for MCP Streamable HTTP SDK.

    This controller mirrors the SDK's behavior to attach/register a transport
    for a given session id into the live `StreamableHTTPSessionManager` so that
    the manager will accept subsequent requests for that session on this node.
    """

    def __init__(self, manager: t.Any, app: t.Any) -> None:
        # We do not depend on concrete SDK types to keep this package decoupled.
        self._manager = manager
        self._app = app

        # Resolve transport class dynamically to survive SDK refactors
        self._transport_cls = self._resolve_transport_class()

    def _resolve_transport_class(self) -> t.Any:
        candidates = [
            "mcp.server.streamable_http_transport.StreamableHTTPServerTransport",
            "mcp.server.streamable_http_manager.StreamableHTTPServerTransport",
            "mcp.server.streamable_http.StreamableHTTPServerTransport",
        ]
        for path in candidates:
            try:
                module_name, cls_name = path.rsplit(".", 1)
                module = __import__(module_name, fromlist=[cls_name])
                return getattr(module, cls_name)
            except Exception:
                continue
        raise ImportError(
            "Could not locate StreamableHTTPServerTransport in MCP SDK. "
            "Checked: " + ", ".join(candidates)
        )

    def has_session(self, session_id: str) -> bool:
        # SDK manager is expected to have an internal mapping of active transports
        instances = getattr(self._manager, "_server_instances", None)
        try:
            return bool(instances is not None and session_id in instances)
        except Exception:
            return False

    async def ensure_session_transport(self, session_id: str) -> None:
        # If already present, nothing to do
        if self.has_session(session_id):
            return

        # Construct a transport compatible with the manager
        json_response = getattr(self._manager, "json_response", False)
        event_store = getattr(self._manager, "event_store", None)
        security_settings = getattr(self._manager, "security_settings", None)

        try:
            transport = self._transport_cls(
                mcp_session_id=session_id,
                is_json_response_enabled=json_response,
                event_store=event_store,
                security_settings=security_settings,
            )
        except TypeError:
            # Older/newer SDKs may use different parameter names
            try:
                transport = self._transport_cls(
                    mcp_session_id=session_id,
                    json_response=json_response,
                    event_store=event_store,
                    security_settings=security_settings,
                )
            except Exception:
                # As a last resort, try minimal ctor
                transport = self._transport_cls(mcp_session_id=session_id)

        # Register into manager's map
        instances = getattr(self._manager, "_server_instances", None)
        if instances is not None:
            instances[session_id] = transport

        # Start the app runner for this transport if a task group is available.
        # This mirrors the SDK's flow for new sessions but with an existing sid.
        task_group = getattr(self._manager, "_task_group", None)
        if task_group is None:
            # No task group available; best-effort registration is done.
            return

        async def _run(*, task_status=None) -> None:
            try:
                async with transport.connect() as (read, write):
                    # Signal that streams are ready so the manager can route requests
                    if task_status is not None:
                        try:
                            import anyio

                            if task_status is anyio.TASK_STATUS_IGNORED:
                                pass
                            else:
                                task_status.started()
                        except Exception:
                            pass
                    init_options = self._app.create_initialization_options()
                    await self._app.run(read, write, init_options, stateless=False)
            except Exception:
                # Swallow exceptions to avoid crashing the node; manager will handle errors.
                pass

        try:
            # Prefer start() to wait until transport.connect() is established
            await task_group.start(_run)
        except Exception:
            # If the manager's task group API differs, run fire-and-forget
            try:
                import anyio
                async with anyio.create_task_group() as tg:
                    await tg.start(_run)
            except Exception:
                # Last fallback: run inline (potentially blocking)
                await _run()


