"""Audit service (phase B5, DEV_SPEC B5).

Records tool calls, policy decisions and approval outcomes. Every event is
redacted via :func:`fiat_agent.logging.redact_sensitive` before storage, so
secrets never enter the audit trail.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fiat_agent.audit.repository import (
    AuditEvent,
    AuditRepository,
    InMemoryAuditRepository,
)
from fiat_agent.auth.policy import PolicyDecision
from fiat_agent.logging import redact_sensitive
from fiat_agent.schemas.common import ActorContext


class AuditService:
    def __init__(self, repository: AuditRepository | None = None) -> None:
        self._repo = repository or InMemoryAuditRepository()

    async def record_event(
        self,
        *,
        type: str,
        actor: ActorContext | None = None,
        actor_id: str = "",
        roles: list[str] | None = None,
        environment: str = "",
        tool_name: str | None = None,
        action: str | None = None,
        allowed: bool | None = None,
        reason: str | None = None,
        risk_level: str | None = None,
        metadata: dict | None = None,
    ) -> AuditEvent:
        if actor is not None:
            actor_id = actor.actor_id
            roles = actor.roles
            environment = actor.environment.value
        event = AuditEvent(
            id=uuid4().hex,
            timestamp=datetime.now(timezone.utc),
            type=type,
            actor_id=actor_id,
            roles=roles or [],
            environment=environment,
            tool_name=tool_name,
            action=action,
            allowed=allowed,
            reason=reason,
            risk_level=risk_level,
            metadata=redact_sensitive(metadata or {}),
        )
        await self._repo.add(event)
        return event

    async def record_tool_call(
        self,
        actor: ActorContext,
        tool_name: str,
        arguments: dict,
        *,
        result: dict | None = None,
        decision: PolicyDecision | None = None,
    ) -> AuditEvent:
        risk = decision.risk_level.value if decision and decision.risk_level else None
        return await self.record_event(
            type="tool_call",
            actor=actor,
            tool_name=tool_name,
            action="execute",
            allowed=decision.allowed if decision else None,
            reason=decision.reason if decision else None,
            risk_level=risk,
            metadata={"arguments": arguments, "result": result},
        )

    async def record_policy_decision(
        self, actor: ActorContext, tool_name: str, decision: PolicyDecision
    ) -> AuditEvent:
        return await self.record_event(
            type="policy_decision",
            actor=actor,
            tool_name=tool_name,
            allowed=decision.allowed,
            reason=decision.reason,
            risk_level=decision.risk_level.value if decision.risk_level else None,
        )

    async def record_approval(
        self,
        *,
        actor_id: str,
        tool_name: str,
        approval_id: str,
        outcome: str,
        reason: str | None = None,
    ) -> AuditEvent:
        return await self.record_event(
            type="approval",
            actor_id=actor_id,
            tool_name=tool_name,
            action="approval",
            allowed=(outcome == "approved"),
            reason=reason,
            metadata={"approval_id": approval_id, "outcome": outcome},
        )
