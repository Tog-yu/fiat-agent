"""MCP tool registry (phase E2, DEV_SPEC §6.5).

Discovers the tools exposed by the RAG MCP server via `tools/list` and converts
each MCP `Tool` into the canonical internal `ToolDefinition`
(`fiat_agent/tools/schemas.py`). Risk/approval stay at safe defaults (L1, no
approval) because RAG query tools are read-only; the Tool Gateway (F3) layers
policy on top.
"""

from __future__ import annotations

from typing import Any

from fiat_agent.mcp_clients.rag_mcp_client import RagMcpClient
from fiat_agent.tools.schemas import ToolDefinition


def _to_tool_definition(tool: Any) -> ToolDefinition:
    """Convert one MCP `Tool` into the internal `ToolDefinition`."""
    schema = tool.inputSchema
    return ToolDefinition(
        name=tool.name,
        description=tool.description or "",
        input_schema=dict(schema) if schema else {},
    )


async def sync_mcp_tools(client: RagMcpClient) -> list[ToolDefinition]:
    """Fetch `tools/list` from the connected MCP server and convert them."""
    result = await client.session.list_tools()
    return [_to_tool_definition(t) for t in result.tools]


class McpToolRegistry:
    """Caches the converted tool definitions for a single MCP server session."""

    def __init__(self) -> None:
        self._tools: list[ToolDefinition] = []

    async def sync(self, client: RagMcpClient) -> list[ToolDefinition]:
        """Discover tools from `client` and store them."""
        self._tools = await sync_mcp_tools(client)
        return self._tools

    @property
    def tools(self) -> list[ToolDefinition]:
        return list(self._tools)

    def by_name(self, name: str) -> ToolDefinition | None:
        return next((t for t in self._tools if t.name == name), None)
