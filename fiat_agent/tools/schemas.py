"""Tool definition schema (phase B4; canonical home, reused by F1)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from fiat_agent.schemas.common import RiskLevel


class ToolDefinition(BaseModel):
    """Canonical tool descriptor used by auth filtering and the tool gateway.

    Declared here (B4) because the policy service needs a tool representation;
    F1 extends the surrounding tool registry around it.
    """

    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.L1
    approval_required: bool = False
