"""Tool Gateway — single execution entry point (phase F3, DEV_SPEC §6.4 / §F3).

Every tool invocation (business tool or MCP-derived) flows through
:class:`ToolGateway.execute_tool`. It enforces the deterministic authorization
boundary (B4 ``can_execute``) *before* any side effect, runs the registered
handler, and records an auditable ``tool_call`` event *after*.

Failures never escape as raw exceptions — they are normalized into the shared
:class:`ToolResult` (D5) so the agent loop always sees one structure.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from uuid import uuid4

from fiat_agent.audit.service import AuditService
from fiat_agent.auth.policy import can_execute
from fiat_agent.schemas.common import ActorContext, FiatModel
from fiat_agent.tools.function_calling import ToolResult, ToolResultStatus


class ToolCallRecord(FiatModel):
    """In-memory record of one tool invocation (gateway-local ``tool_calls`` log).

    Later phases persist this to the session event store
    (``fiat_agent.sessions.store.ToolCall``); here it stays in memory so execution
    is hermetic and testable without a database.
    """

    id: str
    tool_name: str
    actor_id: str
    environment: str = ""
    arguments: dict[str, Any] = {}
    status: str  # success | error | pending_approval
    error: str | None = None
    result_summary: str | None = None
    timestamp: datetime


# A handler receives (actor, arguments, context) and returns the raw output.
Handler = Callable[
    [ActorContext, dict[str, Any], Any],
    Any | Awaitable[Any],
]


class ToolGateway:
    """Authorization-gated, audited dispatcher for every tool call."""

    def __init__(self, audit_service: AuditService) -> None:
        self._audit = audit_service
        self._handlers: dict[str, Handler] = {}
        self.tool_calls: list[ToolCallRecord] = []

    # --- handler registration -----------------------------------------
    def register_handler(self, name: str, handler: Handler) -> None:
        """Register the function that actually executes ``name``.

        The handler may be sync or async; it receives ``(actor, arguments,
        context)`` and returns the raw tool output.
        """
        self._handlers[name] = handler

    # --- execution ----------------------------------------------------
    async def execute_tool(
        self,
        actor: ActorContext,
        tool_name: str,
        arguments: dict[str, Any],
        context: Any | None = None,
        *,
        approved: bool = False,
        tool_call_id: str | None = None,
    ) -> ToolResult:
        """Execute ``tool_name`` on behalf of ``actor``, with policy + audit.

        Flow:
          1. ``can_execute`` gate (deterministic, no LLM). Denied -> ERROR result.
          2. approval gate: if the tool requires approval and the caller hasn't
             signaled ``approved``, defer with PENDING_APPROVAL (no execution).
          3. handler runs; success/error normalized into ``ToolResult``.
          4. a ``ToolCallRecord`` and an audit ``tool_call`` event are written
             regardless of outcome.

        Args:
            actor: the acting principal.
            tool_name: policy key / registered handler name.
            arguments: validated tool arguments.
            context: optional execution context passed through to the handler.
            approved: set True only after an approval flow has cleared the call.
            tool_call_id: id linking this call to the model's function_call.

        Returns:
            A :class:`ToolResult` — success, error, or pending_approval.
        """
        call_id = tool_call_id or uuid4().hex
        decision = can_execute(actor, tool_name)

        # 1. authorization gate (before any side effect).
        if not decision.allowed:
            return await self._finish(
                call_id, actor, tool_name, arguments,
                status=ToolResultStatus.ERROR,
                error=decision.reason,
                decision_allowed=False,
                decision_reason=decision.reason,
            )

        # 2. approval gate.
        if decision.approval_required and not approved:
            return await self._finish(
                call_id, actor, tool_name, arguments,
                status=ToolResultStatus.PENDING_APPROVAL,
                error="tool requires approval before execution",
                decision_allowed=True,
                decision_reason=decision.reason,
            )

        # 3. execute handler.
        handler = self._handlers.get(tool_name)
        if handler is None:
            return await self._finish(
                call_id, actor, tool_name, arguments,
                status=ToolResultStatus.ERROR,
                error=f"no handler registered for tool '{tool_name}'",
                decision_allowed=True,
                decision_reason=decision.reason,
            )

        try:
            raw = handler(actor, arguments, context)
            if inspect.isawaitable(raw):
                raw = await raw
            summary = _summarize(raw)
            return await self._finish(
                call_id, actor, tool_name, arguments,
                status=ToolResultStatus.SUCCESS,
                error=None,
                result_summary=summary,
                raw=raw,
                decision_allowed=True,
                decision_reason=decision.reason,
            )
        except Exception as exc:  # noqa: BLE001 - normalize, don't leak stack
            return await self._finish(
                call_id, actor, tool_name, arguments,
                status=ToolResultStatus.ERROR,
                error=str(exc),
                decision_allowed=True,
                decision_reason=decision.reason,
            )

    # --- internal -----------------------------------------------------
    async def _finish(
        self,
        call_id: str,
        actor: ActorContext,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        status: ToolResultStatus,
        error: str | None,
        result_summary: str | None = None,
        raw: Any | None = None,
        decision_allowed: bool,
        decision_reason: str | None,
    ) -> ToolResult:
        # 4. write tool_calls record + audit_logs event (after execution).
        record = ToolCallRecord(
            id=call_id,
            tool_name=tool_name,
            actor_id=actor.actor_id,
            environment=actor.environment.value,
            arguments=arguments,
            status=status.value,
            error=error,
            result_summary=result_summary,
            timestamp=datetime.now(timezone.utc),
        )
        self.tool_calls.append(record)

        await self._audit.record_tool_call(
            actor,
            tool_name,
            arguments,
            result={"status": status.value, "error": error, "summary": result_summary},
            decision=None,
        )

        return ToolResult(
            tool_call_id=call_id,
            name=tool_name,
            status=status,
            content=result_summary or "",
            error=error,
            raw=raw,
        )


def _summarize(raw: Any) -> str:
    """Best-effort short, model-safe summary of a raw tool output."""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw[:500]
    if isinstance(raw, (dict, list)):
        try:
            import json

            text = json.dumps(raw, ensure_ascii=False, default=str)
            return text[:500]
        except (TypeError, ValueError):
            return str(raw)[:500]
    return str(raw)[:500]
