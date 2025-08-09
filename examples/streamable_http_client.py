#!/usr/bin/env python3

import asyncio
import json
from typing import Any, Tuple

import click
import httpx


async def shttp_post(
    client: httpx.AsyncClient, url: str, payload: dict, *, headers: dict | None = None
) -> Tuple[str | None, Any | None]:
    async with client.stream("POST", url, json=payload, headers=headers) as r:
        r.raise_for_status()
        sid = r.headers.get("Mcp-Session-Id") or r.headers.get("mcp-session-id")
        event_obj = None
        async for line in r.aiter_lines():
            if not line:
                continue
            if line.startswith("data:"):
                data = line[5:].strip()
                if not data:
                    continue
                try:
                    event_obj = json.loads(data)
                except Exception:
                    continue
                break
        return sid, event_obj


@click.command()
@click.option("--base", default="http://127.0.0.1:3000/mcp/", help="Base URL of MCP endpoint (must end with /)")
@click.option("--shttp/--no-shttp", default=True, help="Use Streamable HTTP (SSE on POST). If disabled, expect JSON.")
async def main(base: str, shttp: bool) -> None:
    default_headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": "2025-06-18",
    }

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=default_headers) as client:
        # Initialize
        init = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "example-client", "version": "0.1.0"},
            },
        }
        if shttp:
            sid, ev = await shttp_post(client, base, init)
            print("initialize (shttp):", ev)
        else:
            r = await client.post(base, json=init)
            r.raise_for_status()
            print("initialize:", r.json())
            sid = r.headers.get("Mcp-Session-Id") or r.headers.get("mcp-session-id")
        print("session id:", sid)
        headers = {"Mcp-Session-Id": sid} if sid else {}

        # Send Initialized notification
        initialized = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        if shttp:
            _, ev = await shttp_post(client, base, initialized, headers=headers)
            if ev is not None:
                print("initialized (shttp):", ev)
        else:
            r_initd = await client.post(base, json=initialized, headers={**default_headers, **headers})
            if r_initd.status_code not in (200, 202):
                print("initialized status:", r_initd.status_code, r_initd.text)

        # tools/list
        list_req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        if shttp:
            _, ev = await shttp_post(client, base, list_req, headers=headers)
            print("tools/list (shttp):", ev)
        else:
            r2 = await client.post(base, json=list_req, headers={**default_headers, **headers})
            print("tools/list:", r2.json())

        # tools/call
        call = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "start-notification-stream",
                "arguments": {
                    "interval": 0.25,
                    "count": 4,
                    "caller": "client",
                },
            },
        }
        if shttp:
            _, ev = await shttp_post(client, base, call, headers=headers)
            print("tools/call (shttp):", ev)
        else:
            r3 = await client.post(base, json=call, headers={**default_headers, **headers})
            print("tools/call:", r3.json())


if __name__ == "__main__":
    # click supports asyncio entrypoints via 'python -m' invocation in uv
    asyncio.run(main(standalone_mode=False))
