"""B6 unit test: approval immutability + L5 dual approval (DEV_SPEC B6)."""

from __future__ import annotations

import asyncio

import pytest

from fiat_agent.approvals.service import (
    AlreadyDecidedError,
    ApprovalService,
    InMemoryApprovalRepository,
)
from fiat_agent.schemas.common import Environment, RiskLevel


@pytest.mark.unit
def test_single_approval_and_immutable_params() -> None:
    async def _run() -> None:
        svc = ApprovalService(InMemoryApprovalRepository())
        params = {"collection": "cashback", "amount": 100}
        ap = await svc.request(
            requester_id="u1",
            tool_name="cashback_reconcile",
            params_summary=params,
            risk_level=RiskLevel.L4,
            environment="staging",
        )
        approved = await svc.approve(ap.id, "lead1")
        assert approved.status == "approved"
        # params snapshot is frozen
        assert approved.params_summary == {"collection": "cashback", "amount": 100}
        # double approve rejected
        with pytest.raises(AlreadyDecidedError):
            await svc.approve(ap.id, "lead2")

    asyncio.run(_run())


@pytest.mark.unit
def test_l5_requires_two_distinct_approvers() -> None:
    async def _run() -> None:
        svc = ApprovalService(InMemoryApprovalRepository())
        ap = await svc.request(
            requester_id="u1",
            tool_name="cashback_submit",
            params_summary={"amount": 5000},
            risk_level=RiskLevel.L5,
            environment="prod",
        )
        assert ap.dual_approval is True
        # first approval keeps it pending
        after_first = await svc.approve(ap.id, "lead1")
        assert after_first.status == "pending"
        # same approver again -> error
        with pytest.raises(Exception):
            await svc.approve(ap.id, "lead1")
        # second distinct approver -> approved
        after_second = await svc.approve(ap.id, "lead2")
        assert after_second.status == "approved"

    asyncio.run(_run())


@pytest.mark.unit
def test_reject_then_immutable() -> None:
    async def _run() -> None:
        svc = ApprovalService(InMemoryApprovalRepository())
        ap = await svc.request(
            requester_id="u1",
            tool_name="cashback_reconcile",
            params_summary={"x": 1},
            risk_level=RiskLevel.L3,
            environment="dev",
        )
        rejected = await svc.reject(ap.id, "lead1", reason="not justified")
        assert rejected.status == "rejected"
        assert rejected.reason == "not justified"
        with pytest.raises(AlreadyDecidedError):
            await svc.approve(ap.id, "lead2")

    asyncio.run(_run())
