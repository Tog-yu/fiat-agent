"""Elasticsearch read-only tool contract (phase F4, DEV_SPEC §F4).

The agent is **never** allowed to send arbitrary ES DSL. This module exposes a
single structured query surface (:class:`EsQueryRequest`) and builds a fixed,
safe query template from whitelisted indices and controlled parameters. A
pluggable client (real or fake) performs the actual ``search`` — no raw query
body is ever accepted from the caller, so injection of arbitrary DSL is
structurally impossible.
"""

from __future__ import annotations

from typing import Any

from fiat_agent.errors import ToolContractViolation
from fiat_agent.schemas.common import FiatModel

# Whitelisted indices the agent may read (DEV_SPEC §F4: 白名单 index).
ALLOWED_INDICES: frozenset[str] = frozenset({"alerts", "logs", "traces"})
MAX_SIZE = 100
DEFAULT_SIZE = 20


class EsQueryRequest(FiatModel):
    """Structured, safe query surface — NOT a raw ES DSL body.

    Only these fields exist; there is no parameter that forwards arbitrary DSL.
    """

    index: str
    keyword: str = ""
    level: str | None = None  # e.g. "ERROR", "WARN"
    since_minutes: int = 60
    size: int = DEFAULT_SIZE


class EsSearchResult(FiatModel):
    """Normalized, model-safe result (raw ``_source`` only)."""

    index: str
    total: int = 0
    hits: list[dict[str, Any]] = []


class FakeEsClient:
    """In-memory stand-in for an ES client (used by tests)."""

    def __init__(self, store: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.store: dict[str, list[dict[str, Any]]] = store or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def search(self, index: str, body: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((index, body))
        hits = self.store.get(index, [])
        return {
            "hits": {
                "total": {"value": len(hits)},
                "hits": [{"_source": h} for h in hits],
            }
        }


def build_safe_query(request: EsQueryRequest) -> dict[str, Any]:
    """Build a fixed, safe ES query from structured params only.

    The keyword becomes a ``match`` on ``message`` (never a raw query string);
    level becomes a ``term``; time is bounded by a ``range`` filter. The shape is
    constant — the caller cannot inject scripts, raw DSL, or unbounded queries.
    """
    must: list[dict[str, Any]] = []
    if request.keyword:
        must.append({"match": {"message": request.keyword}})
    if request.level:
        must.append({"term": {"level": request.level}})
    return {
        "size": request.size,
        "query": {
            "bool": {
                "filter": [
                    {"range": {"@timestamp": {"gte": f"now-{request.since_minutes}m"}}}
                ],
                "must": must,
            }
        },
        "sort": [{"@timestamp": {"order": "desc"}}],
    }


class EsTool:
    """Read-only ES query tool bound to a client (real or :class:`FakeEsClient`)."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def validate(self, request: EsQueryRequest) -> None:
        """Enforce the contract before any search (raises on violation)."""
        if request.index not in ALLOWED_INDICES:
            raise ToolContractViolation(
                f"index '{request.index}' is not in the allowed list",
                metadata={"allowed_indices": sorted(ALLOWED_INDICES)},
            )
        if request.size > MAX_SIZE:
            raise ToolContractViolation(
                f"size {request.size} exceeds max {MAX_SIZE}",
                metadata={"max_size": MAX_SIZE},
            )
        if request.since_minutes <= 0:
            raise ToolContractViolation("since_minutes must be positive")

    async def query(self, request: EsQueryRequest) -> EsSearchResult:
        """Run a safe, whitelisted, size-capped query against the bound client."""
        self.validate(request)
        body = build_safe_query(request)  # caller-supplied DSL is never used
        raw = await self._client.search(request.index, body)
        raw_hits = raw.get("hits", {}).get("hits", [])
        hits = [h.get("_source", h) for h in raw_hits]
        total = raw.get("hits", {}).get("total", {})
        total_val = (
            total.get("value", len(hits)) if isinstance(total, dict) else int(total)
        )
        return EsSearchResult(index=request.index, total=int(total_val), hits=hits)
