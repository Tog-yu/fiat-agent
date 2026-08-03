"""F6 unit test: Lark tool contract (DEV_SPEC §F6).

Verifies, against the fake Lark SDK client:
  1. an alert summary can be sent;
  2. an approval card can be created;
  3. empty/oversized inputs are rejected by the contract.
"""

from __future__ import annotations

import asyncio

import pytest

from fiat_agent.errors import ToolContractViolation
from fiat_agent.tool_gateway.lark_tools import FakeLarkClient, LarkTool


@pytest.mark.unit
def test_send_alert_summary() -> None:
    fake = FakeLarkClient()
    tool = LarkTool(fake)

    msg = asyncio.run(tool.send_alert_summary("oc_alert", "CPU > 95% on node-7"))
    assert msg.message_id is not None
    assert msg.content == "CPU > 95% on node-7"
    # SDK received exactly this call.
    assert fake.sent == [("oc_alert", "CPU > 95% on node-7", "text")]


@pytest.mark.unit
def test_create_approval_card() -> None:
    fake = FakeLarkClient()
    tool = LarkTool(fake)

    card = asyncio.run(
        tool.create_approval_card(
            "oc_approval", "Refund ¥500", {"user": "u42", "amount": 500}
        )
    )
    assert card.card_id is not None
    assert card.title == "Refund ¥500"
    assert card.fields == {"user": "u42", "amount": 500}
    assert fake.cards == [("oc_approval", "Refund ¥500", {"user": "u42", "amount": 500})]


@pytest.mark.unit
def test_empty_summary_rejected() -> None:
    tool = LarkTool(FakeLarkClient())
    with pytest.raises(ToolContractViolation):
        asyncio.run(tool.send_alert_summary("oc", "   "))


@pytest.mark.unit
def test_empty_title_rejected() -> None:
    tool = LarkTool(FakeLarkClient())
    with pytest.raises(ToolContractViolation):
        asyncio.run(tool.create_approval_card("oc", ""))
