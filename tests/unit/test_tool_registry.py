"""F2 unit test: ToolRegistry (DEV_SPEC §F2).

Covers the three acceptance criteria:
  1. tool names must be unique (registering a duplicate raises);
  2. tools can be filtered by role and environment (delegates to the
     deterministic auth policy);
  3. local business tools and MCP-derived tools merge into one registry while
     preserving uniqueness.
"""

from __future__ import annotations

import pytest

from fiat_agent.schemas.common import ActorContext, Environment, RiskLevel
from fiat_agent.tools.registry import DuplicateToolNameError, ToolRegistry
from fiat_agent.tools.schemas import ToolDefinition


def _tool(name: str, risk: RiskLevel = RiskLevel.L1) -> ToolDefinition:
    return ToolDefinition(name=name, risk_level=risk)


@pytest.mark.unit
def test_duplicate_names_rejected() -> None:
    reg = ToolRegistry()
    reg.register(_tool("es_query"))
    with pytest.raises(DuplicateToolNameError):
        reg.register(_tool("es_query"))
    # the first registration survives
    assert reg.by_name("es_query") is not None
    assert len(reg.tools) == 1


@pytest.mark.unit
def test_filter_by_role_and_environment() -> None:
    reg = ToolRegistry()
    # es_query: oncall/ops, all envs; cashback_reconcile: ops/oncall, dev/staging
    # only; rag_query: oncall/ops/viewer, all envs. (from config/tool_policies.yaml)
    reg.register_tools(
        [
            _tool("es_query", RiskLevel.L2),
            _tool("cashback_reconcile", RiskLevel.L4),
            _tool("rag_query", RiskLevel.L1),
        ]
    )

    # ops in prod -> cashback_reconcile denied (staging/prod env mismatch),
    # es_query allowed, rag_query allowed.
    ops_prod = ActorContext(actor_id="u1", roles=["ops"], environment=Environment.PROD)
    allowed = {t.name for t in reg.filter(ops_prod)}
    assert allowed == {"es_query", "rag_query"}
    assert "cashback_reconcile" not in allowed

    # viewer in dev -> only rag_query (es_query/cashback_reconcile need ops/oncall).
    viewer_dev = ActorContext(
        actor_id="u2", roles=["viewer"], environment=Environment.DEV
    )
    allowed = {t.name for t in reg.filter(viewer_dev)}
    assert allowed == {"rag_query"}

    # ops in dev -> everything permitted.
    ops_dev = ActorContext(actor_id="u3", roles=["ops"], environment=Environment.DEV)
    allowed = {t.name for t in reg.filter(ops_dev)}
    assert allowed == {"es_query", "cashback_reconcile", "rag_query"}


@pytest.mark.unit
def test_merge_local_and_mcp_tools() -> None:
    reg = ToolRegistry()
    # local business tools
    reg.register_tools(
        [
            _tool("es_query", RiskLevel.L2),
            _tool("db_query", RiskLevel.L2),
        ]
    )
    # MCP-derived tools (stand-ins for RAG server tools, namespaced apart)
    mcp_tools = [
        _tool("mcp_rag.query_knowledge_hub"),
        _tool("mcp_rag.list_collections"),
    ]
    reg.register_tools(mcp_tools)

    assert len(reg.tools) == 4
    assert set(reg.names()) == {
        "es_query",
        "db_query",
        "mcp_rag.query_knowledge_hub",
        "mcp_rag.list_collections",
    }
    assert reg.by_name("mcp_rag.query_knowledge_hub") is not None

    # a name clash between local and MCP tools is still rejected
    with pytest.raises(DuplicateToolNameError):
        reg.register(_tool("es_query"))
