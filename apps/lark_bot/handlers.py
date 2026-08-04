"""Lark bot handlers (DEV_SPEC §I4).

Pure parsing + dispatch logic for Lark event callbacks, kept free of any network
dependency so it is fully unit/integration-testable. The two side effects —
replying to a chat and notifying an approver — go through an injectable
:class:`LarkSender`, so tests use a capturing fake instead of the real Lark API.

Supported Lark event shapes (v2 callback):
  * ``url_verification``      -> echo back the ``challenge`` (handshake)
  * ``im.message.receive_v1`` -> Q&A: run the agent, reply with the answer
  * ``card.action.trigger``   -> approval decision (approve / reject) from a card
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from fiat_agent.schemas.common import ActorContext, Environment


class LarkSender(ABC):
    """Outbound channel to Lark (chat reply / approver notification)."""

    @abstractmethod
    async def send_text(self, open_id: str, text: str) -> None:
        """Send a plain-text message to the user identified by ``open_id``."""


class LoggingLarkSender(LarkSender):
    """No-op sender (default when no Lark credentials are configured)."""

    async def send_text(self, open_id: str, text: str) -> None:  # noqa: D401
        # In production this would call the Lark OpenAPI; the MVP just drops it.
        return None


def event_kind(payload: dict) -> str:
    """Classify a Lark callback payload."""
    if not isinstance(payload, dict):
        return "unknown"
    t = payload.get("type")
    if t == "url_verification":
        return "url_verification"
    header = payload.get("header") or {}
    event_type = header.get("event_type")
    if event_type == "im.message.receive_v1":
        return "message"
    if event_type == "card.action.trigger":
        return "card"
    return "unknown"


def extract_message(payload: dict) -> tuple[str, str]:
    """Return ``(open_id, text)`` from an ``im.message.receive_v1`` event."""
    event = payload.get("event") or {}
    sender = event.get("sender") or {}
    open_id = (sender.get("sender_id") or {}).get("open_id", "")
    message = event.get("message") or {}
    raw = message.get("content", "{}")
    try:
        text = json.loads(raw).get("text", "") if isinstance(raw, str) else ""
    except (json.JSONDecodeError, ValueError):
        text = ""
    return open_id, text


def extract_card_action(payload: dict) -> tuple[str, str, str]:
    """Return ``(open_id, approval_id, action)`` from a card action callback."""
    event = payload.get("event") or {}
    operator = event.get("operator") or {}
    open_id = operator.get("open_id", "")
    action = event.get("action") or {}
    value = action.get("value") or {}
    approval_id = value.get("approval_id", "")
    decision = value.get("action", "")
    return open_id, approval_id, decision


class LarkMessageHandler:
    """Q&A handler: runs the agent and replies to the asking user."""

    def __init__(self, agent_service: Any, sender: LarkSender) -> None:
        self._agent = agent_service
        self._sender = sender

    async def handle(self, payload: dict) -> dict:
        open_id, text = extract_message(payload)
        actor = ActorContext(
            actor_id=open_id or "lark",
            roles=["oncall"],
            environment=Environment.DEV,
        )
        session = await self._agent.create_session(title="lark", task_type=None)
        result = await self._agent.run_message(
            session_id=session["session_id"],
            actor=actor,
            content=text,
        )
        answer = result.get("final_answer") or ""
        await self._sender.send_text(open_id, answer)
        return result


class LarkApprovalHandler:
    """Approval-card handler: applies an approve/reject decision."""

    def __init__(self, approval_service: Any, sender: LarkSender) -> None:
        self._approval = approval_service
        self._sender = sender

    async def handle(self, payload: dict) -> dict:
        open_id, approval_id, decision = extract_card_action(payload)
        if decision == "approve":
            await self._approval.approve(approval_id, open_id)
            verb = "approved"
        else:
            await self._approval.reject(approval_id, open_id)
            verb = "rejected"
        await self._sender.send_text(
            open_id, f"approval {approval_id} {verb}"
        )
        return {"approval_id": approval_id, "action": decision}
