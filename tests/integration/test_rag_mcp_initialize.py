"""E1 integration test: MCP stdio client lifecycle (DEV_SPEC §E1, §2.4, §7.2).

Covers:
  - starting the real MODULAR-RAG-MCP-SERVER (config-driven), initialize + close,
    and that it exposes the three expected tools;
  - starting a hermetic fake MCP server to prove stdout carries JSON-RPC while
    stderr is treated as logs (criterion 2);
  - `from_settings` reads the `rag` server config;
  - `initialize()` must follow `start()`.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from fiat_agent.config import McpServerConfig, load_settings
from fiat_agent.mcp_clients.rag_mcp_client import (
    McpClientNotStartedError,
    RagMcpClient,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _rag_server_config() -> McpServerConfig | None:
    """Resolve a runnable config for the real RAG server.

    The shipped settings use ``command: python``, but the RAG server's deps live
    in its own ``.venv``. Prefer that interpreter so the test can actually start
    the server in this local dev environment. Returns ``None`` (so the caller can
    skip) when the server directory or its venv interpreter is absent.
    """
    base = load_settings().mcp_servers.get("rag")
    if base is None or not base.cwd:
        return None
    cwd = Path(base.cwd)
    if not cwd.exists():
        return None
    venv_python = cwd / ".venv" / "bin" / "python"
    command = str(venv_python) if venv_python.exists() else (base.command or "python")
    return McpServerConfig(
        name=base.name,
        transport=base.transport,
        cwd=str(cwd),
        command=command,
        args=list(base.args),
    )


@pytest.mark.integration
def test_starts_real_rag_server_and_exposes_tools() -> None:
    config = _rag_server_config()
    if config is None:
        pytest.skip("MODULAR-RAG-MCP-SERVER not found; skipping real-server test")

    async def _run() -> None:
        async with RagMcpClient(config) as client:
            assert client.server_info.name == "modular-rag-mcp-server"
            tools = await client.session.list_tools()
            names = {t.name for t in tools.tools}
            assert {
                "query_knowledge_hub",
                "list_collections",
                "get_document_summary",
            } <= names

    asyncio.run(_run())


@pytest.mark.integration
def test_stdio_transport_isolates_stderr() -> None:
    """A fake MCP server that logs to stderr must not break JSON-RPC parsing."""
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
            assert client.server_info.name == "fake-rag-mcp-server"
            tools = await client.session.list_tools()
            assert {t.name for t in tools.tools} == {"noop"}

    asyncio.run(_run())


@pytest.mark.integration
def test_from_settings_reads_rag_config() -> None:
    settings = load_settings()
    client = RagMcpClient.from_settings(settings)
    assert client.config.name == "modular-rag-mcp-server"
    assert "MODULAR-RAG-MCP-SERVER" in (client.config.cwd or "")


@pytest.mark.integration
def test_initialize_requires_start() -> None:
    config = McpServerConfig(
        name="x", transport="stdio", command=sys.executable, args=["-c", "pass"]
    )
    client = RagMcpClient(config)

    async def _run() -> None:
        with pytest.raises(McpClientNotStartedError):
            await client.initialize()

    asyncio.run(_run())
