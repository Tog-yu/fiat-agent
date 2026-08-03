"""Unit tests for D5: tool result -> model message conversion.

Covers the two acceptance criteria from DEV_SPEC D5:

* success / failure / approval-pending each produce a standard message
* sensitive raw results are never exposed to the model
"""

import pytest

from fiat_agent.models.base import ChatMessage
from fiat_agent.tools.function_calling import (
    ToolResult,
    ToolResultStatus,
    to_tool_result_message,
)


@pytest.mark.unit
def test_success_message():
    r = ToolResult(
        tool_call_id="c1", name="search", status=ToolResultStatus.SUCCESS, content="found 3 docs"
    )
    msg = to_tool_result_message(r)
    assert isinstance(msg, ChatMessage)
    assert msg.role == "tool"
    assert msg.tool_call_id == "c1"
    assert msg.content == "found 3 docs"


@pytest.mark.unit
def test_error_message_no_raw_leak():
    r = ToolResult(
        tool_call_id="c2",
        name="db",
        status=ToolResultStatus.ERROR,
        error="connection refused",
        raw="TRACEBACK password=secret123",
    )
    msg = to_tool_result_message(r)
    assert msg.role == "tool"
    assert "connection refused" in msg.content
    # raw must never reach the model context
    assert "secret123" not in msg.content
    assert "TRACEBACK" not in msg.content


@pytest.mark.unit
def test_pending_approval_message():
    r = ToolResult(tool_call_id="c3", name="refund", status=ToolResultStatus.PENDING_APPROVAL)
    msg = to_tool_result_message(r)
    assert "awaiting approval" in msg.content
    assert msg.tool_call_id == "c3"


@pytest.mark.unit
def test_success_empty_content_default():
    r = ToolResult(tool_call_id="c4", name="noop", status=ToolResultStatus.SUCCESS)
    msg = to_tool_result_message(r)
    assert msg.content == "(tool returned no output)"


@pytest.mark.unit
def test_raw_never_in_message_even_on_success():
    r = ToolResult(
        tool_call_id="c5",
        name="x",
        status=ToolResultStatus.SUCCESS,
        content="ok",
        raw="SUPER_SECRET_TOKEN=abc123",
    )
    msg = to_tool_result_message(r)
    assert "SUPER_SECRET_TOKEN" not in msg.content
