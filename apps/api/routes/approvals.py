"""Approval queue API (DEV_SPEC §J5).

Exposes the human-approval queue so the web console and Lark bot share one
source of truth:

* ``GET    /api/approvals``                  — list approvals (filter by status)
* ``POST   /api/approvals/:id/approve``      — approve (optionally with reason)
* ``POST   /api/approvals/:id/reject``       — reject with reason

The ``params_summary`` returned to the client is a *frozen snapshot* — the page
may display it but must not let the user mutate it before deciding (enforced by
the backend: this route never re-reads client-supplied params).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from apps.api.agent_service import get_approval_service
from apps.api.deps import get_current_actor
from fiat_agent.approvals.service import (
    AlreadyDecidedError,
    ApprovalError,
    ApprovalService,
)
from fiat_agent.schemas.common import ActorContext

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


class ApprovalView(BaseModel):
    id: str
    requester_id: str
    tool_name: str
    params_summary: dict
    risk_level: str
    environment: str
    status: str
    dual_approval: bool
    first_approver_id: str | None = None
    second_approver_id: str | None = None
    approver_id: str | None = None
    reason: str | None = None
    decided_at: str | None = None


class DecideRequest(BaseModel):
    approver_id: str | None = None
    reason: str | None = None


class DecideResponse(BaseModel):
    id: str
    status: str
    approver_id: str | None = None
    reason: str | None = None


def _view(a) -> ApprovalView:
    return ApprovalView(
        id=a.id,
        requester_id=a.requester_id,
        tool_name=a.tool_name,
        params_summary=a.params_summary,
        risk_level=a.risk_level,
        environment=a.environment,
        status=a.status,
        dual_approval=a.dual_approval,
        first_approver_id=a.first_approver_id,
        second_approver_id=a.second_approver_id,
        approver_id=a.approver_id,
        reason=a.reason,
        decided_at=a.decided_at.isoformat() if a.decided_at is not None else None,
    )


@router.get("", response_model=list[ApprovalView])
async def list_approvals(
    status_filter: str | None = None,
    service: ApprovalService = Depends(get_approval_service),
) -> list[ApprovalView]:
    """Return approvals, optionally filtered by ``status`` (pending/approved/...)."""
    approvals = await service.list(status=status_filter)
    return [_view(a) for a in approvals]


@router.post(
    "/{approval_id}/approve",
    response_model=DecideResponse,
    status_code=status.HTTP_200_OK,
)
async def approve(
    approval_id: str,
    req: DecideRequest,
    actor: ActorContext = Depends(get_current_actor),
    service: ApprovalService = Depends(get_approval_service),
) -> DecideResponse:
    """Approve a pending approval. The frozen ``params_summary`` is never read back."""
    approver = req.approver_id or actor.actor_id
    try:
        a = await service.approve(approval_id, approver)
    except AlreadyDecidedError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from None
    except ApprovalError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from None
    return DecideResponse(id=a.id, status=a.status, approver_id=a.approver_id, reason=a.reason)


@router.post(
    "/{approval_id}/reject",
    response_model=DecideResponse,
    status_code=status.HTTP_200_OK,
)
async def reject(
    approval_id: str,
    req: DecideRequest,
    actor: ActorContext = Depends(get_current_actor),
    service: ApprovalService = Depends(get_approval_service),
) -> DecideResponse:
    """Reject a pending approval."""
    approver = req.approver_id or actor.actor_id
    try:
        a = await service.reject(approval_id, approver, reason=req.reason)
    except AlreadyDecidedError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from None
    except ApprovalError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from None
    return DecideResponse(id=a.id, status=a.status, approver_id=a.approver_id, reason=a.reason)
