"""H4 e2e test: 测试环境自动化 workflow (DEV_SPEC §H4).

Exercises :func:`fiat_agent.workflows.test_automation.run_test_automation` end-to-end
with hermetic fakes (no real LLM / test-env backend) and asserts the acceptance pillars:

1. **仅测试环境可执行** — in a non-DEV environment the workflow refuses
   deterministically: no model call, no tool call, ``error`` set.
2. **流程可编排（DEV）** — in DEV the model plans the full pipeline and the
   workflow runs ``create_account`` -> ``recharge`` -> ``kyc`` through the audited
   gateway; each resource is stamped ``TEST_`` and ``is_test`` is ``True``.
3. **失败即停** — when one step fails the pipeline stops; downstream steps are not
   attempted and the failure is recorded.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from fiat_agent.audit.repository import InMemoryAuditRepository
from fiat_agent.audit.service import AuditService
from fiat_agent.models.base import BaseChatModel, ChatRequest, ChatResponse, TokenUsage
from fiat_agent.models.gateway import ModelGateway
from fiat_agent.schemas.common import ActorContext, Environment, RiskLevel, TaskType
from fiat_agent.tool_gateway.gateway import ToolGateway
from fiat_agent.tool_gateway.test_env_tools import (
    FakeTestEnvClient,
    TestEnvRequest,
    TestEnvTool,
)
from fiat_agent.tools.registry import ToolRegistry
from fiat_agent.tools.schemas import ToolDefinition
from fiat_agent.workflows.test_automation import (
    TestAutomationResult,
    run_test_automation,
)


class _FakeModel(BaseChatModel):
    """Deterministic model that returns a fixed action plan and counts calls."""

    provider = "fake"

    def __init__(self, json_text: str) -> None:
        self._json = json_text
        self.calls = 0

    async def chat(self, request: ChatRequest) -> ChatResponse:  # noqa: D401
        self.calls += 1
        return ChatResponse(
            content=self._json,
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )

    async def stream(self, request: ChatRequest):
        yield ChatResponse(content=self._json)


def _register(registry: ToolRegistry) -> None:
    registry.register(
        ToolDefinition(
            name="test_env",
            description="test-env automation",
            risk_level=RiskLevel.L3,
            approval_required=False,
        )
    )


def _build(model_json: str, *, fail_on: Optional[str] = None):
    """Assemble a hermetic test-automation run using the real TestEnvTool."""
    audit = AuditService(InMemoryAuditRepository())
    registry = ToolRegistry()
    _register(registry)
    gateway = ToolGateway(audit)
    tool = TestEnvTool(FakeTestEnvClient())

    async def test_env_handler(actor, args, ctx):  # type: ignore[no-untyped-def]
        if fail_on and args.get("action") == fail_on:
            raise RuntimeError(f"{fail_on} backend error")
        req = TestEnvRequest(
            environment=Environment.DEV,
            action=args["action"],
            payload=args.get("payload", {}),
        )
        return await tool.execute(req)

    gateway.register_handler("test_env", test_env_handler)

    model = _FakeModel(model_json)
    model_gw = ModelGateway(
        policies=SimpleNamespace(),
        provider_factory=lambda p, t, c: model,
        audit_sink=lambda task, m, usage: audit.record_model_usage(
            task_type=task, model=m, usage=usage
        ),
    )
    return audit, registry, gateway, model_gw, model


def _actor(environment: Environment) -> ActorContext:
    return ActorContext(actor_id="u1", roles=["oncall"], environment=environment)


_FULL_PLAN = '{"actions": ["create_account", "recharge", "kyc"]}'


@pytest.mark.e2e
def test_test_automation_dev_full_pipeline():
    audit, registry, gateway, model_gw, model = _build(_FULL_PLAN)
    actor = _actor(Environment.DEV)

    result: TestAutomationResult = asyncio.run(
        run_test_automation(
            "帮我建个测试账号，充值 100，再做 KYC",
            actor=actor,
            registry=registry,
            gateway=gateway,
            model_gateway=model_gw,
            audit_service=audit,
        )
    )

    # Acceptance 2: planned + executed full pipeline in DEV.
    assert result.environment == "dev"
    assert result.is_test is True
    assert result.error is None
    assert len(result.steps) == 3
    assert [s["action"] for s in result.steps] == ["create_account", "recharge", "kyc"]
    assert all(s["status"] == "ok" for s in result.steps)
    # Every resource is test data, stamped with TEST_.
    assert all(
        s["resource_id"].startswith("TEST_") for s in result.steps if s["resource_id"]
    )
    # Model planned the sequence; all three steps ran through the audited gateway.
    assert model.calls == 1
    assert len(gateway.tool_calls) == 3
    assert all(c.tool_name == "test_env" and c.status == "success" for c in gateway.tool_calls)
    events = asyncio.run(audit._repo.list(limit=100))
    assert any(e.type == "tool_call" for e in events)


@pytest.mark.e2e
def test_test_automation_non_dev_refused():
    audit, registry, gateway, model_gw, model = _build(_FULL_PLAN)
    actor = _actor(Environment.STAGING)

    result = asyncio.run(
        run_test_automation(
            "建个测试账号",
            actor=actor,
            registry=registry,
            gateway=gateway,
            model_gateway=model_gw,
            audit_service=audit,
        )
    )

    # Acceptance 1: deterministic refusal — no model, no tool, error set.
    assert result.error is not None
    assert "DEV" in result.error
    assert result.environment == "staging"
    assert result.steps == []
    assert model.calls == 0
    assert gateway.tool_calls == []


@pytest.mark.e2e
def test_test_automation_stops_on_failure():
    # recharge fails in the backend -> pipeline stops before kyc.
    audit, registry, gateway, model_gw, model = _build(_FULL_PLAN, fail_on="recharge")
    actor = _actor(Environment.DEV)

    result = asyncio.run(
        run_test_automation(
            "建号、充值、KYC",
            actor=actor,
            registry=registry,
            gateway=gateway,
            model_gateway=model_gw,
            audit_service=audit,
        )
    )

    # Only create_account (ok) then recharge (failed); kyc not attempted.
    assert len(result.steps) == 2
    assert result.steps[0]["action"] == "create_account"
    assert result.steps[0]["status"] == "ok"
    assert result.steps[1]["action"] == "recharge"
    assert result.steps[1]["status"] == "failed"
    assert model.calls == 1
    assert len(gateway.tool_calls) == 2
    assert [c.tool_name for c in gateway.tool_calls] == ["test_env", "test_env"]
