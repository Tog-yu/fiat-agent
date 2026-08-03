"""Approval-gating node (phase G6, DEV_SPEC §G6).

Before high-risk tools run, this node inspects the candidate tools (either the
plan's ``required_tools`` or the pending tool calls) and, if any is L4/L5 or
marked approval-required, sets ``approval_state = PENDING`` and records an
``approval_requested`` session event. The actual non-execution is still enforced
downstream by the ToolGateway's approval gate (F3); this node is the explicit,
auditable decision point.
"""

from __future__ import annotations

from typing import Any, Optional

from fiat_agent.auth.policy import can_execute
from fiat_agent.orchestrator.state import AgentState, ApprovalState
from fiat_agent.schemas.common import RiskLevel

_HIGH_RISK = {RiskLevel.L4, RiskLevel.L5}


def _candidate_tools(state: AgentState, plan: Optional[Any] = None) -> list[str]:
    # Prefer the plan's declared tools, else the model's pending tool calls.
    if plan is not None and getattr(plan, "required_tools", None):
        return list(plan.required_tools)
    for msg in reversed(state.messages):
        if msg.role == "assistant" and msg.tool_calls:
            return [fc.name for fc in msg.tool_calls]
    return []


async def approval_node(
    state: AgentState,
    plan: Optional[Any] = None,
    audit_service: Optional[Any] = None,
) -> dict:
    """Decide whether this run needs human approval.

    Returns ``{"approval_state": ..., "pending_approvals": [...]}`` and, when
    approval is required, records an ``approval_requested`` event via
    ``audit_service`` (if provided).
    """
    names = _candidate_tools(state, plan)
    required: list[str] = []
    for name in names:
        decision = can_execute(state.actor, name)
        if decision.approval_required or (decision.risk_level in _HIGH_RISK):
            required.append(name)

    if not required:
        return {"approval_state": ApprovalState.NOT_REQUIRED, "pending_approvals": []}

    if audit_service is not None:
        await audit_service.record_event(
            type="approval_requested",
            actor=state.actor,
            tool_name=",".join(required),
            action="request_approval",
            allowed=None,
            reason="high-risk tool requires human approval",
            metadata={"tools": required},
        )
    return {"approval_state": ApprovalState.PENDING, "pending_approvals": required}
