"""G7 unit test: final-answer node (DEV_SPEC §G7).

Verifies fixed output formats per task type and that RAG citations are kept.
"""

from __future__ import annotations

import pytest

from fiat_agent.orchestrator.nodes.final import final_node
from fiat_agent.orchestrator.state import AgentState
from fiat_agent.rag.citations import Citation
from fiat_agent.rag.context_merge import MergedRagContext
from fiat_agent.schemas.agent import ToolResult, ToolStatus
from fiat_agent.schemas.common import ActorContext, Environment, TaskType


def _actor() -> ActorContext:
    return ActorContext(actor_id="u", roles=["ops"], environment=Environment.DEV)


@pytest.mark.unit
def test_rag_answer_preserves_citations() -> None:
    rag = MergedRagContext(
        query="q",
        answer="返现 T+1 到账。",
        citations=[Citation(collection="kb", doc_id="d1", chunk_id="c1", source="返现手册")],
    )
    state = AgentState(actor=_actor(), task_type=TaskType.RAG_QA)
    answer = final_node(state, rag_context=rag)["final_answer"]

    assert "【知识库问答】" in answer
    assert "返现 T+1 到账。" in answer
    # citations preserved (Sources + source label).
    assert "Sources:" in answer
    assert "返现手册" in answer


@pytest.mark.unit
def test_alert_format_fixed() -> None:
    state = AgentState(
        actor=_actor(),
        task_type=TaskType.ALERT_DIAGNOSIS,
        tool_results=[
            ToolResult(tool_name="es_query", status=ToolStatus.SUCCESS, data={"hits": 3})
        ],
    )
    answer = final_node(state)["final_answer"]
    assert "【告警诊断】" in answer
    assert "es_query" in answer


@pytest.mark.unit
def test_dry_run_format_for_reconcile() -> None:
    state = AgentState(
        actor=_actor(),
        task_type=TaskType.CASHBACK_RECONCILE,
        tool_results=[
            ToolResult(tool_name="db_query", status=ToolStatus.SUCCESS, data={"rows": 10})
        ],
    )
    answer = final_node(state)["final_answer"]
    assert "Dry-run 报告" in answer
    assert "未执行任何写操作" in answer
    assert "db_query" in answer
