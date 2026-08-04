"""H2 e2e test: RAG 问答 workflow (DEV_SPEC §H2).

Exercises :func:`fiat_agent.workflows.rag_qa.run_rag_qa` end-to-end with hermetic
fakes (no real LLM / MCP server / DB) and asserts the three acceptance pillars:

1. **自动调用 MCP RAG** — the ``rag_query`` tool is invoked through the audited
   ToolGateway (gateway handler runs, a success ToolCallRecord + ``tool_call``
   audit event are written).
2. **回答带来源** — when RAG returns citations, the result carries them and
   ``has_evidence`` is ``True``; the model is only called in this branch.
3. **无依据时拒答** — when RAG returns no citations (or errors), the workflow
   refuses deterministically with ``has_evidence=False`` and the model is NOT
   called.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from fiat_agent.audit.repository import InMemoryAuditRepository
from fiat_agent.audit.service import AuditService
from fiat_agent.models.base import BaseChatModel, ChatRequest, ChatResponse, TokenUsage
from fiat_agent.models.gateway import ModelGateway
from fiat_agent.rag.context_merge import Citation, MergedRagContext
from fiat_agent.schemas.common import ActorContext, Environment, RiskLevel, TaskType
from fiat_agent.tool_gateway.gateway import ToolGateway
from fiat_agent.tools.registry import ToolRegistry
from fiat_agent.tools.schemas import ToolDefinition
from fiat_agent.workflows.rag_qa import RagQaResult, run_rag_qa


class _FakeModel(BaseChatModel):
    """Deterministic model that records how many times it was called."""

    provider = "fake"

    def __init__(self, answer: str) -> None:
        self._answer = answer
        self.calls = 0

    async def chat(self, request: ChatRequest) -> ChatResponse:  # noqa: D401
        self.calls += 1
        return ChatResponse(
            content=self._answer,
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )

    async def stream(self, request: ChatRequest):
        yield ChatResponse(content=self._answer)


def _build(rag_raw: Any, model_answer: str):
    """Assemble a hermetic RAG-QA run: audit + registry + gateway + model."""
    audit = AuditService(InMemoryAuditRepository())
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="rag_query",
            description="RAG search",
            risk_level=RiskLevel.L1,
            approval_required=False,
        )
    )
    gateway = ToolGateway(audit)
    called: dict[str, int] = {"n": 0}

    async def rag_handler(actor, args, ctx):  # type: ignore[no-untyped-def]
        called["n"] += 1
        if isinstance(rag_raw, Exception):
            raise rag_raw
        return rag_raw

    gateway.register_handler("rag_query", rag_handler)

    model = _FakeModel(model_answer)
    model_gw = ModelGateway(
        policies=SimpleNamespace(),
        provider_factory=lambda p, t, c: model,
        audit_sink=lambda task, m, usage: audit.record_model_usage(
            task_type=task, model=m, usage=usage
        ),
    )
    return audit, registry, gateway, model_gw, model, called


def _actor() -> ActorContext:
    return ActorContext(actor_id="u1", roles=["oncall"], environment=Environment.DEV)


@pytest.mark.e2e
def test_rag_qa_answers_with_sources():
    citations = [
        Citation(
            collection="kb",
            doc_id="d1",
            chunk_id="c1",
            source="人民币跨境结算手册",
            snippet="第三章规定跨境结算需双人复核。",
        )
    ]
    merged = MergedRagContext(
        query="人民币跨境结算怎么规定的？",
        answer="人民币跨境结算规定见第三章，需双人复核。",
        citations=citations,
    )
    audit, registry, gateway, model_gw, model, called = _build(
        merged, "根据知识库，人民币跨境结算规定见第三章，需双人复核。"
    )
    actor = _actor()

    result: RagQaResult = asyncio.run(
        run_rag_qa(
            "人民币跨境结算怎么规定的？",
            actor=actor,
            registry=registry,
            gateway=gateway,
            model_gateway=model_gw,
            audit_service=audit,
        )
    )

    # Acceptance 1: MCP RAG was auto-called through the gateway.
    assert called["n"] == 1
    assert any(
        c.tool_name == "rag_query" and c.status == "success" for c in gateway.tool_calls
    )
    events = asyncio.run(audit._repo.list(limit=100))
    assert any(e.type == "tool_call" for e in events)

    # Acceptance 2: answer carries sources and evidence flag.
    assert result.has_evidence is True
    assert result.confidence == "high"
    assert len(result.citations) == 1
    assert result.citations[0].source == "人民币跨境结算手册"
    assert "第三章" in result.answer
    # Model only runs in the evidence branch.
    assert model.calls == 1


@pytest.mark.e2e
def test_rag_qa_refuses_without_evidence():
    # RAG returns an empty citation set -> no evidence.
    audit, registry, gateway, model_gw, model, called = _build(
        MergedRagContext(query="x", answer="", citations=[]), "MUST NOT APPEAR"
    )
    actor = _actor()

    result = asyncio.run(
        run_rag_qa(
            "一个知识库里没有的问题",
            actor=actor,
            registry=registry,
            gateway=gateway,
            model_gateway=model_gw,
            audit_service=audit,
        )
    )

    # Acceptance 3: refuses deterministically, does NOT call the model.
    assert result.has_evidence is False
    assert result.confidence == "low"
    assert result.citations == []
    assert model.calls == 0
    assert "无法确认" in result.answer


@pytest.mark.e2e
def test_rag_qa_refuses_on_rag_error():
    # RAG lookup raises -> treated as an error, still refuse (no evidence).
    audit, registry, gateway, model_gw, model, called = _build(
        RuntimeError("rag server down"), "MUST NOT APPEAR"
    )
    actor = _actor()

    result = asyncio.run(
        run_rag_qa(
            "任何问题",
            actor=actor,
            registry=registry,
            gateway=gateway,
            model_gateway=model_gw,
            audit_service=audit,
        )
    )

    assert result.rag_status == "error"
    assert result.has_evidence is False
    assert result.error is not None
    assert model.calls == 0
