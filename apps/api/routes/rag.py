"""RAG MCP proxy API (DEV_SPEC §I2, plus the E6 status endpoint).

Endpoints:
  - GET  /api/rag/mcp/status            (phase E6 health check)
  - POST /api/rag/query                 (proxy query_knowledge_hub)
  - GET  /api/rag/collections           (proxy list_collections)
  - GET  /api/rag/documents/{doc_id}/summary  (proxy get_document_summary)

All RAG-backed endpoints degrade gracefully: when the MCP server is unreachable
or unconfigured they return HTTP 200 with a ``status`` field of ``"disabled"`` or
``"unavailable"`` (never a 500), mirroring the existing status endpoint.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from fiat_agent.config import load_settings
from fiat_agent.mcp_clients.rag_mcp_client import RagMcpHealthStatus
from fiat_agent.mcp_clients.tool_registry import load_rag_tools

from apps.api.rag_service import RagService, get_rag_service

router = APIRouter(prefix="/api/rag", tags=["rag"])


class RagQueryRequest(BaseModel):
    query: str
    top_k: int = 5
    collection: Optional[str] = None


@router.get("/mcp/status")
async def rag_mcp_status() -> dict:
    cfg = load_settings().mcp_servers.get("rag")
    if cfg is None or not cfg.name:
        return RagMcpHealthStatus(status="disabled", server="").model_dump()
    _tools, status = await load_rag_tools(cfg)
    return status.model_dump()


@router.post("/query")
async def rag_query(
    body: RagQueryRequest,
    service: RagService = Depends(get_rag_service),
) -> dict:
    if not body.query or not body.query.strip():
        raise HTTPException(status_code=422, detail="query 不能为空")
    return await service.query(
        body.query, top_k=body.top_k, collection=body.collection
    )


@router.get("/collections")
async def rag_collections(
    include_stats: bool = True,
    service: RagService = Depends(get_rag_service),
) -> dict:
    return await service.list_collections(include_stats=include_stats)


@router.get("/documents/{doc_id}/summary")
async def rag_document_summary(
    doc_id: str,
    collection: Optional[str] = None,
    service: RagService = Depends(get_rag_service),
) -> Any:
    return await service.get_document_summary(doc_id, collection=collection)
