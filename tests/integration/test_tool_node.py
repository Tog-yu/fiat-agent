"""G5 integration test: tool-execution node (DEV_SPEC §G5).

Wires the real ToolGateway (F3) into the tool node and verifies:
  1. tool results are fed back to the model as `role="tool"` messages;
  2. a permission/approval-gated call is NOT executed (handler never runs) and
     the deferral is still surfaced as a tool message.
"""

from __future__ import annotations

import asyncio

import pytest

from fiat_agent.audit.repository import InMemoryAuditRepository
from fiat_agent.audit.service import AuditService
from fiat_agent.models.base import ChatMessage, FunctionCall
from fiat_agent.orchestrator.nodes.tool import tool_node
from fiat_agent.orchestrator.state import AgentState
from fiat_agent.schemas.common import ActorContext, Environment
from fiat_agent.tool_gateway.gateway import ToolGateway


@pytest.mark.integration
def test_tool_results_fed_back_to_model() -> None:
    called = {"n": 0}
    gw = ToolGateway(AuditService(InMemoryAuditRepository()))

    async def handler(actor, args, ctx):
        called["n"] += 1
        return {"hits": 2}

    gw.register_handler("es_query", handler)
    state = AgentState(
        actor=ActorContext(actor_id="o", roles=["ops"], environment=Environment.DEV),
        messages=[
            ChatMessage(
                role="assistant",
                tool_calls=[
                    FunctionCall(name="es_query", arguments='{"index":"logs"}', id="call1")
                ],
            )
        ],
    )

    delta = asyncio.run(tool_node(state, gw))
    assert called["n"] == 1  # handler executed
    assert len(delta["messages"]) == 1
    msg = delta["messages"][0]
    assert msg.role == "tool"
    assert msg.tool_call_id == "call1"
    assert "hits" in (msg.content or "")
    assert delta["tool_results"][0].tool_name == "es_query"
    assert delta["tool_results"][0].status.value == "success"


@pytest.mark.integration
def test_permission_denial_does_not_execute() -> None:
    called = {"n": 0}
    gw = ToolGateway(AuditService(InMemoryAuditRepository()))

    async def handler(actor, args, ctx):
        called["n"] += 1
        return "done"

    # cashback_reconcile requires approval (L4) -> not executed without `approved`.
    gw.register_handler("cashback_reconcile", handler)
    state = AgentState(
        actor=ActorContext(actor_id="o", roles=["ops"], environment=Environment.DEV),
        messages=[
            ChatMessage(
                role="assistant",
                tool_calls=[
                    FunctionCall(
                        name="cashback_reconcile",
                        arguments='{"dry_run": true}',
                        id="c2",
                    )
                ],
            )
        ],
    )

    delta = asyncio.run(tool_node(state, gw))
    assert called["n"] == 0  # handler never ran
    assert delta["tool_results"][0].status.value == "approval_required"
    # deferral still surfaced as a tool message so the model sees it.
    assert delta["messages"][0].role == "tool"
