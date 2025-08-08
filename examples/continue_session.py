#!/usr/bin/env python3

import asyncio
import sys
from typing import Optional

import httpx


async def main(session_id: str, *, base: str = "http://127.0.0.1:3000/mcp/") -> None:
    default_headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": "2025-06-18",
        "Mcp-Session-Id": session_id,
    }
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers=default_headers) as client:
        # tools/list should work directly if the node reconstructs transport
        list_req = {"jsonrpc": "2.0", "id": 100, "method": "tools/list"}
        r = await client.post(base, json=list_req)
        r.raise_for_status()
        print("tools/list:", r.json())

        call = {
            "jsonrpc": "2.0",
            "id": 101,
            "method": "tools/call",
            "params": {
                "name": "start-notification-stream",
                "arguments": {"interval": 0.2, "count": 2, "caller": "continued-client"},
            },
        }
        r2 = await client.post(base, json=call)
        r2.raise_for_status()
        print("tools/call:", r2.json())


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m examples.continue_session <SESSION_ID>")
        raise SystemExit(2)
    asyncio.run(main(sys.argv[1]))


