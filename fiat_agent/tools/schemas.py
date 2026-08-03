"""Tool definition schema (phase B4; canonical home, reused by F1)."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from fiat_agent.schemas.common import FiatModel, RiskLevel


class ToolDefinition(FiatModel):
    """Canonical tool descriptor used by auth filtering and the tool gateway.

    Declared here (B4) because the policy service needs a tool representation;
    F1 formalizes it as the project's canonical `FiatModel`-based tool schema.
    Every business tool and MCP-derived tool is represented by this model so
    the registry (F2) and gateway (F3) share one contract.
    """

    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.L1
    approval_required: bool = False
