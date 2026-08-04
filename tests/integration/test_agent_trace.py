"""Integration test for agent execution trace (DEV_SPEC §K3).

Verifies that a run records one trace entry per node, that every ReAct round
covers ``plan`` / ``model_call`` / ``tool_call`` / ``final``, and that a node
failure is recorded (so the failed node is locatable after the fact).

Reuses the hermetic ReAct fakes from the G8 graph test to avoid any real LLM
or external system.
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
from fiat_agent.schemas.common import ActorContext, Environment, RiskLevel
from fiat_agent.tool_gateway.gateway import ToolGateway
from fiat_agent.tools.registry import ToolRegistry
from fiat_agent.tools.schemas import ToolDefinition


class FakeReActModel(BaseChatModel):
    """Tool call on first turn, final text on second."""

    provider = "fake"

    def __init__(self, tool_name: str, final_answer: str) -> None:
        self._tool = tool_name
        self._answer = final_answer
        self.calls = 0

    async def chat(self, request):
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


def _build(tool_name: str = "rag_query", fail_tool: bool = False):
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

    async def rag_handler(actor, args, ctx):
        if fail_tool:
            raise RuntimeError("simulated tool failure")
        return "法币知识库答案：人民币跨境结算规定见第三章。"

    gw = ToolGateway(audit)
    gw.register_handler("rag_query", rag_handler)

    fake = FakeReActModel(tool_name, "根据知识库，人民币跨境结算规定见第三章。")
    mgw = ModelGateway(
        policies=SimpleNamespace(),
        provider_factory=lambda p, t, c: fake,
        audit_sink=lambda task, model, usage: audit.record_model_usage(
            task_type=task, model=model, usage=usage
        ),
    )

    # Wire the graph's trace sink into the audit service.
    graph = AgentGraph(
        registry=registry,
        gateway=gw,
        model_gateway=mgw,
        audit_service=audit,
        trace_sink=lambda record: audit.record_trace(**record),
    )
    return graph, audit


def _trace_events(audit: AuditService):
    events = asyncio.run(audit._repo.list(limit=10_000))
    return [e for e in events if e.type == "agent_trace"]


@pytest.mark.integration
def test_trace_covers_plan_model_tool_final_per_round():
    graph, audit = _build()
    actor = ActorContext(actor_id="u1", roles=["oncall"], environment=Environment.DEV)
    messages = [ChatMessage(role="user", content="知识库里怎么规定的人民币跨境结算？")]

    asyncio.run(graph.arun(actor=actor, messages=messages, session_id="s_trace"))

    traces = _trace_events(audit)
    assert traces, "no agent_trace events recorded"

    steps = {t.metadata["step"] for t in traces}
    # Every required category must appear across the run.
    assert {"plan", "model_call", "tool_call", "final"} <= steps

    # Each trace entry carries round + node + status.
    for t in traces:
        assert "round" in t.metadata and "node" in t.metadata
        assert t.metadata["status"] == "ok"
        assert t.metadata["session_id"] == "s_trace"

    # Round 1 must include model_call, plan and tool_call (the tool-executing
    # round); round 2 (final answer) must include model_call + final.
    round1 = {t.metadata["step"] for t in traces if t.metadata["round"] == 1}
    assert {"model_call", "plan", "tool_call"} <= round1
    round2 = {t.metadata["step"] for t in traces if t.metadata["round"] == 2}
    assert {"model_call", "final"} <= round2


@pytest.mark.integration
def test_trace_records_failed_node():
    graph, audit = _build(fail_tool=True)
    actor = ActorContext(actor_id="u2", roles=["oncall"], environment=Environment.DEV)
    messages = [ChatMessage(role="user", content="查询知识库。")]

    # The graph handles a tool error gracefully (no exception escapes), but the
    # failing node must still be recorded in the trace so it is locatable.
    asyncio.run(graph.arun(actor=actor, messages=messages, session_id="s_fail"))

    traces = _trace_events(audit)
    errors = [t for t in traces if t.metadata["status"] == "error"]
    assert errors, "no error trace recorded for the failed node"

    # The failed node must be locatable by name and carry the error detail.
    assert any(t.metadata["node"] == "tool" for t in errors)
    assert any(
        "simulated tool failure" in (t.metadata["detail"].get("errors", []) or [])
        for t in errors
    )