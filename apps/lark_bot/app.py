"""Lark bot FastAPI app (DEV_SPEC §I4).

Exposes ``POST /lark/events`` which receives Lark callbacks (URL-verification
handshake, IM message events, and approval card-action callbacks) and dispatches
them to the handlers in :mod:`apps.lark_bot.handlers`.

Dependencies are injectable so integration tests can swap in hermetic fakes:
  * ``get_agent_service``   — the shared agent service (reused from the API)
  * ``get_approval_service``— an :class:`ApprovalService`
  * ``get_lark_sender``     — an outbound Lark channel (default: no-op logger)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, FastAPI

from apps.api.agent_service import AgentService, get_agent_service
from apps.lark_bot.handlers import (
    LoggingLarkSender,
    LarkApprovalHandler,
    LarkMessageHandler,
    LarkSender,
    event_kind,
)
from fiat_agent.approvals.service import ApprovalService

_approval_service: ApprovalService | None = None


async def get_approval_service() -> ApprovalService:
    """Lazily-built process-wide approval service (in-memory by default)."""
    global _approval_service
    if _approval_service is None:
        _approval_service = ApprovalService()
    return _approval_service


def get_lark_sender() -> LarkSender:
    """Outbound Lark channel. Default: no-op logger (no credentials required)."""
    return LoggingLarkSender()


router = APIRouter(prefix="/lark", tags=["lark"])


@router.post("/events")
async def lark_events(
    payload: dict,
    agent_service: AgentService = Depends(get_agent_service),
    approval_service: ApprovalService = Depends(get_approval_service),
    sender: LarkSender = Depends(get_lark_sender),
) -> dict:
    kind = event_kind(payload)

    if kind == "url_verification":
        return {"challenge": payload.get("challenge", "")}

    if kind == "message":
        handler = LarkMessageHandler(agent_service, sender)
        result = await handler.handle(payload)
        return {"ok": True, "type": "message", "answer": result.get("final_answer")}

    if kind == "card":
        handler = LarkApprovalHandler(approval_service, sender)
        result = await handler.handle(payload)
        return {"ok": True, "type": "card", **result}

    return {"ok": False, "type": "unknown"}


app = FastAPI(title="fiat-agent-lark-bot", version="0.1.0")
app.include_router(router)
