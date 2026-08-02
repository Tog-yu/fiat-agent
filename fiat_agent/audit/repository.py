"""Audit event model + repository boundary (phase B5, DEV_SPEC B5)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fiat_agent.schemas.common import FiatModel


class AuditEvent(FiatModel):
    """A single auditable occurrence (tool call, policy decision, approval...).

    JSON-serializable (FiatModel) so it can be persisted and exported. Sensitive
    values must already be redacted by :func:`fiat_agent.logging.redact_sensitive`
    before being placed into ``metadata``.
    """

    id: str
    timestamp: datetime
    type: str  # tool_call | policy_decision | approval | generic
    actor_id: str = ""
    roles: list[str] = []
    environment: str = ""
    tool_name: str | None = None
    action: str | None = None
    allowed: bool | None = None
    reason: str | None = None
    risk_level: str | None = None
    metadata: dict[str, Any] = {}


class AuditRepository:
    """Persistence boundary for audit events (async for later DB swap)."""

    async def add(self, event: AuditEvent) -> None:  # pragma: no cover
        raise NotImplementedError

    async def list(self, limit: int = 100) -> list[AuditEvent]:  # pragma: no cover
        raise NotImplementedError


class InMemoryAuditRepository(AuditRepository):
    """Default in-memory repository; sufficient for unit tests and local runs."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    async def add(self, event: AuditEvent) -> None:
        self._events.append(event)

    async def list(self, limit: int = 100) -> list[AuditEvent]:
        return self._events[-limit:]
