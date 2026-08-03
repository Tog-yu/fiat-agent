"""G3 unit test: context builder (DEV_SPEC §G3).

Verifies:
  1. only permission-allowed tools are exposed in tool_schemas;
  2. RAG results enter the context with their citations attached;
  3. the graph node writes system_prompt + filtered tool_schemas onto state.
"""

from __future__ import annotations

import pytest

from fiat_agent.context.builder import BuiltContext, ContextBuilder
from fiat_agent.orchestrator.nodes.build_context import build_context_node
from fiat_agent.orchestrator.state import AgentState
from fiat_agent.rag.citations import Citation
from fiat_agent.rag.context_merge import MergedRagContext
from fiat_agent.schemas.common import ActorContext, Environment, RiskLevel, TaskType
from fiat_agent.tools.registry import ToolRegistry
from fiat_agent.tools.schemas import ToolDefinition


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register_tools(
        [
            ToolDefinition(name="es_query", risk_level=RiskLevel.L2),
            ToolDefinition(name="rag_query", risk_level=RiskLevel.L1),
        ]
    )
    return reg


def _viewer() -> ActorContext:
    return ActorContext(actor_id="v", roles=["viewer"], environment=Environment.DEV)


def _ops() -> ActorContext:
    return ActorContext(actor_id="o", roles=["ops"], environment=Environment.DEV)


@pytest.mark.unit
def test_only_allowed_tools_exposed() -> None:
    builder = ContextBuilder()
    schemas = builder.build_tool_schemas(_viewer(), _registry())
    names = [s["function"]["name"] for s in schemas]
    # viewer may use rag_query but NOT es_query (needs oncall/ops).
    assert "rag_query" in names
    assert "es_query" not in names

    # ops sees both.
    names_ops = [s["function"]["name"] for s in builder.build_tool_schemas(_ops(), _registry())]
    assert set(names_ops) == {"es_query", "rag_query"}


@pytest.mark.unit
def test_rag_context_carries_citations() -> None:
    merged = MergedRagContext(
        query="返现规则?",
        answer="返现 T+1 到账。",
        citations=[
            Citation(collection="kb", doc_id="d1", chunk_id="c1", source="返现手册"),
        ],
    )
    builder = ContextBuilder()
    ctx: BuiltContext = builder.build(
        _viewer(), _registry(), task_type=TaskType.RAG_QA, rag_context=merged
    )
    assert "返现 T+1 到账。" in ctx.rag_context
    # citations attached (Sources + provenance).
    assert "Sources:" in ctx.rag_context
    assert "返现手册" in ctx.rag_context
    assert "collection=kb" in ctx.rag_context


@pytest.mark.unit
def test_node_writes_state_delta() -> None:
    state = AgentState(actor=_viewer(), task_type=TaskType.RAG_QA)
    delta = build_context_node(state, _registry())
    assert isinstance(delta["system_prompt"], str) and delta["system_prompt"]
    names = [s["function"]["name"] for s in delta["tool_schemas"]]
    assert names == ["rag_query"]
    # task type is reflected in the system prompt.
    assert "rag_qa" in delta["system_prompt"]
