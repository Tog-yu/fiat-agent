"""E5 unit test: RAG context merge (DEV_SPEC §E5).

Covers:
  - the merged context keeps the answer AND attached source citations;
  - collection / doc_id / chunk_id remain traceable on each citation;
  - citations can be provided explicitly or extracted from parsed metadata.
"""

from __future__ import annotations

import mcp.types as types
import pytest

from fiat_agent.mcp_clients.content_parser import parse_mcp_contents
from fiat_agent.rag.citations import Citation
from fiat_agent.rag.context_merge import MergedRagContext, merge_rag_context


@pytest.mark.unit
def test_merge_retains_citations_and_traceability() -> None:
    contents = [types.TextContent(type="text", text="The answer is 42.")]
    citations = [
        Citation(
            collection="kb",
            doc_id="d1",
            chunk_id="c1",
            source="doc1.md",
            snippet="42",
        )
    ]
    merged = merge_rag_context("what is the answer?", contents, citations)

    assert merged.answer == "The answer is 42."
    assert len(merged.citations) == 1
    c = merged.citations[0]
    assert c.collection == "kb"
    assert c.doc_id == "d1"
    assert c.chunk_id == "c1"
    # Sources are retained in the merged context.
    assert "The answer is 42." in merged.context
    assert "doc1.md" in merged.context
    assert "kb" in merged.context


@pytest.mark.unit
def test_extract_citations_from_metadata() -> None:
    parsed = parse_mcp_contents(
        [
            {
                "type": "resource",
                "collection": "kb",
                "doc_id": "d2",
                "chunk_id": "c2",
                "source": "doc2.md",
                "score": 0.91,
            }
        ]
    )
    # _extract_citations runs inside merge only when contents carry metadata;
    # here we exercise it via a metadata-bearing parse + explicit merge.
    from fiat_agent.rag.context_merge import _extract_citations

    cites = _extract_citations(parsed)
    assert len(cites) == 1
    assert cites[0].collection == "kb"
    assert cites[0].doc_id == "d2"
    assert cites[0].chunk_id == "c2"
    assert cites[0].source == "doc2.md"
    assert cites[0].score == 0.91
    # Wire it through merge_rag_context to confirm end-to-end traceability.
    merged = merge_rag_context("q", parsed.metadata, citations=cites)
    assert merged.citations[0].doc_id == "d2"


@pytest.mark.unit
def test_empty_context_has_no_sources() -> None:
    merged: MergedRagContext = merge_rag_context("q", [], citations=[])
    assert merged.answer == ""
    assert merged.citations == []
    assert merged.context == ""
