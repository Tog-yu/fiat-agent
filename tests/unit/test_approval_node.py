"""G6 unit test: approval-gating node (DEV_SPEC §G6).

Verifies L4/L5 (or approval-required) tools are flagged for human approval,
``approval_state`` becomes PENDING, and an ``approval_requested`` session event
is written; low-risk-only runs stay NOT_REQUIRED with no event.
"""

from __future__ import annotations

import asyncio

import pytest

from fiat_agent.models.base import ChatMessage, FunctionCall
from fiat_agent.orchestrator.nodes.approval import approval_node
from fiat_agent.orchestrator.state import AgentState, ApprovalState
from fiat_agent.schemas.common import ActorContext, Environment


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def record_event(self, **kwargs) -> None:
        self.events.append(kwargs)


def _actor() -> ActorContext:
    return ActorContext(actor_id="o", roles=["ops"], environment=Environment.DEV)


@pytest.mark.unit
def test_high_risk_tool_requests_approval_and_writes_event() -> None:
    state = AgentState(
        actor=_actor(),
        messages=[
            ChatMessage(
                role="assistant",
                tool_calls=[FunctionCall(name="cashback_reconcile", arguments="{}", id="x")],
            )
        ],
    )
    audit = FakeAudit()
    delta = asyncio.run(approval_node(state, audit_service=audit))

    assert delta["approval_state"] == ApprovalState.PENDING
    assert delta["pending_approvals"] == ["cashback_reconcile"]
    # approval_requested event written to session.
    assert len(audit.events) == 1
    assert audit.events[0]["type"] == "approval_requested"
    assert "cashback_reconcile" in audit.events[0]["tool_name"]


@pytest.mark.unit
def test_low_risk_only_needs_no_approval() -> None:
    state = AgentState(
        actor=_actor(),
        messages=[
            ChatMessage(
                role="assistant",
                tool_calls=[FunctionCall(name="es_query", arguments="{}", id="y")],
            )
        ],
    )
    audit = FakeAudit()
    delta = asyncio.run(approval_node(state, audit_service=audit))

    assert delta["approval_state"] == ApprovalState.NOT_REQUIRED
    assert delta["pending_approvals"] == []
    assert audit.events == []


@pytest.mark.unit
def test_plan_required_tools_also_flagged() -> None:
    # plan not yet in messages; node reads required_tools from the plan object.
    state = AgentState(actor=_actor())
    plan = type("P", (), {"required_tools": ["db_query", "cashback_submit"]})()
    audit = FakeAudit()
    delta = asyncio.run(approval_node(state, plan=plan, audit_service=audit))

    assert delta["approval_state"] == ApprovalState.PENDING
    assert "cashback_submit" in delta["pending_approvals"]
    assert "db_query" not in delta["pending_approvals"]
