"""Agent / tool result schemas (phase A5, DEV_SPEC §11-A5).

Extends the common base with `ToolResult`, the uniform shape every tool call
returns to the orchestrator. Kept JSON-serializable so results can be stored in
session events and exported as JSONL (phases C / K).
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field

from fiat_agent.schemas.common import FiatModel


class ToolStatus(str, Enum):
    """Outcome of a tool execution."""

    SUCCESS = "success"
    FAILURE = "failure"
    APPROVAL_REQUIRED = "approval_required"
    PENDING = "pending"


class ToolResult(FiatModel):
    """Uniform result returned by every tool via the Tool Gateway."""

    tool_name: str
    status: ToolStatus
    data: Any = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
