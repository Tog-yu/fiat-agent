"""F3 unit test: ToolGateway (DEV_SPEC §F3).

Covers the acceptance criteria:
  1. `can_execute` is called *before* execution (denied calls never reach a
     handler);
  2. after execution a `tool_calls` record and an `audit_logs` event are written;
  3. failures are normalized into the unified `ToolResult` error structure
     (no raw exceptions escape).

Business tool handlers (F4-F7) do not exist yet, so handlers are registered as
fakes — keeping the gateway decoupled and hermetic.
"""

from __future__ import annotations

import asyncio

import pytest

from fiat_agent.audit.repository import InMemoryAuditRepository
from fiat_agent.audit.service import AuditService
from fiat_agent.schemas.common import ActorContext, Environment
from fiat_agent.tools.function_calling import ToolResultStatus
from fiat_agent.tool_gateway.gateway import ToolGateway


def _gw() -> ToolGateway:
    return ToolGateway(AuditService(InMemoryAuditRepository()))


def _ops_dev() -> ActorContext:
    return ActorContext(actor_id="ops1", roles=["ops"], environment=Environment.DEV)


def _viewer_dev() -> ActorContext:
    return ActorContext(actor_id="vw1", roles=["viewer"], environment=Environment.DEV)


@pytest.mark.unit
def test_denied_call_never_reaches_handler() -> None:
    gw = _gw()
    called = {"n": 0}

    async def handler(actor, args, ctx):  # pragma: no cover - must not run
        called["n"] += 1
        return "should-not-run"

    gw.register_handler("es_query", handler)

    # viewer cannot use es_query (needs oncall/ops) -> denied by policy.
    result = asyncio.run(gw.execute_tool(_viewer_dev(), "es_query", {}))

    assert result.status == ToolResultStatus.ERROR
    assert "not permitted" in (result.error or "")
    assert called["n"] == 0  # handler never executed

    # audit + tool_calls still recorded for the denied attempt.
    assert len(gw.tool_calls) == 1
    assert gw.tool_calls[0].status == "error"
    assert any(e.type == "tool_call" for e in gw._audit._repo._events)


@pytest.mark.unit
def test_success_writes_tool_call_and_audit() -> None:
    gw = _gw()

    async def handler(actor, args, ctx):
        return {"hits": 3, "top": "cpu_spike"}

    gw.register_handler("es_query", handler)

    result = asyncio.run(gw.execute_tool(_ops_dev(), "es_query", {"index": "logs"}))

    assert result.status == ToolResultStatus.SUCCESS
    assert "hits" in (result.content or "")
    # tool_calls record + audit_logs event both present.
    assert len(gw.tool_calls) == 1
    rec = gw.tool_calls[0]
    assert rec.tool_name == "es_query"
    assert rec.status == "success"
    assert rec.arguments == {"index": "logs"}
    events = [e for e in gw._audit._repo._events if e.type == "tool_call"]
    assert len(events) == 1
    assert events[0].tool_name == "es_query"


@pytest.mark.unit
def test_execution_error_normalized() -> None:
    gw = _gw()

    async def handler(actor, args, ctx):
        raise ValueError("boom: index missing")

    gw.register_handler("es_query", handler)

    result = asyncio.run(gw.execute_tool(_ops_dev(), "es_query", {}))

    # unified error structure, not a raised exception.
    assert result.status == ToolResultStatus.ERROR
    assert result.error == "boom: index missing"
    # still logged.
    assert len(gw.tool_calls) == 1
    assert gw.tool_calls[0].status == "error"
    assert gw.tool_calls[0].error == "boom: index missing"


@pytest.mark.unit
def test_approval_gating_defers_without_approval() -> None:
    gw = _gw()
    called = {"n": 0}

    async def handler(actor, args, ctx):
        called["n"] += 1
        return "submitted"

    # cashback_reconcile requires approval (L4, approval_required).
    gw.register_handler("cashback_reconcile", handler)

    # Without approval -> deferred (no execution).
    deferred = asyncio.run(
        gw.execute_tool(_ops_dev(), "cashback_reconcile", {"dry_run": True})
    )
    assert deferred.status == ToolResultStatus.PENDING_APPROVAL
    assert called["n"] == 0

    # With approval -> executes.
    approved = asyncio.run(
        gw.execute_tool(
            _ops_dev(), "cashback_reconcile", {"dry_run": True}, approved=True
        )
    )
    assert approved.status == ToolResultStatus.SUCCESS
    assert called["n"] == 1
