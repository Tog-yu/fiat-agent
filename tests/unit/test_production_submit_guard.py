"""H8 unit test: production submit guard (DEV_SPEC §H8 / §13.2).

Acceptance pillars:

1. **未审批不能调用 submit** — submit is blocked unless the referenced
   ``Approval`` exists and is ``approved`` (deterministic gate).
2. **MVP 中 submit 默认禁用或 fake** — with the MVP switch off (the default),
   an approved submit yields a *fake* result that writes nothing.

Both the standalone :class:`ProductionSubmitGuard` and the workflow-level
``submit`` reserved interfaces are exercised.
"""

from __future__ import annotations

import asyncio

import pytest

from fiat_agent.approvals.service import (
    ApprovalService,
    InMemoryApprovalRepository,
)
from fiat_agent.audit.repository import InMemoryAuditRepository
from fiat_agent.audit.service import AuditService
from fiat_agent.errors import ApprovalRequiredError
from fiat_agent.schemas.common import ActorContext, Environment, RiskLevel
from fiat_agent.tool_gateway.gateway import ToolGateway
from fiat_agent.tools.registry import ToolRegistry
from fiat_agent.workflows.cashback_reconcile import CashbackReconcileWorkflow
from fiat_agent.workflows.production_submit import ProductionSubmitGuard


@pytest.mark.unit
def _actor(roles=("ops",)) -> ActorContext:
    return ActorContext(actor_id="u1", roles=list(roles), environment=Environment.DEV)


async def _request_and_approve(svc: ApprovalService, tool_name: str = "cashback_submit"):
    approval = await svc.request(
        requester_id="u1",
        tool_name=tool_name,
        params_summary={"file_path": "x.csv"},
        risk_level=RiskLevel.L4,
        environment="dev",
    )
    return await svc.approve(approval.id, "approver1")


@pytest.mark.unit
def test_submit_without_approval_is_blocked():
    """No such approval -> blocked before any write."""
    svc = ApprovalService(InMemoryApprovalRepository())
    guard = ProductionSubmitGuard(svc)  # MVP disabled by default
    with pytest.raises(ApprovalRequiredError):
        asyncio.run(guard.submit("does-not-exist", _actor()))


@pytest.mark.unit
def test_submit_with_pending_approval_is_blocked():
    """Approval exists but is not approved -> still blocked."""
    svc = ApprovalService(InMemoryApprovalRepository())
    guard = ProductionSubmitGuard(svc)
    approval = asyncio.run(
        svc.request(
            requester_id="u1",
            tool_name="cashback_submit",
            params_summary={"file": "x"},
            risk_level=RiskLevel.L4,
            environment="dev",
        )
    )
    with pytest.raises(ApprovalRequiredError):
        asyncio.run(guard.submit(approval.id, _actor()))


@pytest.mark.unit
def test_submit_mvp_disabled_is_fake():
    """Approved, but MVP disabled -> safe fake stub (no real write)."""
    svc = ApprovalService(InMemoryApprovalRepository())
    guard = ProductionSubmitGuard(svc, production_submit_enabled=False)
    approval = asyncio.run(_request_and_approve(svc))

    result = asyncio.run(
        guard.submit(approval.id, _actor(), params={"file": "x.csv"})
    )

    assert result["approved"] is True
    assert result["submitted"] is False
    assert result["fake"] is True
    assert result["approval_id"] == approval.id


@pytest.mark.unit
def test_submit_enabled_invokes_real_handler():
    """Approved + enabled + handler -> real production write runs once."""
    svc = ApprovalService(InMemoryApprovalRepository())
    guard = ProductionSubmitGuard(svc, production_submit_enabled=True)
    approval = asyncio.run(_request_and_approve(svc))
    calls = {"n": 0}

    async def do_submit(actor, appr, params):
        calls["n"] += 1
        return {"records_written": 3}

    result = asyncio.run(
        guard.submit(
            approval.id, _actor(), params={"file": "x"}, do_submit=do_submit
        )
    )

    assert calls["n"] == 1
    assert result["submitted"] is True
    assert result["fake"] is False
    assert result["records_written"] == 3


@pytest.mark.unit
def test_submit_enabled_without_handler_is_blocked():
    """Enabled but no submit handler provided -> still safe (no write)."""
    svc = ApprovalService(InMemoryApprovalRepository())
    guard = ProductionSubmitGuard(svc, production_submit_enabled=True)
    approval = asyncio.run(_request_and_approve(svc))
    with pytest.raises(ApprovalRequiredError):
        asyncio.run(guard.submit(approval.id, _actor()))


@pytest.mark.unit
def test_workflow_submit_interface_gated_on_approval():
    """H8: the workflow-level submit reserves the interface and gates on approval."""
    audit = AuditService(InMemoryAuditRepository())
    registry = ToolRegistry()
    gateway = ToolGateway(audit)
    wf = CashbackReconcileWorkflow(
        registry=registry,
        gateway=gateway,
        model_gateway=None,
        audit_service=audit,
    )
    guard = ProductionSubmitGuard(ApprovalService(InMemoryApprovalRepository()))

    # No approval -> blocked, even in the MVP (default disabled) configuration.
    with pytest.raises(ApprovalRequiredError):
        asyncio.run(wf.submit("nope", _actor(), guard))
