#!/usr/bin/env python3

import asyncio
import json
from typing import Any

import httpx


async def main() -> None:
    base = "http://127.0.0.1:3000/mcp/"

    default_headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": "2025-06-18",
    }

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers=default_headers) as client:
        # Initialize (Streamable HTTP)
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
        r = await client.post(base, json=init)
        r.raise_for_status()
        print("initialize:", r.json())
        sid = r.headers.get("Mcp-Session-Id") or r.headers.get("mcp-session-id")
        headers = {"Mcp-Session-Id": sid} if sid else {}

        # Send Initialized notification
        initialized = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        r_initd = await client.post(base, json=initialized, headers={**default_headers, **headers})
        if r_initd.status_code not in (200, 202):
            print("initialized status:", r_initd.status_code, r_initd.text)

        # tools/list
        list_req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
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
        r3 = await client.post(base, json=call, headers={**default_headers, **headers})
        print("tools/call:", r3.json())


if __name__ == "__main__":
    asyncio.run(main())


