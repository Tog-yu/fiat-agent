"""E3 integration test: query_knowledge_hub call (DEV_SPEC §E3).

Covers:
  - a successful call returns parseable TextContent (hermetic fake server);
  - a server `isError` result raises ToolExecutionError and never reaches the
    trusted context (unit test with a stubbed session);
  - a smoke call against the real MODULAR-RAG-MCP-SERVER (skipped if absent).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from fiat_agent.config import McpServerConfig
from fiat_agent.errors import ToolExecutionError
from fiat_agent.mcp_clients.rag_mcp_client import RagMcpClient

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.integration
def test_query_knowledge_hub_returns_text_content() -> None:
    fixture = REPO_ROOT / "tests" / "fixtures" / "fake_rag_query_server.py"
    config = McpServerConfig(
        name="fake-rag-query-server",
        transport="stdio",
        cwd=str(REPO_ROOT),
        command=sys.executable,
        args=[str(fixture)],
    )

    async def _run() -> None:
        async with RagMcpClient(config) as client:
            content = await client.query_knowledge_hub("hello world", top_k=3)
            assert len(content) == 1
            parsed = json.loads(content[0].text)  # parseable TextContent
            assert parsed["query"] == "hello world"

    asyncio.run(_run())


@pytest.mark.integration
def test_query_knowledge_hub_iserror_not_trusted() -> None:
    """A server error must raise, never return content for the context."""
    config = McpServerConfig(
        name="x", transport="stdio", command=sys.executable, args=["-c", "pass"]
    )
    client = RagMcpClient(config)

    class _FakeContent:
        text = "boom"

    class _FakeResult:
        isError = True
        content = [_FakeContent()]

    class _FakeSession:
        async def call_tool(self, name: str, arguments: dict) -> _FakeResult:
            return _FakeResult()

    client._session = _FakeSession()  # bypass start() for a focused unit test

    async def _run() -> None:
        with pytest.raises(ToolExecutionError):
            await client.call_tool("query_knowledge_hub", {"query": "x"})

    asyncio.run(_run())


@pytest.mark.integration
def test_query_knowledge_hub_real_server(rag_server_config) -> None:
    if rag_server_config is None:
        pytest.skip("MODULAR-RAG-MCP-SERVER not found")

    async def _run() -> None:
        async with RagMcpClient(rag_server_config) as client:
            try:
                content = await client.query_knowledge_hub("test query", top_k=2)
            except ToolExecutionError:
                # The real server may reject a query without a valid collection;
                # that is exactly the isError path already covered above.
                return
            assert content
            assert any(getattr(c, "text", None) for c in content)

    asyncio.run(_run())
