"""RAG MCP proxy service (DEV_SPEC §I2).

Thin async proxy in front of the modular RAG MCP server. Each call spins up a
short-lived MCP stdio connection, invokes the relevant tool, and returns a
structured, JSON-friendly payload. Backend failures degrade gracefully: the
service never raises a 500 — it returns a ``status`` field
(``"ok"`` | ``"disabled"`` | ``"unavailable"``) plus an ``error`` string, mirroring
the existing ``GET /api/rag/mcp/status`` contract.

The service is dependency-injectable via :func:`get_rag_service` so integration
tests can swap in a hermetic fake without spawning the real RAG subprocess.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from fiat_agent.config import Settings, load_settings
from fiat_agent.mcp_clients.content_parser import parse_mcp_contents
from fiat_agent.mcp_clients.rag_mcp_client import (
    McpClientNotStartedError,
    RagMcpClient,
)


def _structured(text: str) -> Any:
    """Best-effort JSON parse of a tool text payload; fall back to raw string."""
    text = text.strip()
    if not text:
        return {"text": ""}
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return {"text": text}
    return data


class RagService:
    """Proxy to the RAG MCP server (query / collections / document summary)."""

    def __init__(
        self,
        *,
        config_name: str = "rag",
        settings: Optional[Settings] = None,
    ) -> None:
        self._config_name = config_name
        self._settings = settings

    def _new_client(self) -> RagMcpClient:
        return RagMcpClient.from_settings(self._settings, self._config_name)

    async def query(
        self, query: str, *, top_k: int = 5, collection: Optional[str] = None
    ) -> dict:
        """Proxy ``query_knowledge_hub`` and return parsed results.

        Returns a dict with ``status``, ``results`` (structured JSON when the
        server emits JSON, else ``{"text": ...}``), ``images`` and ``raw_metadata``.
        """
        try:
            async with self._new_client() as client:
                contents = await client.query_knowledge_hub(
                    query, top_k=top_k, collection=collection
                )
                parsed = parse_mcp_contents(contents)
                return {
                    "status": "ok",
                    "query": query,
                    "collection": collection,
                    "top_k": top_k,
                    "results": [_structured(t) for t in parsed.texts],
                    "images": [img.model_dump() for img in parsed.images],
                    "raw_metadata": parsed.metadata,
                }
        except McpClientNotStartedError as e:
            return {"status": "disabled", "error": str(e)}
        except Exception as e:  # noqa: BLE001 - graceful degradation
            return {"status": "unavailable", "error": str(e)}

    async def list_collections(self, *, include_stats: bool = True) -> dict:
        """Proxy ``list_collections`` and return parsed collection metadata."""
        try:
            async with self._new_client() as client:
                contents = await client.list_collections(include_stats=include_stats)
                parsed = parse_mcp_contents(contents)
                return {
                    "status": "ok",
                    "include_stats": include_stats,
                    "collections": [_structured(t) for t in parsed.texts],
                    "raw_metadata": parsed.metadata,
                }
        except McpClientNotStartedError as e:
            return {"status": "disabled", "error": str(e)}
        except Exception as e:  # noqa: BLE001 - graceful degradation
            return {"status": "unavailable", "error": str(e)}

    async def get_document_summary(
        self, doc_id: str, *, collection: Optional[str] = None
    ) -> dict:
        """Proxy ``get_document_summary`` and return parsed document info."""
        try:
            async with self._new_client() as client:
                contents = await client.get_document_summary(
                    doc_id, collection=collection
                )
                parsed = parse_mcp_contents(contents)
                return {
                    "status": "ok",
                    "document_id": doc_id,
                    "collection": collection,
                    "summary": [_structured(t) for t in parsed.texts],
                    "images": [img.model_dump() for img in parsed.images],
                    "raw_metadata": parsed.metadata,
                }
        except McpClientNotStartedError as e:
            return {"status": "disabled", "error": str(e)}
        except Exception as e:  # noqa: BLE001 - graceful degradation
            return {"status": "unavailable", "error": str(e)}


_service: RagService | None = None


async def get_rag_service() -> RagService:
    """FastAPI dependency returning a lazily-built, process-wide RAG service.

    Tests override this via ``app.dependency_overrides[get_rag_service]`` with a
    hermetic instance.
    """
    global _service
    if _service is None:
        settings = load_settings()
        # Only build a live service if the rag server is actually configured;
        # otherwise an empty config still yields a service that reports
        # status="disabled" rather than crashing the app at import time.
        _service = RagService(settings=settings)
    return _service
