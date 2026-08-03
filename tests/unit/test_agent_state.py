"""G1 unit test: AgentState (DEV_SPEC §G1).

Verifies the state carries the six required concepts (actor, session, messages,
task_type, tool_results, approval_state) with sensible defaults and remains
JSON-serializable for session persistence.
"""

from __future__ import annotations

import json

import pytest

from fiat_agent.models.base import ChatMessage
from fiat_agent.orchestrator.state import AgentState, ApprovalState
from fiat_agent.schemas.agent import ToolResult, ToolStatus
from fiat_agent.schemas.common import ActorContext, Environment, TaskType


def _actor() -> ActorContext:
    return ActorContext(actor_id="u1", roles=["ops"], environment=Environment.DEV)


@pytest.mark.unit
def test_required_fields_present_with_defaults() -> None:
    state = AgentState(actor=_actor())
    # the six required concepts exist.
    assert isinstance(state.actor, ActorContext)
    assert state.session_id == ""
    assert state.messages == []
    assert state.task_type is None
    assert state.tool_results == []
    assert state.approval_state == ApprovalState.NOT_REQUIRED


@pytest.mark.unit
def test_populated_state_roundtrips() -> None:
    state = AgentState(
        actor=_actor(),
        session_id="sess-9",
        messages=[ChatMessage(role="user", content="查告警")],
        task_type=TaskType.ALERT_DIAGNOSIS,
        tool_results=[
            ToolResult(tool_name="es_query", status=ToolStatus.SUCCESS, data={"hits": 3})
        ],
        approval_state=ApprovalState.PENDING,
    )
    assert state.task_type == TaskType.ALERT_DIAGNOSIS
    assert len(state.messages) == 1
    assert state.tool_results[0].tool_name == "es_query"

    # JSON-serializable (session event store / export).
    dumped = state.model_dump()
    payload = json.dumps(dumped, default=str)
    assert isinstance(payload, str)
    assert dumped["task_type"] == "alert_diagnosis"
    assert dumped["approval_state"] == "pending"
