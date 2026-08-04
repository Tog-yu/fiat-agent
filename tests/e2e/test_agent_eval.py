"""End-to-end agent evaluation suite (DEV_SPEC §K4).

Runs a small, stable eval dataset (``tests/fixtures/agent_eval_cases.json``)
covering the four required scenarios — RAG 问答, 告警诊断, 权限拒绝, 审批等待 —
through the real :class:`~fiat_agent.orchestrator.graph.AgentGraph` with hermetic
fakes (no LLM / MCP / DB). Each case yields a normalized, stable result dict so
regressions surface as structural diffs rather than free-text mismatches.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
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

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "agent_eval_cases.json"


class ScriptedModel(BaseChatModel):
    """Deterministic model: call ``script[0]`` then return ``final_answer``."""

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


def _build(case: dict):
    audit = AuditService(InMemoryAuditRepository())
    registry = ToolRegistry()
    called: dict[str, int] = {}

    tool = case["tool"]
    # Risk/approval mirrors config/tool_policies.yaml so can_execute agrees.
    risk = {
        "rag_query": RiskLevel.L1,
        "es_query": RiskLevel.L2,
        "cashback_reconcile": RiskLevel.L4,
        "cashback_submit": RiskLevel.L5,
    }[tool]
    approval_required = tool in ("cashback_reconcile", "cashback_submit")
    registry.register(
        ToolDefinition(
            name=tool,
            description=tool,
            risk_level=risk,
            approval_required=approval_required,
        )
    )

    async def handler(actor, args, ctx):
        called[tool] = called.get(tool, 0) + 1
        return f"{tool} result"

    gw = ToolGateway(audit)
    gw.register_handler(tool, handler)

    fake = ScriptedModel(tool, case["final_answer"])
    mgw = ModelGateway(
        policies=SimpleNamespace(),
        provider_factory=lambda p, t, c: fake,
        audit_sink=lambda task, model, usage: audit.record_model_usage(
            task_type=task, model=model, usage=usage
        ),
    )
    graph = AgentGraph(registry=registry, gateway=gw, model_gateway=mgw, audit_service=audit)
    return graph, audit, called


def _run_case(case: dict) -> dict:
    graph, audit, called = _build(case)
    actor_raw = case["actor"]
    actor = ActorContext(
        actor_id=actor_raw["actor_id"],
        roles=actor_raw["roles"],
        environment=Environment(actor_raw["environment"]),
    )
    messages = [ChatMessage(role="user", content=case["input"])]
    result = asyncio.run(graph.arun(actor=actor, messages=messages, session_id=case["id"]))

    task_type = _read(result, "task_type")
    approval_state = _read(result, "approval_state") or ApprovalState.NOT_REQUIRED
    approval_state = (
        approval_state.value if isinstance(approval_state, ApprovalState) else str(approval_state)
    )
    executed = case["tool"] if called.get(case["tool"], 0) > 0 else None

    if approval_state == "pending":
        outcome = "approval_pending"
    elif executed is not None:
        outcome = "answered"
    else:
        outcome = "denied"

    return {
        "case_id": case["id"],
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


@pytest.mark.e2e
def test_eval_dataset_stable_structure():
    cases = json.loads(FIXTURE.read_text())
    assert len(cases) == 4, "eval dataset must cover the 4 required scenarios"

    results = [_run_case(c) for c in cases]

    # Every result exposes the stable schema.
    for r in results:
        assert set(r.keys()) == {
            "case_id",
            "task_type",
            "outcome",
            "tool_executed",
            "approval_state",
            "final_answer",
        }

    by_id = {r["case_id"]: r for r in results}
    assert set(by_id) == {c["id"] for c in cases}


@pytest.mark.e2e
@pytest.mark.parametrize("case_id", ["eval-rag-001", "eval-alert-001", "eval-deny-001", "eval-approve-001"])
def test_eval_case_meets_expectation(case_id):
    cases = json.loads(FIXTURE.read_text())
    case = next(c for c in cases if c["id"] == case_id)
    result = _run_case(case)
    expect = case["expect"]

    assert result["outcome"] == expect["outcome"], result
    assert result["approval_state"] == expect["approval_state"], result
    assert result["tool_executed"] == expect["tool_executed"], result
    # The answered scenarios must produce a non-empty final answer.
    if expect["outcome"] == "answered":
        assert result["final_answer"]
