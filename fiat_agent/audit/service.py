"""Audit service (phase B5, DEV_SPEC B5).

Records tool calls, policy decisions and approval outcomes. Every event is
redacted via :func:`fiat_agent.logging.redact_sensitive` before storage, so
secrets never enter the audit trail.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from fiat_agent.audit.repository import (
    AuditEvent,
    AuditRepository,
    InMemoryAuditRepository,
)
from fiat_agent.auth.policy import PolicyDecision
from fiat_agent.logging import redact_sensitive
from fiat_agent.models.base import TokenUsage
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

    async def record_model_usage(
        self,
        *,
        task_type: Optional[str],
        model: str,
        usage: TokenUsage,
        session_id: Optional[str] = None,
    ) -> AuditEvent:
        """Record a single model-call token usage (DEV_SPEC D6).

        Emitted by :class:`~fiat_agent.models.gateway.ModelGateway` via its
        ``audit_sink`` on every chat/stream call. Stored under the ``model_usage``
        event type so it can later be aggregated per task.

        ``usage`` is serialized via ``model_dump()``; its keys (``prompt_tokens``,
        ``completion_tokens``, ``total_tokens``) are not in ``SENSITIVE_KEYS``, so
        :func:`fiat_agent.logging.redact_sensitive` leaves the values intact.
        """
        return await self.record_event(
            type="model_usage",
            tool_name=model,
            action="chat",
            metadata={
                "task_type": task_type,
                "model": model,
                "session_id": session_id,
                "usage": usage.model_dump(),
            },
        )

    async def record_trace(
        self,
        *,
        session_id: str,
        actor_id: str = "",
        round: int,
        step: str,
        node: str,
        status: str,
        detail: dict | None = None,
    ) -> AuditEvent:
        """Record one step of an agent execution trace (DEV_SPEC §K3).

        The orchestrator emits one trace entry per node invocation with its
        ``round`` (ReAct loop index), ``step`` category (``plan`` /
        ``model_call`` / ``tool_call`` / ``final`` / ...), ``node`` name and
        ``status`` (``ok`` / ``error``). Persisted under the ``agent_trace``
        event type so a run's full chain can be reconstructed and a failed
        node located after the fact.
        """
        return await self.record_event(
            type="agent_trace",
            actor_id=actor_id,
            metadata={
                "session_id": session_id,
                "round": round,
                "step": step,
                "node": node,
                "status": status,
                "detail": detail or {},
            },
        )

    async def usage_by_task(self, task_type: str) -> TokenUsage:
        """Aggregate token usage for a task across all recorded model calls."""
        events = await self._repo.list(limit=1_000_000)
        prompt = completion = total = 0
        for ev in events:
            if ev.type != "model_usage":
                continue
            if ev.metadata.get("task_type") != task_type:
                continue
            u = ev.metadata.get("usage", {})
            prompt += int(u.get("prompt_tokens", 0) or 0)
            completion += int(u.get("completion_tokens", 0) or 0)
            total += int(u.get("total_tokens", 0) or 0)
        return TokenUsage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
        )

    async def query(
        self,
        *,
        actor_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        risk_level: Optional[str] = None,
        type: Optional[str] = None,
        from_ts: Optional[datetime] = None,
        to_ts: Optional[datetime] = None,
        limit: int = 200,
    ) -> list[AuditEvent]:
        """Filterable audit log query (DEV_SPEC §J6).

        All filters are optional; results are newest-first and capped by
        ``limit``. Mirrors the in-Python filtering used by :meth:`usage_by_task`
        (the in-memory repo has no secondary-index query API yet).
        """
        events = await self._repo.list(limit=10_000_000)
        out: list[AuditEvent] = []
        for e in events:
            if actor_id is not None and e.actor_id != actor_id:
                continue
            if tool_name is not None and e.tool_name != tool_name:
                continue
            if risk_level is not None and e.risk_level != risk_level:
                continue
            if type is not None and e.type != type:
                continue
            if from_ts is not None and e.timestamp < from_ts:
                continue
            if to_ts is not None and e.timestamp > to_ts:
                continue
            out.append(e)
        out.sort(key=lambda e: e.timestamp, reverse=True)
        return out[:limit]
