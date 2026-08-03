"""Lark tool contract (phase F6, DEV_SPEC §F6).

Wraps the Lark SDK behind two intent-level operations — sending an alert digest
and creating an approval card. The actual SDK call is delegated to a pluggable
client; :class:`FakeLarkClient` stands in for the SDK in tests so no network or
real Lark tenant is touched (DEV_SPEC §9: no external services in unit tests).
"""

from __future__ import annotations

from typing import Any

from fiat_agent.errors import ToolContractViolation
from fiat_agent.schemas.common import FiatModel

MAX_SUMMARY_LEN = 4000
MAX_TITLE_LEN = 200


class LarkMessage(FiatModel):
    """Result of sending an alert/text message."""

    chat_id: str
    content: str
    msg_type: str = "text"
    message_id: str | None = None


class LarkApprovalCard(FiatModel):
    """Result of creating an approval interactive card."""

    chat_id: str
    title: str
    fields: dict[str, Any] = {}
    card_id: str | None = None


class FakeLarkClient:
    """In-memory stand-in for the Lark SDK (used by tests)."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.cards: list[tuple[str, str, dict[str, Any]]] = []
        self._seq = 0

    async def send(
        self, chat_id: str, content: str, msg_type: str = "text"
    ) -> dict[str, Any]:
        self._seq += 1
        self.sent.append((chat_id, content, msg_type))
        return {"message_id": f"m{self._seq}"}

    async def create_card(
        self, chat_id: str, title: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        self._seq += 1
        self.cards.append((chat_id, title, fields))
        return {"card_id": f"c{self._seq}"}


class LarkTool:
    """High-level Lark operations bound to a client (real SDK or fake)."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def send_alert_summary(self, chat_id: str, summary: str) -> LarkMessage:
        """Send an alert digest to ``chat_id``."""
        if not chat_id:
            raise ToolContractViolation("chat_id is required")
        if not summary or not summary.strip():
            raise ToolContractViolation("alert summary must not be empty")
        if len(summary) > MAX_SUMMARY_LEN:
            raise ToolContractViolation(
                f"alert summary exceeds {MAX_SUMMARY_LEN} chars",
                metadata={"max": MAX_SUMMARY_LEN},
            )
        resp = await self._client.send(chat_id, summary, msg_type="text")
        return LarkMessage(
            chat_id=chat_id,
            content=summary,
            msg_type="text",
            message_id=resp.get("message_id"),
        )

    async def create_approval_card(
        self, chat_id: str, title: str, fields: dict[str, Any] | None = None
    ) -> LarkApprovalCard:
        """Create an approval interactive card in ``chat_id``."""
        if not chat_id:
            raise ToolContractViolation("chat_id is required")
        if not title or not title.strip():
            raise ToolContractViolation("approval card title must not be empty")
        if len(title) > MAX_TITLE_LEN:
            raise ToolContractViolation(
                f"title exceeds {MAX_TITLE_LEN} chars", metadata={"max": MAX_TITLE_LEN}
            )
        resp = await self._client.create_card(chat_id, title, fields or {})
        return LarkApprovalCard(
            chat_id=chat_id,
            title=title,
            fields=fields or {},
            card_id=resp.get("card_id"),
        )
