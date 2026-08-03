"""Hermetic fake MCP server implementing `query_knowledge_hub` (E3 tests).

Returns a JSON `TextContent` so the client's success path can be exercised
without the real RAG server. Run as a subprocess:

    python tests/fixtures/fake_rag_query_server.py
"""

from __future__ import annotations

import asyncio
import json
import sys

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

app = Server("fake-rag-query-server")

_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "top_k": {"type": "integer"},
        "collection": {"type": "string"},
    },
    "required": ["query"],
}


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="query_knowledge_hub",
            description="search the knowledge base",
            inputSchema=_INPUT_SCHEMA,
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "query_knowledge_hub":
        payload = {
            "answer": "fake answer",
            "query": arguments.get("query"),
            "results": [],
        }
        return [types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]
    return [types.TextContent(type="text", text="unknown tool")]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
