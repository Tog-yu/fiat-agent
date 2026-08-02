"""B4 unit test: deterministic can_execute / filter_tools (DEV_SPEC B4)."""

from __future__ import annotations

import pytest

from fiat_agent.auth.policy import can_execute, filter_tools
from fiat_agent.schemas.common import ActorContext, Environment
from fiat_agent.tools.schemas import ToolDefinition


def _actor(roles, env=Environment.DEV):
    return ActorContext(actor_id="u", roles=roles, environment=env)


@pytest.mark.unit
def test_ops_cashback_dryrun_requires_approval():
    d = can_execute(_actor(["ops"], Environment.DEV), "cashback_reconcile")
    assert d.allowed is True
    assert d.approval_required is True


@pytest.mark.unit
def test_ops_cashback_denied_in_prod_env():
    d = can_execute(_actor(["ops"], Environment.PROD), "cashback_reconcile")
    assert d.allowed is False
    assert "environment" in d.reason.lower()


@pytest.mark.unit
def test_oncall_es_allowed_no_approval():
    d = can_execute(_actor(["oncall"], Environment.PROD), "es_query")
    assert d.allowed is True
    assert d.approval_required is False


@pytest.mark.unit
def test_unknown_tool_denied_with_reason():
    d = can_execute(_actor(["ops"], Environment.DEV), "nonexistent_tool")
    assert d.allowed is False
    assert d.reason  # reason always provided


@pytest.mark.unit
def test_high_risk_returns_approval_required():
    # cashback_submit: role not permitted at all
    d = can_execute(_actor(["ops"], Environment.STAGING), "cashback_submit")
    assert d.allowed is False
    # a permitted high-risk tool still requires approval
    d2 = can_execute(_actor(["ops"], Environment.DEV), "cashback_reconcile")
    assert d2.approval_required is True


@pytest.mark.unit
def test_filter_tools_returns_only_allowed():
    actor = _actor(["oncall"], Environment.PROD)
    tools = [
        ToolDefinition(name="es_query"),
        ToolDefinition(name="rag_query"),
        ToolDefinition(name="cashback_submit"),
        ToolDefinition(name="unknown_x"),
    ]
    allowed = filter_tools(actor, tools)
    assert {t.name for t in allowed} == {"es_query", "rag_query"}
