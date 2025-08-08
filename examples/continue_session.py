#!/usr/bin/env python3

import asyncio
import json
import sys
from typing import Any, Tuple

import click
import httpx


async def shttp_post(client: httpx.AsyncClient, url: str, payload: dict, *, headers: dict | None = None) -> Tuple[Any | None, int]:
    async with client.stream("POST", url, json=payload, headers=headers) as r:
        r.raise_for_status()
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
        return event_obj, r.status_code


@click.command()
@click.argument("session_id")
@click.option("--base", default="http://127.0.0.1:3000/mcp/", help="Base URL of MCP endpoint (must end with /)")
@click.option("--shttp/--no-shttp", default=True, help="Use Streamable HTTP (SSE on POST). If disabled, expect JSON.")
async def main(session_id: str, base: str, shttp: bool) -> None:
    default_headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": "2025-06-18",
        "Mcp-Session-Id": session_id,
    }
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=default_headers) as client:
        # tools/list
        list_req = {"jsonrpc": "2.0", "id": 100, "method": "tools/list"}
        if shttp:
            ev, _ = await shttp_post(client, base, list_req, headers=default_headers)
            print("tools/list (shttp):", ev)
        else:
            r = await client.post(base, json=list_req)
            r.raise_for_status()
            print("tools/list:", r.json())

        # tools/call
        call = {
            "jsonrpc": "2.0",
            "id": 101,
            "method": "tools/call",
            "params": {
                "name": "start-notification-stream",
                "arguments": {"interval": 0.2, "count": 2, "caller": "continued-client"},
            },
        }
        if shttp:
            ev, _ = await shttp_post(client, base, call, headers=default_headers)
            print("tools/call (shttp):", ev)
        else:
            r2 = await client.post(base, json=call)
            r2.raise_for_status()
            print("tools/call:", r2.json())


if __name__ == "__main__":
    asyncio.run(main(standalone_mode=False))


