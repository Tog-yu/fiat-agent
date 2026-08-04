"""I5 integration test: Fiat MCP adapter (DEV_SPEC §I5).

Asserts that the adapter exposes the fiat.* tools and that every call is routed
through fiat-agent's permission (RBAC ``can_execute``) and audit trail — i.e. it
does not bypass the core authorization/audit layer.

The test drives the core :func:`dispatch` with an injected fake context (no real
LLM / MCP server / RAG subprocess), and verifies:
  * a permitted call returns success AND is recorded in the audit trail,
  * a denied call (role not allowed) returns an error with a policy reason AND
    is still recorded in the audit trail.

Run with: ``pytest -q tests/integration/test_fiat_mcp_adapter.py``
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from adapters.claude_code_mcp import server as mcp_server
from fiat_agent.audit.service import AuditService
from fiat_agent.schemas.common import ActorContext, Environment
from fiat_agent.tool_gateway.gateway import ToolGateway


class _FakeHandler:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[tuple[ActorContext, dict]] = []

    async def __call__(self, actor: ActorContext, args: dict, ctx: Any) -> dict:
        self.calls.append((actor, args))
        return {"answer": f"{self.name}:ok"}


@pytest.fixture()
def fake_context():
    audit = AuditService()
    gateway = ToolGateway(audit)
    handler = _FakeHandler("rag_query")
    gateway.register_handler("rag_query", handler)
    gateway.register_handler("alert_diagnosis", _FakeHandler("alert_diagnosis"))
    ctx = mcp_server.FiatMcpContext(gateway=gateway, audit=audit)
    mcp_server._context = ctx
    yield ctx, audit, handler
    mcp_server._context = None


@pytest.mark.integration
def test_tool_mapping_and_exposure(fake_context) -> None:
    # The external tool names are registered on the FastMCP server.
    registered = {t.name for t in mcp_server.mcp._tool_manager.list_tools()}
    assert "fiat.rag_search" in registered
    assert "fiat.alert_diagnose" in registered


@pytest.mark.integration
def test_permitted_call_goes_through_audit(fake_context) -> None:
    ctx, audit, handler = fake_context
    actor = ActorContext(actor_id="ou_alice", roles=["oncall"], environment=Environment.DEV)
    result = asyncio.run(
        mcp_server.dispatch("fiat.rag_search", {"query": "refund policy"}, actor)
    )
    assert result["status"] == "success"
    assert result["tool"] == "rag_query"
    assert handler.calls, "real handler must have executed"
    # Audit trail recorded the tool call.
    events = asyncio.run(audit._repo.list(limit=1000))
    assert any(e.type == "tool_call" and e.tool_name == "rag_query" for e in events)


@pytest.mark.integration
def test_denied_call_still_audited(fake_context) -> None:
    ctx, audit, handler = fake_context
    # viewer is not allowed for es_query (policy: oncall/ops only) -> denied.
    actor = ActorContext(actor_id="ou_bob", roles=["viewer"], environment=Environment.DEV)
    result = asyncio.run(mcp_server.dispatch("fiat.es_query", {"query": "*"}, actor))
    assert result["status"] == "error"
    assert "not permitted" in (result["error"] or "")
    # Even a denied call is written to the audit trail.
    events = asyncio.run(audit._repo.list(limit=1000))
    assert any(e.type == "tool_call" and e.tool_name == "es_query" for e in events)
    assert handler.calls == []  # handler must NOT run when denied


@pytest.mark.integration
def test_unknown_tool_errors(fake_context) -> None:
    ctx, audit, handler = fake_context
    actor = ActorContext(actor_id="x", roles=["oncall"], environment=Environment.DEV)
    result = asyncio.run(mcp_server.dispatch("fiat.nope", {}, actor))
    assert result["status"] == "error"
    assert result["tool"] is None
