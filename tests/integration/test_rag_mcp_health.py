"""E6 integration test: MCP RAG health check & graceful degradation (DEV_SPEC §E6).

Covers:
  - GET /api/rag/mcp/status returns a status dict;
  - a server that fails to start yields no tools and status "unavailable"
    (RAG tools are disabled, not crashing the caller);
  - the real MODULAR-RAG-MCP-SERVER reports "ok" with its tools (skipped if absent).
"""

from __future__ import annotations

import asyncio
import sys

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from fiat_agent.config import McpServerConfig
from fiat_agent.mcp_clients.tool_registry import load_rag_tools


@pytest.mark.integration
def test_rag_mcp_status_endpoint_returns_status() -> None:
    client = TestClient(app)
    r = client.get("/api/rag/mcp/status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in {"ok", "unavailable", "disabled"}


@pytest.mark.integration
def test_load_rag_tools_disabled_on_startup_failure() -> None:
    bad = McpServerConfig(
        name="bad", transport="stdio", command="/nonexistent/mcp-server-xyz", args=[]
    )

    async def _run() -> None:
        tools, status = await load_rag_tools(bad)
        assert tools == []
        assert status.status == "unavailable"
        assert status.error  # failure reason is surfaced, not swallowed

    asyncio.run(_run())


@pytest.mark.integration
def test_load_rag_tools_ok_with_real_server(rag_server_config) -> None:
    if rag_server_config is None:
        pytest.skip("MODULAR-RAG-MCP-SERVER not found")

    async def _run() -> None:
        tools, status = await load_rag_tools(rag_server_config)
        assert status.status == "ok"
        assert len(tools) >= 3

    asyncio.run(_run())
