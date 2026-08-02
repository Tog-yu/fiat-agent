"""Permission check API (phase B7, DEV_SPEC B7).

Wraps the deterministic ``can_execute`` from the auth policy service.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from apps.api.deps import get_current_actor
from fiat_agent.auth.policy import can_execute
from fiat_agent.schemas.common import ActorContext


class AuthCheckRequest(BaseModel):
    tool_name: str
    environment: str | None = None
    action: str | None = None


class AuthCheckResponse(BaseModel):
    allowed: bool
    reason: str
    approval_required: bool
    risk_level: str | None = None


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/check", response_model=AuthCheckResponse)
def auth_check(
    req: AuthCheckRequest,
    actor: ActorContext = Depends(get_current_actor),
) -> AuthCheckResponse:
    decision = can_execute(
        actor, req.tool_name, environment=req.environment, action=req.action
    )
    return AuthCheckResponse(
        allowed=decision.allowed,
        reason=decision.reason,
        approval_required=decision.approval_required,
        risk_level=decision.risk_level.value if decision.risk_level else None,
    )
