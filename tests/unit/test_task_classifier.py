"""G2 unit test: task classifier (DEV_SPEC §G2).

Verifies all five task types are recognized, ambiguous/unknown input is not
force-classified, and the graph node writes task_type onto the state.
"""

from __future__ import annotations

import pytest

from fiat_agent.models.base import ChatMessage
from fiat_agent.orchestrator.nodes.classify import classify_node, classify_task
from fiat_agent.orchestrator.state import AgentState
from fiat_agent.schemas.common import ActorContext, Environment, TaskType


def _actor() -> ActorContext:
    return ActorContext(actor_id="u1", roles=["ops"], environment=Environment.DEV)


@pytest.mark.unit
def test_all_five_types_recognized() -> None:
    cases = {
        TaskType.RAG_QA: "知识库里权限模型是怎么设计的？",
        TaskType.ALERT_DIAGNOSIS: "线上服务报错，帮我诊断一下原因",
        TaskType.TEST_ENV_AUTOMATION: "在测试环境给这个用户开个测试账号并充值",
        TaskType.CASHBACK_RECONCILE: "帮我做一次返现对账 dry-run",
        TaskType.LOGISTICS_VALIDATION: "导入这批卡片的物流状态并校验",
    }
    for expected, prompt in cases.items():
        assert classify_task(prompt) == expected, f"{prompt!r} -> {expected}"


@pytest.mark.unit
def test_unknown_input_returns_none() -> None:
    assert classify_task("今天天气不错") is None
    assert classify_task("") is None
    assert classify_task(None) is None


@pytest.mark.unit
def test_classify_node_sets_task_type() -> None:
    state = AgentState(
        actor=_actor(),
        messages=[
            ChatMessage(role="system", content="you are an agent"),
            ChatMessage(role="user", content="查一下知识库里权限模型怎么设计"),
        ],
    )
    update = classify_node(state)
    assert update["task_type"] == TaskType.RAG_QA


@pytest.mark.unit
def test_classify_node_no_user_message() -> None:
    state = AgentState(actor=_actor(), messages=[ChatMessage(role="system", content="x")])
    assert classify_node(state)["task_type"] is None
