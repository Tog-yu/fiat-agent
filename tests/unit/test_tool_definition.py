"""F1 unit test: ToolDefinition schema (DEV_SPEC §F1).

Covers the required fields (name / description / input_schema / risk_level /
approval_required), their defaults, and JSON serializability.
"""

from __future__ import annotations

import json

import pytest

from fiat_agent.schemas.common import RiskLevel
from fiat_agent.tools.schemas import ToolDefinition


@pytest.mark.unit
def test_required_fields_present() -> None:
    tool = ToolDefinition(
        name="es_query",
        description="query Elasticsearch read-only",
        input_schema={
            "type": "object",
            "properties": {"index": {"type": "string"}},
        },
    )
    assert tool.name == "es_query"
    assert tool.description == "query Elasticsearch read-only"
    assert tool.input_schema == {
        "type": "object",
        "properties": {"index": {"type": "string"}},
    }
    assert tool.risk_level == RiskLevel.L1
    assert tool.approval_required is False


@pytest.mark.unit
def test_risk_and_approval_overridable() -> None:
    tool = ToolDefinition(
        name="cashback_submit",
        risk_level=RiskLevel.L4,
        approval_required=True,
    )
    assert tool.risk_level == RiskLevel.L4
    assert tool.approval_required is True


@pytest.mark.unit
def test_json_serializable() -> None:
    tool = ToolDefinition(name="x", description="d", input_schema={"type": "object"})
    dumped = tool.model_dump()
    # JSON-serializable (acceptance: schema can be serialized).
    payload = json.dumps(dumped)
    assert isinstance(payload, str)
    # Enum serializes to its stable string value.
    assert dumped["risk_level"] == "L1"
    assert dumped["approval_required"] is False
