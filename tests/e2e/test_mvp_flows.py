"""MVP end-to-end acceptance (DEV_SPEC §K5).

Drives the five core MVP flows through the real
:class:`~fiat_agent.orchestrator.graph.AgentGraph` with hermetic fakes:

* RAG 问答 — knowledge-base question answered via ``rag_query``.
* 告警诊断 — alert triage answered via ``es_query``.
* 测试账号助手 — test-account provisioning via ``test_env`` (fake backend).
* 权限拒绝 — a tool the role may not use is never executed.
* 审批等待 — a high-risk tool halts for human approval.

All dependency on LLM / MCP / DB / production systems is faked. Each flow
asserts the outcome category, tool execution and (where relevant) approval
state — the same stable contract used by the eval suite (§K4).
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


class ScriptedModel(BaseChatModel):
    """Call ``tool_name`` once, then return ``final_answer``."""

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
                    FunctionCall(name=self._tool, arguments='{"q":"x"}', id="call_1")
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


def _run(tool: str, risk: RiskLevel, approval_required: bool, final_answer: str,
         actor: ActorContext, user_input: str) -> dict:
    audit = AuditService(InMemoryAuditRepository())
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name=tool, description=tool, risk_level=risk, approval_required=approval_required
        )
    )
    called = {"n": 0}

    async def handler(act, args, ctx):
        called["n"] += 1
        # The fake backend returns the substantive answer; final_node renders
        # the tool result as the final answer (see G8 RAG test convention).
        return final_answer

    gw = ToolGateway(audit)
    gw.register_handler(tool, handler)

    fake = ScriptedModel(tool, final_answer)
    mgw = ModelGateway(
        policies=SimpleNamespace(),
        provider_factory=lambda p, t, c: fake,
        audit_sink=lambda task, model, usage: audit.record_model_usage(
            task_type=task, model=model, usage=usage
        ),
    )
    graph = AgentGraph(registry=registry, gateway=gw, model_gateway=mgw, audit_service=audit)
    result = asyncio.run(
        graph.arun(actor=actor, messages=[ChatMessage(role="user", content=user_input)],
                   session_id=f"mvp-{tool}")
    )

    task_type = _read(result, "task_type")
    approval_state = _read(result, "approval_state") or ApprovalState.NOT_REQUIRED
    approval_state = (
        approval_state.value if isinstance(approval_state, ApprovalState) else str(approval_state)
    )
    executed = tool if called["n"] > 0 else None
    if approval_state == "pending":
        outcome = "approval_pending"
    elif executed is not None:
        outcome = "answered"
    else:
        outcome = "denied"
    return {
        "task_type": task_type.value if task_type is not None else None,
        "outcome": outcome,
        "tool_executed": executed,
        "approval_state": approval_state,
        "final_answer": _read(result, "final_answer"),
    }


def _read(result, key):
    if isinstance(result, dict):
        return result.get(key)
    return getattr(result, key, None)


def _oncall() -> ActorContext:
    return ActorContext(actor_id="u_oncall", roles=["oncall"], environment=Environment.DEV)


def _ops() -> ActorContext:
    return ActorContext(actor_id="u_ops", roles=["ops"], environment=Environment.DEV)


@pytest.mark.e2e
def test_rag_qa_flow():
    r = _run(
        "rag_query", RiskLevel.L1, False,
        "根据知识库，人民币跨境结算规定见第三章。",
        _oncall(), "知识库里怎么规定的人民币跨境结算？",
    )
    assert r["outcome"] == "answered"
    assert r["tool_executed"] == "rag_query"
    assert "人民币跨境结算" in r["final_answer"]


@pytest.mark.e2e
def test_alert_diagnosis_flow():
    r = _run(
        "es_query", RiskLevel.L2, False,
        "根据ES日志，支付失败率升高源于下游通道超时。",
        _oncall(), "生产告警日志显示支付失败率升高，帮我排查一下。",
    )
    assert r["outcome"] == "answered"
    assert r["tool_executed"] == "es_query"
    assert r["final_answer"]


@pytest.mark.e2e
def test_test_account_flow_fake_backend():
    r = _run(
        "test_env", RiskLevel.L3, False,
        "已通过测试环境创建账号 TEST_ACC_001。",
        _oncall(), "帮我开一个测试账号用于联调。",
    )
    assert r["outcome"] == "answered"
    assert r["tool_executed"] == "test_env"
    assert "TEST_ACC_001" in r["final_answer"]


@pytest.mark.e2e
def test_permission_denied_flow():
    r = _run(
        "cashback_submit", RiskLevel.L5, True,
        "抱歉，您当前角色没有权限执行该生产提交操作。",
        _oncall(), "帮我向生产数据库提交一条记录。",
    )
    assert r["outcome"] == "denied"
    assert r["tool_executed"] is None
    assert r["approval_state"] == "not_required"


@pytest.mark.e2e
def test_approval_pending_flow():
    r = _run(
        "cashback_reconcile", RiskLevel.L4, True,
        "已生成返现对账 dry-run 报告，等待审批后执行。",
        _ops(), "帮我做一次返现对账 dry-run。",
    )
    assert r["outcome"] == "approval_pending"
    assert r["approval_state"] == "pending"
    assert r["tool_executed"] is None
