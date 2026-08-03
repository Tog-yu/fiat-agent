"""RAG context merge (phase E5, DEV_SPEC §6.5, §7.2).

Merges a parsed RAG tool response (text + citations) into a single context
block the Agent can consume, while keeping every source attached so the answer
is auditable. Citations are tracked by collection / doc_id / chunk_id.
"""

from __future__ import annotations

from typing import Any

from fiat_agent.mcp_clients.content_parser import ParsedMcpContent, parse_mcp_contents
from fiat_agent.rag.citations import Citation
from fiat_agent.schemas.common import FiatModel


class MergedRagContext(FiatModel):
    """A query, its merged answer text, and the citations that back it."""

    query: str = ""
    answer: str = ""
    citations: list[Citation] = []

    @property
    def context(self) -> str:
        """The answer followed by an attached Sources section.

        The answer text and the provenance are kept together so the LLM never
        loses track of where the answer came from.
        """
        parts = [self.answer] if self.answer else []
        if self.citations:
            lines = ["", "Sources:"]
            for i, c in enumerate(self.citations, 1):
                label = c.source or f"{c.collection}/{c.doc_id}/{c.chunk_id}"
                provenance = (
                    f" (collection={c.collection}, doc_id={c.doc_id}, chunk_id={c.chunk_id})"
                    if (c.collection or c.doc_id or c.chunk_id)
                    else ""
                )
                lines.append(f"[{i}] {label}{provenance}")
            parts.append("\n".join(lines))
        return "\n".join(parts)


def _extract_citations(parsed: ParsedMcpContent) -> list[Citation]:
    """Build `Citation`s from parsed metadata (EmbeddedResource / dicts)."""
    out: list[Citation] = []
    for m in parsed.metadata:
        if not isinstance(m, dict):
            continue
        out.append(
            Citation(
                collection=str(m.get("collection", "")),
                doc_id=str(
                    m.get("doc_id") or m.get("document_id") or m.get("docId") or ""
                ),
                chunk_id=str(m.get("chunk_id") or m.get("chunkId") or ""),
                source=str(m.get("source") or m.get("title") or m.get("uri") or ""),
                snippet=str(m.get("snippet") or m.get("text") or ""),
                score=float(m["score"]) if m.get("score") is not None else None,
            )
        )
    return out


def merge_rag_context(
    query: str,
    contents: list[Any],
    citations: list[Citation] | None = None,
) -> MergedRagContext:
    """Merge a raw MCP content list into a `MergedRagContext`.

    Args:
        query: the original user question (kept for traceability).
        contents: the MCP tool `content` items (text / image / resource).
        citations: explicit citations; if omitted, they are extracted from the
            structured metadata inside `contents`.
    """
    parsed = parse_mcp_contents(contents)
    if citations is None:
        citations = _extract_citations(parsed)
    return MergedRagContext(
        query=query, answer=parsed.text_context, citations=citations
    )
