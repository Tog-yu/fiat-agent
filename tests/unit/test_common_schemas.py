"""Tests for phase A5 base data contracts (DEV_SPEC §11-A5).

Covers:
  - enum values are stable (serialization-safe, audit-friendly)
  - ActorContext / ToolResult are JSON-serializable
"""

import json

import pytest

from fiat_agent.schemas.agent import ToolResult, ToolStatus
from fiat_agent.schemas.common import (
    ActorContext,
    Environment,
    RiskLevel,
    TaskType,
)


@pytest.mark.unit
def test_enum_values_stable():
    assert Environment.PROD.value == "prod"
    assert Environment.DEV.value == "dev"
    assert Environment.STAGING.value == "staging"

    assert [r.value for r in RiskLevel] == ["L1", "L2", "L3", "L4", "L5"]

    assert TaskType.RAG_QA.value == "rag_qa"
    assert TaskType.ALERT_DIAGNOSIS.value == "alert_diagnosis"
    assert TaskType.TEST_ENV_AUTOMATION.value == "test_env_automation"
    assert TaskType.CASHBACK_RECONCILE.value == "cashback_reconcile"
    assert TaskType.LOGISTICS_VALIDATION.value == "logistics_validation"


@pytest.mark.unit
def test_actor_context_json_serializable():
    actor = ActorContext(
        actor_id="u_1",
        roles=["ops"],
        environment=Environment.PROD,
        task_type=TaskType.ALERT_DIAGNOSIS,
    )
    dumped = actor.model_dump(mode="json")
    assert dumped == {
        "actor_id": "u_1",
        "roles": ["ops"],
        "environment": "prod",
        "task_type": "alert_diagnosis",
    }
    assert json.loads(json.dumps(dumped)) == dumped


@pytest.mark.unit
def test_tool_result_json_serializable():
    result = ToolResult(
        tool_name="db_read",
        status=ToolStatus.SUCCESS,
        data={"rows": 3},
        metadata={"duration_ms": 12},
    )
    dumped = result.model_dump(mode="json")
    assert dumped["tool_name"] == "db_read"
    assert dumped["status"] == "success"
    assert dumped["data"] == {"rows": 3}
    assert json.loads(json.dumps(dumped)) == dumped


@pytest.mark.unit
def test_tool_result_failure_shape():
    result = ToolResult(
        tool_name="es_query",
        status=ToolStatus.FAILURE,
        error="index not allowed",
    )
    assert result.error == "index not allowed"
    assert result.status == ToolStatus.FAILURE
