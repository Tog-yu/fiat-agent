"""Hermetic fake MCP stdio server for E1 integration tests.

Implements a minimal but valid MCP server using the `mcp` SDK so the handshake
matches the real protocol. It intentionally writes a line to **stderr** to prove
the client treats stderr as logs and only parses JSON-RPC from stdout
(DEV_SPEC E1 criterion 2).

Run as a subprocess:
    python tests/fixtures/fake_rag_mcp_server.py
"""

from __future__ import annotations

import asyncio
import sys

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

app = Server("fake-rag-mcp-server")


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="noop",
            description="a no-op tool for testing",
            inputSchema={"type": "object", "properties": {}},
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    return [types.TextContent(type="text", text="ok")]


async def main() -> None:
    # This stderr line must NOT be interpreted as a JSON-RPC message by the
    # client; it is a server-side log.
    print("fake-rag-mcp-server: startup log on stderr", file=sys.stderr, flush=True)
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
