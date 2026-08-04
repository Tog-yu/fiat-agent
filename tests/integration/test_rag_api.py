"""I2 integration test: RAG MCP proxy API (DEV_SPEC §I2).

Exercises the three RAG proxy endpoints against a hermetic :class:`RagService`
(no real MCP server / subprocess). Also asserts graceful degradation when the
backend reports ``disabled`` / ``unavailable``.

Run with: ``pytest -q tests/integration/test_rag_api.py``
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.rag_service import RagService, get_rag_service


class _FakeRagService(RagService):
    """Deterministic stand-in returning canned payloads (no subprocess)."""

    def __init__(
        self,
        *,
        query_payload: dict | None = None,
        collections_payload: dict | None = None,
        summary_payload: dict | None = None,
    ) -> None:
        super().__init__()
        self._query = query_payload or {
            "status": "ok",
            "query": "refund policy",
            "collection": None,
            "top_k": 5,
            "results": [{"text": "refunds within 30 days"}],
            "images": [],
            "raw_metadata": [],
        }
        self._collections = collections_payload or {
            "status": "ok",
            "include_stats": True,
            "collections": [{"name": "contracts", "count": 12}],
            "raw_metadata": [],
        }
        self._summary = summary_payload or {
            "status": "ok",
            "document_id": "doc_abc",
            "collection": None,
            "summary": [{"title": "Refund SOP", "chunk_count": 4}],
            "images": [],
            "raw_metadata": [],
        }

    async def query(
        self, query: str, *, top_k: int = 5, collection: str | None = None
    ) -> dict:
        return {**self._query, "query": query, "top_k": top_k, "collection": collection}

    async def list_collections(self, *, include_stats: bool = True) -> dict:
        return {**self._collections, "include_stats": include_stats}

    async def get_document_summary(
        self, doc_id: str, *, collection: str | None = None
    ) -> dict:
        return {
            **self._summary,
            "document_id": doc_id,
            "collection": collection,
        }


@pytest.fixture()
def client():
    fake = _FakeRagService()

    async def _override() -> RagService:
        return fake

    app.dependency_overrides[get_rag_service] = _override
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_rag_service, None)


@pytest.mark.integration
def test_query_endpoint(client: TestClient) -> None:
    r = client.post("/api/rag/query", json={"query": "refund policy", "top_k": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["query"] == "refund policy"
    assert body["top_k"] == 3
    assert body["results"] == [{"text": "refunds within 30 days"}]


@pytest.mark.integration
def test_query_empty_query_422(client: TestClient) -> None:
    r = client.post("/api/rag/query", json={"query": "   "})
    assert r.status_code == 422


@pytest.mark.integration
def test_collections_endpoint(client: TestClient) -> None:
    r = client.get("/api/rag/collections")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["collections"] == [{"name": "contracts", "count": 12}]


@pytest.mark.integration
def test_document_summary_endpoint(client: TestClient) -> None:
    r = client.get("/api/rag/documents/doc_abc/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["document_id"] == "doc_abc"
    assert body["summary"] == [{"title": "Refund SOP", "chunk_count": 4}]


@pytest.mark.integration
def test_graceful_degradation_when_disabled(client: TestClient) -> None:
    disabled = _FakeRagService(
        query_payload={"status": "disabled", "error": "rag server not configured"},
        collections_payload={"status": "disabled", "error": "no config"},
        summary_payload={"status": "disabled", "error": "no config"},
    )

    async def _override() -> RagService:
        return disabled

    app.dependency_overrides[get_rag_service] = _override
    try:
        assert client.post("/api/rag/query", json={"query": "x"}).json()["status"] == "disabled"
        assert client.get("/api/rag/collections").json()["status"] == "disabled"
        assert (
            client.get("/api/rag/documents/d/summary").json()["status"] == "disabled"
        )
    finally:
        app.dependency_overrides.pop(get_rag_service, None)
