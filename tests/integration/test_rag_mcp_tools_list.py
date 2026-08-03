"""E2 integration test: MCP tools/list sync (DEV_SPEC §E2, §6.5).

Covers:
  - discovering the three RAG tools from the real MODULAR-RAG-MCP-SERVER and
    converting them into internal `ToolDefinition`s;
  - the `McpToolRegistry` caches and indexes tools by name;
  - a hermetic fake MCP server proves the conversion works without the external
    server (and that input_schema survives the round-trip).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from fiat_agent.config import McpServerConfig
from fiat_agent.mcp_clients.rag_mcp_client import RagMcpClient
from fiat_agent.mcp_clients.tool_registry import (
    McpToolRegistry,
    sync_mcp_tools,
)
from fiat_agent.schemas.common import RiskLevel
from fiat_agent.tools.schemas import ToolDefinition

REPO_ROOT = Path(__file__).resolve().parents[2]

EXPECTED_RAG_TOOLS = {
    "query_knowledge_hub",
    "list_collections",
    "get_document_summary",
}


@pytest.mark.integration
def test_sync_discovers_rag_tools(rag_server_config) -> None:
    if rag_server_config is None:
        pytest.skip("MODULAR-RAG-MCP-SERVER not found; skipping real-server test")

    async def _run() -> None:
        async with RagMcpClient(rag_server_config) as client:
            tools = await sync_mcp_tools(client)
            names = {t.name for t in tools}
            assert EXPECTED_RAG_TOOLS <= names
            for tool in tools:
                assert isinstance(tool, ToolDefinition)
                assert tool.risk_level == RiskLevel.L1
                assert tool.approval_required is False
                assert isinstance(tool.input_schema, dict)

    asyncio.run(_run())


@pytest.mark.integration
def test_registry_caches_and_indexes(rag_server_config) -> None:
    if rag_server_config is None:
        pytest.skip("MODULAR-RAG-MCP-SERVER not found; skipping real-server test")

    async def _run() -> None:
        async with RagMcpClient(rag_server_config) as client:
            registry = McpToolRegistry()
            tools = await registry.sync(client)
            assert len(tools) >= len(EXPECTED_RAG_TOOLS)
            assert {t.name for t in registry.tools} == {t.name for t in tools}
            assert registry.by_name("query_knowledge_hub") is not None
            assert registry.by_name("does_not_exist") is None

    asyncio.run(_run())


@pytest.mark.integration
def test_sync_converts_fake_server_tools() -> None:
    """Hermetic: a fake MCP server's tool is converted to a ToolDefinition."""
    fixture = REPO_ROOT / "tests" / "fixtures" / "fake_rag_mcp_server.py"
    config = McpServerConfig(
        name="fake-rag-mcp-server",
        transport="stdio",
        cwd=str(REPO_ROOT),
        command=sys.executable,
        args=[str(fixture)],
    )

    async def _run() -> None:
        async with RagMcpClient(config) as client:
            tools = await sync_mcp_tools(client)
            assert len(tools) == 1
            td = tools[0]
            assert isinstance(td, ToolDefinition)
            assert td.name == "noop"
            assert td.input_schema == {"type": "object", "properties": {}}

    asyncio.run(_run())
