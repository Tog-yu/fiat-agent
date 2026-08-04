"""G8 integration test: complete LangGraph agent orchestration (DEV_SPEC §G8).

Wires the G1–G7 nodes through :class:`fiat_agent.orchestrator.graph.AgentGraph`
and verifies the two acceptance pillars:

1. **RAG 问答端到端通过** — a knowledge-base question is classified, the model
   calls ``rag_query``, the tool executes through the audited gateway, and the
   final answer carries the RAG answer text.
2. **工具调用 / session 写入 / event stream 均触发** — tool calls are executed
   and audited; the optional ``session_writer`` / ``event_emitter`` callbacks are
   invoked on every step; and a high-risk tool is halted at the approval gate
   (L4 requires human approval, never auto-executed).

All dependencies are hermetic fakes (no real LLM / MCP server / DB).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from fiat_agent.audit.repository import InMemoryAuditRepository
from fiat_agent.audit.service import AuditService
from fiat_agent.models.base import (
    BaseChatModel,
    ChatMessage,
    ChatResponse,
    FunctionCall,
    TokenUsage,
)
from fiat_agent.models.gateway import ModelGateway
from fiat_agent.orchestrator.graph import AgentGraph
from fiat_agent.orchestrator.state import ApprovalState
from fiat_agent.schemas.common import ActorContext, Environment, RiskLevel, TaskType
from fiat_agent.tool_gateway.gateway import ToolGateway
from fiat_agent.tools.registry import ToolRegistry
from fiat_agent.tools.schemas import ToolDefinition


class FakeReActModel(BaseChatModel):
    """A deterministic ReAct stand-in: tool call on first turn, text on second."""

    provider = "fake"

    def __init__(self, tool_name: str, final_answer: str) -> None:
        self._tool = tool_name
        self._answer = final_answer
        self.calls = 0

    async def chat(self, request):  # noqa: D401 - minimal fake
        self.calls += 1
        if self.calls == 1:
            return ChatResponse(
                content=None,
                function_calls=[
                    FunctionCall(name=self._tool, arguments='{"query":"x"}', id="call_1")
                ],
                finish_reason="tool_calls",
                usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )
        return ChatResponse(
            content=self._answer,
            function_calls=None,
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=20, completion_tokens=8, total_tokens=28),
        )

    async def stream(self, request):
        yield ChatResponse(content=self._answer)


def _build(tool_name: str, final_answer: str, rag_answer: str):
    """Assemble a hermetic :class:`AgentGraph` for one scenario."""
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
    registry.register(
        ToolDefinition(
            name="cashback_reconcile",
            description="cashback dry-run",
            risk_level=RiskLevel.L4,
            approval_required=True,
        )
    )

    called = {"n": 0}

    async def rag_handler(actor, args, ctx):
        called["n"] += 1
        return rag_answer

    async def cb_handler(actor, args, ctx):
        called["n"] += 1
        return {"reconcile": "ok"}

    gw = ToolGateway(audit)
    gw.register_handler("rag_query", rag_handler)
    gw.register_handler("cashback_reconcile", cb_handler)

    fake = FakeReActModel(tool_name, final_answer)
    mgw = ModelGateway(
        policies=SimpleNamespace(),
        provider_factory=lambda p, t, c: fake,
        audit_sink=lambda task, model, usage: audit.record_model_usage(
            task_type=task, model=model, usage=usage
        ),
    )

    session_events: list[tuple[str, dict]] = []
    event_events: list[tuple[str, dict]] = []

    async def session_writer(et, payload):
        session_events.append((et, payload))

    async def event_emitter(et, payload):
        event_events.append((et, payload))

    graph = AgentGraph(
        registry=registry,
        gateway=gw,
        model_gateway=mgw,
        audit_service=audit,
        session_writer=session_writer,
        event_emitter=event_emitter,
    )
    return graph, gw, audit, called, session_events, event_events


def _get(result, key):
    """Read a field from either a GraphState or the raw state dict."""
    if isinstance(result, dict):
        return result.get(key)
    return getattr(result, key)


@pytest.mark.integration
def test_rag_qa_end_to_end():
    graph, gw, audit, called, session_events, event_events = _build(
        tool_name="rag_query",
        final_answer="根据知识库，人民币跨境结算规定见第三章。",
        rag_answer="法币知识库答案：人民币跨境结算规定见第三章。",
    )
    actor = ActorContext(actor_id="u1", roles=["oncall"], environment=Environment.DEV)
    messages = [ChatMessage(role="user", content="知识库里怎么规定的人民币跨境结算？")]

    result = asyncio.run(graph.arun(actor=actor, messages=messages, session_id="s_rag"))

    # 1) classified as a RAG question.
    assert _get(result, "task_type") == TaskType.RAG_QA

    # 2) the RAG tool actually executed (handler ran once).
    assert called["n"] == 1
    assert any(
        c.tool_name == "rag_query" and c.status == "success" for c in gw.tool_calls
    )

    # 3) final answer carries the RAG answer text.
    assert _get(result, "final_answer") is not None
    assert "人民币跨境结算" in _get(result, "final_answer")

    # 4) L1 tool needs no approval.
    assert _get(result, "approval_state") == ApprovalState.NOT_REQUIRED

    # 5) tool call was audited; session writes + event stream fired.
    events = asyncio.run(audit._repo.list(limit=100))
    assert any(e.type == "tool_call" for e in events)
    assert len(session_events) > 0
    assert len(event_events) > 0
    assert any(et == "tool_call" for et, _ in session_events)
    assert any(et == "final" for et, _ in session_events)


@pytest.mark.integration
def test_high_risk_requires_approval():
    graph, gw, audit, called, session_events, event_events = _build(
        tool_name="cashback_reconcile",
        final_answer="已生成返现对账 dry-run 报告。",
        rag_answer="",
    )
    actor = ActorContext(actor_id="u2", roles=["ops"], environment=Environment.DEV)
    messages = [ChatMessage(role="user", content="帮我做一次返现对账 dry-run。")]

    result = asyncio.run(graph.arun(actor=actor, messages=messages, session_id="s_cb"))

    # High-risk tool must NOT be executed without approval.
    assert called["n"] == 0
    assert _get(result, "approval_state") == ApprovalState.PENDING

    # The graph-level approval gate halts before the tool node runs, so the
    # gateway is never invoked at all (no tool-call record, no execution).
    assert gw.tool_calls == []

    # An approval_requested audit event was recorded by the approval node.
    events = asyncio.run(audit._repo.list(limit=100))
    assert any(e.type == "approval_requested" for e in events)

    # Event stream includes the approval decision.
    assert any(et == "approval" for et, _ in event_events)

    # Run halted for human approval -> no final answer produced.
    assert _get(result, "final_answer") is None
