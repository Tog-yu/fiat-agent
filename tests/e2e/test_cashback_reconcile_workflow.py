"""H6 e2e test: cashback reconciliation dry-run (DEV_SPEC §H6).

Exercises :func:`fiat_agent.workflows.cashback_reconcile.run_cashback_reconcile`
end-to-end with hermetic fakes and asserts the two acceptance pillars:

1. **校验通过** — total / record / status validation all run; the report's
   ``summary`` math is correct and every issue type is detected.
2. **只做 dry-run** — ``is_dry_run`` is ``True`` and the production-write tool
   (``cashback_submit``) is never invoked; only the read-only ``cashback_parse``
   tool is called through the audited gateway.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from fiat_agent.audit.repository import InMemoryAuditRepository
from fiat_agent.audit.service import AuditService
from fiat_agent.models.base import BaseChatModel, ChatRequest, ChatResponse, TokenUsage
from fiat_agent.models.gateway import ModelGateway
from fiat_agent.schemas.common import ActorContext, Environment, RiskLevel, TaskType
from fiat_agent.tool_gateway.cashback_tools import make_cashback_parse_handler
from fiat_agent.tool_gateway.gateway import ToolGateway
from fiat_agent.tools.registry import ToolRegistry
from fiat_agent.tools.schemas import ToolDefinition
from fiat_agent.workflows.cashback_reconcile import (
    CashbackReconcileResult,
    run_cashback_reconcile,
)


@pytest.mark.e2e
def test_cashback_reconcile_dry_run_report(tmp_path):
    csv_path = tmp_path / "rebate.csv"
    csv_path.write_text(
        # row0 T1 paid 100 (clean) | row1 T1 paid 100 (DUP) | row2 T2 abc (bad amt)
        # row3 T3 'unknown' status (invalid) | row4 T4 pending 200 (clean)
        "交易号,用户ID,金额,币种,状态,日期\n"
        "T1,U1,100.00,CNY,paid,2026-01-01\n"
        "T1,U1,100.00,CNY,paid,2026-01-01\n"
        "T2,U2,abc,CNY,pending,2026-01-02\n"
        "T3,U3,50.00,CNY,unknown,2026-01-03\n"
        "T4,U4,200.00,CNY,pending,2026-01-04\n",
        encoding="utf-8-sig",
    )

    audit = AuditService(InMemoryAuditRepository())
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="cashback_parse", risk_level=RiskLevel.L1, approval_required=False)
    )
    # Register the production-write tool too, so we can PROVE it is never called.
    submit_calls = {"n": 0}

    async def submit_handler(actor, args, ctx):
        submit_calls["n"] += 1
        raise AssertionError("cashback_submit must never be called in dry-run")

    gateway = ToolGateway(audit)
    gateway.register_handler("cashback_parse", make_cashback_parse_handler())
    gateway.register_handler("cashback_submit", submit_handler)

    model = _FakeModel("已生成对账报告，请运营复核异常项。")
    model_gw = ModelGateway(
        policies=SimpleNamespace(),
        provider_factory=lambda p, t, c: model,
        audit_sink=lambda task, m, usage: audit.record_model_usage(
            task_type=task, model=m, usage=usage
        ),
    )
    actor = ActorContext(actor_id="u1", roles=["oncall"], environment=Environment.DEV)

    result: CashbackReconcileResult = asyncio.run(
        run_cashback_reconcile(
            str(csv_path),
            actor=actor,
            registry=registry,
            gateway=gateway,
            model_gateway=model_gw,
            audit_service=audit,
        )
    )

    # Acceptance 2: dry-run only — parse ran, submit never did.
    assert result.is_dry_run is True
    assert submit_calls["n"] == 0
    assert any(
        c.tool_name == "cashback_parse" and c.status == "success"
        for c in gateway.tool_calls
    )
    assert all(c.tool_name == "cashback_parse" for c in gateway.tool_calls)

    # Acceptance 1: reconciliation math + status validation.
    s = result.summary
    assert s["record_count"] == 5
    assert s["total_amount"] == Decimal("450.00")  # 100+100+50+200 (bad amt excluded)
    assert s["matched"] == 2          # row0, row4
    assert s["mismatched"] == 3       # row1 dup, row2 bad amt, row3 bad status

    issue_types = {i["type"] for i in result.issues}
    assert issue_types == {"duplicate", "amount_format", "status_invalid"}
    assert len(result.change_plan) == len(result.issues)

    # Model produced the narrative (best-effort augmentation on top).
    assert "对账" in result.narrative


@pytest.mark.e2e
def test_cashback_reconcile_parse_error_is_dry_run_error(tmp_path):
    """A missing/unparseable file yields an error report, still dry-run."""
    bad = tmp_path / "missing.csv"
    audit = AuditService(InMemoryAuditRepository())
    registry = ToolRegistry()
    registry.register(ToolDefinition(name="cashback_parse", risk_level=RiskLevel.L1))
    gateway = ToolGateway(audit)
    gateway.register_handler("cashback_parse", make_cashback_parse_handler())

    result = asyncio.run(
        run_cashback_reconcile(
            str(bad),  # file does not exist
            actor=ActorContext(actor_id="u1", roles=["oncall"], environment=Environment.DEV),
            registry=registry,
            gateway=gateway,
            audit_service=audit,
        )
    )
    assert result.is_dry_run is True
    assert result.error is not None


class _FakeModel(BaseChatModel):
    """Deterministic model that records how many times it was called."""

    provider = "fake"

    def __init__(self, answer: str) -> None:
        self._answer = answer
        self.calls = 0

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        return ChatResponse(
            content=self._answer,
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )

    async def stream(self, request: ChatRequest):
        yield ChatResponse(content=self._answer)
