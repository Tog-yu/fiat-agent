"""G4 unit test: planning node (DEV_SPEC §G4).

Verifies the plan output carries steps/required_tools/risk_level/need_approval,
and that malformed plans trigger retry while tool-mismatched plans degrade.
"""

from __future__ import annotations

import pytest  # noqa: F401  (kept for consistency / future marks)

from fiat_agent.orchestrator.nodes.plan import (
    PlanStatus,
    PlanningResult,
    plan_node,
    validate_plan,
)
from fiat_agent.orchestrator.state import AgentState
from fiat_agent.schemas.common import ActorContext, Environment, RiskLevel, TaskType


def _state() -> AgentState:
    return AgentState(
        actor=ActorContext(actor_id="u", roles=["ops"], environment=Environment.DEV),
        task_type=TaskType.CASHBACK_RECONCILE,
    )


def _valid_planner(_state):
    return {
        "steps": ["核对流水", "生成对账报告"],
        "required_tools": ["db_query", "cashback_reconcile"],
        "risk_level": "L4",
        "need_approval": True,
    }


@pytest.mark.unit
def test_valid_plan_ok_and_fields_present() -> None:
    delta = plan_node(_state(), _valid_planner)
    assert delta["plan_status"] == PlanStatus.OK
    plan: PlanningResult = delta["plan"]
    assert plan.steps and isinstance(plan.steps, list)
    assert plan.required_tools == ["db_query", "cashback_reconcile"]
    assert plan.risk_level == RiskLevel.L4
    assert plan.need_approval is True


@pytest.mark.unit
def test_invalid_plan_triggers_retry() -> None:
    # missing steps -> structurally invalid.
    def bad(_s):
        return {"required_tools": ["db_query"], "risk_level": "L1", "need_approval": False}

    delta = plan_node(_state(), bad)
    assert delta["plan_status"] == PlanStatus.RETRY
    assert delta["plan"] is None

    # non-list required_tools also invalid.
    def bad2(_s):
        return {"steps": ["x"], "required_tools": "db_query", "risk_level": "L1"}

    assert plan_node(_state(), bad2)["plan_status"] == PlanStatus.RETRY
    assert validate_plan({"steps": []}) is None  # empty steps invalid


@pytest.mark.unit
def test_tool_mismatch_degrades_to_safe_subset() -> None:
    def planner(_s):
        return {
            "steps": ["核对", "提交"],
            "required_tools": ["db_query", "forbidden_tool"],
            "risk_level": "L2",
            "need_approval": False,
        }

    delta = plan_node(_state(), planner, available_tools={"db_query", "es_query"})
    assert delta["plan_status"] == PlanStatus.DEGRADED
    assert delta["plan"].required_tools == ["db_query"]


@pytest.mark.unit
def test_all_unknown_tools_retry() -> None:
    def planner(_s):
        return {
            "steps": ["x"],
            "required_tools": ["nope"],
            "risk_level": "L1",
            "need_approval": False,
        }

    delta = plan_node(_state(), planner, available_tools={"db_query"})
    assert delta["plan_status"] == PlanStatus.RETRY
