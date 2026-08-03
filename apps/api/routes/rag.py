"""RAG MCP status API (phase E6, DEV_SPEC §E6).

Exposes GET /api/rag/mcp/status so operators can see whether the RAG MCP server
is reachable. On startup failure the RAG tools are reported as disabled
(graceful degradation).
"""

from __future__ import annotations

from fastapi import APIRouter

from fiat_agent.config import load_settings
from fiat_agent.mcp_clients.rag_mcp_client import RagMcpHealthStatus
from fiat_agent.mcp_clients.tool_registry import load_rag_tools

router = APIRouter(prefix="/api/rag", tags=["rag"])


@router.get("/mcp/status")
async def rag_mcp_status() -> dict:
    cfg = load_settings().mcp_servers.get("rag")
    if cfg is None or not cfg.name:
        return RagMcpHealthStatus(status="disabled", server="").model_dump()
    _tools, status = await load_rag_tools(cfg)
    return status.model_dump()
