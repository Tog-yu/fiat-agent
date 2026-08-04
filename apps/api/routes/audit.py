"""Audit query API (DEV_SPEC §J6).

Exposes the audit trail with optional filters so the web console can drill down
by user, tool, risk level, event type and time window:

* ``GET /api/audit`` — list/filter audit events (newest first)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from apps.api.agent_service import get_audit_service
from fiat_agent.audit.service import AuditService

router = APIRouter(prefix="/api/audit", tags=["audit"])


class AuditEventView(BaseModel):
    id: str
    timestamp: str
    type: str
    actor_id: str
    roles: list[str]
    environment: str
    tool_name: str | None = None
    action: str | None = None
    allowed: bool | None = None
    reason: str | None = None
    risk_level: str | None = None
    metadata: dict


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        # Accept ISO-8601 (with or without trailing Z).
        s = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无效的时间参数: {value} ({e})",
        ) from None


@router.get("", response_model=list[AuditEventView])
async def list_audit(
    actor_id: Optional[str] = None,
    tool_name: Optional[str] = None,
    risk_level: Optional[str] = None,
    type: Optional[str] = None,
    from_ts: Optional[str] = None,
    to_ts: Optional[str] = None,
    limit: int = 200,
    service: AuditService = Depends(get_audit_service),
) -> list[AuditEventView]:
    """Return audit events filtered by the supplied criteria (newest first)."""
    events = await service.query(
        actor_id=actor_id,
        tool_name=tool_name,
        risk_level=risk_level,
        type=type,
        from_ts=_parse_ts(from_ts),
        to_ts=_parse_ts(to_ts),
        limit=min(max(limit, 1), 1000),
    )
    return [
        AuditEventView(
            id=e.id,
            timestamp=e.timestamp.isoformat(),
            type=e.type,
            actor_id=e.actor_id,
            roles=e.roles,
            environment=e.environment,
            tool_name=e.tool_name,
            action=e.action,
            allowed=e.allowed,
            reason=e.reason,
            risk_level=e.risk_level,
            metadata=e.metadata,
        )
        for e in events
    ]
