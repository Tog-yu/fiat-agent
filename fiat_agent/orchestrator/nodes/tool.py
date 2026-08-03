"""Tool-execution node (phase G5, DEV_SPEC §G5).

Runs the tool calls requested by the latest assistant message through the
policy-gated, audited :class:`~fiat_agent.tool_gateway.gateway.ToolGateway` and
feeds every result back to the model as a ``role="tool"`` message (DEV_SPEC
D5). Permission-denied or approval-required calls are **not** executed — the
gateway enforces the boundary and the node only surfaces the outcome.
"""

from __future__ import annotations

import json
from typing import Any, Optional
from uuid import uuid4

from fiat_agent.models.base import ChatMessage
from fiat_agent.orchestrator.state import AgentState
from fiat_agent.schemas.agent import ToolResult as SchemaToolResult, ToolStatus
from fiat_agent.tool_gateway.gateway import ToolGateway
from fiat_agent.tools.function_calling import (
    ToolResult as GatewayToolResult,
    ToolResultStatus,
    to_tool_result_message,
)


def _parse_args(arguments: Optional[str]) -> dict[str, Any]:
    """Parse a tool-call argument JSON string into a dict (best effort)."""
    if not arguments:
        return {}
    try:
        parsed = json.loads(arguments)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, ValueError):
        return {}


def _pending_tool_calls(state: AgentState):
    for msg in reversed(state.messages):
        if msg.role == "assistant" and msg.tool_calls:
            return list(msg.tool_calls)
    return []


def _to_schema_status(status: ToolResultStatus) -> ToolStatus:
    return {
        ToolResultStatus.SUCCESS: ToolStatus.SUCCESS,
        ToolResultStatus.ERROR: ToolStatus.FAILURE,
        ToolResultStatus.PENDING_APPROVAL: ToolStatus.APPROVAL_REQUIRED,
    }.get(status, ToolStatus.FAILURE)


async def tool_node(
    state: AgentState, gateway: ToolGateway, context: Any = None
) -> dict:
    """Execute pending tool calls and return the state delta.

    Returns ``{"messages": [tool messages], "tool_results": [ToolResult]}``.
    Each tool call becomes one ``role="tool"`` message (so the next model turn
    sees the output) and one normalized :class:`SchemaToolResult` on the state.
    """
    calls = _pending_tool_calls(state)
    new_messages: list[ChatMessage] = []
    results: list[SchemaToolResult] = []
    for fc in calls:
        args = _parse_args(fc.arguments)
        gw_result: GatewayToolResult = await gateway.execute_tool(
            state.actor, fc.name, args, context, tool_call_id=fc.id or uuid4().hex
        )
        new_messages.append(to_tool_result_message(gw_result))
        results.append(
            SchemaToolResult(
                tool_name=fc.name,
                status=_to_schema_status(gw_result.status),
                data=gw_result.raw if gw_result.status == ToolResultStatus.SUCCESS else None,
                error=gw_result.error,
            )
        )
    return {"messages": new_messages, "tool_results": results}
