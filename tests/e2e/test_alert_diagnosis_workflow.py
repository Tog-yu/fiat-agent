"""H3 e2e test: 告警诊断 workflow (DEV_SPEC §H3).

Exercises :func:`fiat_agent.workflows.alert_diagnosis.run_alert_diagnosis` end-to-end
with hermetic fakes (no real LLM / ES / DB / MCP / Lark) and asserts the acceptance
pillars:

1. **并行查询 ES / DB / RAG** — the three read tools are all invoked through the
   audited ToolGateway concurrently; each gets a success ToolCallRecord + audit
   event.
2. **结构化诊断** — the model reply (JSON matching the skill schema) is parsed into
   impact / possible_causes / confidence / next_steps.
3. **可发 Lark 通知** — when severity is P0/P1 the workflow pages Lark via the
   gateway (lark_notified=True, lark tool called); for P2 it does NOT page and
   the lark handler is never invoked.
4. A single tool failure (db_query raises) does not crash the workflow — the
   error is recorded in ``tool_errors`` and a diagnosis is still produced.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from fiat_agent.audit.repository import InMemoryAuditRepository
from fiat_agent.audit.service import AuditService
from fiat_agent.models.base import BaseChatModel, ChatRequest, ChatResponse, TokenUsage
from fiat_agent.models.gateway import ModelGateway
from fiat_agent.rag.context_merge import Citation, MergedRagContext
from fiat_agent.schemas.common import ActorContext, Environment, RiskLevel, TaskType
from fiat_agent.tool_gateway.gateway import ToolGateway
from fiat_agent.tools.registry import ToolRegistry
from fiat_agent.tools.schemas import ToolDefinition
from fiat_agent.workflows.alert_diagnosis import (
    AlertDiagnosisResult,
    run_alert_diagnosis,
)


class _FakeModel(BaseChatModel):
    """Deterministic model that returns a fixed JSON diagnosis and counts calls."""

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
    for name in ("es_query", "db_query", "rag_query", "lark_notify"):
        registry.register(
            ToolDefinition(
                name=name,
                description=f"{name} tool",
                risk_level=RiskLevel.L2,
                approval_required=False,
            )
        )


def _build(
    es_raw: Any,
    db_raw: Any,
    rag_raw: Any,
    model_json: str,
    *,
    db_fail: bool = False,
):
    """Assemble a hermetic alert-diagnosis run: audit + registry + gateway + model."""
    audit = AuditService(InMemoryAuditRepository())
    registry = ToolRegistry()
    _register(registry)
    gateway = ToolGateway(audit)
    called: dict[str, int] = {"es": 0, "db": 0, "rag": 0, "lark": 0}

    async def es_handler(actor, args, ctx):  # type: ignore[no-untyped-def]
        called["es"] += 1
        return es_raw

    async def db_handler(actor, args, ctx):  # type: ignore[no-untyped-def]
        called["db"] += 1
        if db_fail:
            raise RuntimeError("db unreachable")
        return db_raw

    async def rag_handler(actor, args, ctx):  # type: ignore[no-untyped-def]
        called["rag"] += 1
        return rag_raw

    async def lark_handler(actor, args, ctx):  # type: ignore[no-untyped-def]
        called["lark"] += 1
        assert args.get("chat_id") and args.get("content")
        return {"message_id": "m1"}

    gateway.register_handler("es_query", es_handler)
    gateway.register_handler("db_query", db_handler)
    gateway.register_handler("rag_query", rag_handler)
    gateway.register_handler("lark_notify", lark_handler)

    model = _FakeModel(model_json)
    model_gw = ModelGateway(
        policies=SimpleNamespace(),
        provider_factory=lambda p, t, c: model,
        audit_sink=lambda task, m, usage: audit.record_model_usage(
            task_type=task, model=m, usage=usage
        ),
    )
    return audit, registry, gateway, model_gw, model, called


def _actor() -> ActorContext:
    return ActorContext(actor_id="u1", roles=["oncall"], environment=Environment.DEV)


_ES_RAW = '{"hits": 12, "top": "timeout in payment-svc"}'
_DB_RAW = '{"rows": 3, "orders": ["o1", "o2", "o3"]}'
_RAG_RAW = MergedRagContext(
    query="q",
    answer="预案：先扩容 payment-svc 并回滚最近发布。",
    citations=[Citation(collection="kb", doc_id="d1", chunk_id="c1", source="预案库", snippet="扩容")],
)


@pytest.mark.e2e
def test_alert_diagnosis_parallel_and_p0_lark():
    model_json = (
        '{"impact": {"scope": "支付链路", "affected_services": ["payment-svc"], '
        '"severity": "P0"}, "possible_causes": [{"cause": "扩容不足", "evidence": '
        '"ES 超时", "likelihood": "high"}], "confidence": "high", '
        '"next_steps": ["扩容 payment-svc", "回滚发布"]}'
    )
    audit, registry, gateway, model_gw, model, called = _build(
        _ES_RAW, _DB_RAW, _RAG_RAW, model_json
    )
    actor = _actor()

    result: AlertDiagnosisResult = asyncio.run(
        run_alert_diagnosis(
            "payment-svc 大量超时",
            actor=actor,
            registry=registry,
            gateway=gateway,
            model_gateway=model_gw,
            audit_service=audit,
            lark_chat_id="oncall-room",
        )
    )

    # Acceptance 1: all three read tools were invoked through the gateway.
    assert called["es"] == 1 and called["db"] == 1 and called["rag"] == 1
    for t in ("es_query", "db_query", "rag_query"):
        assert any(c.tool_name == t and c.status == "success" for c in gateway.tool_calls)
    events = asyncio.run(audit._repo.list(limit=100))
    assert sum(1 for e in events if e.type == "tool_call") >= 3

    # Acceptance 2: structured diagnosis parsed.
    assert result.impact.get("severity") == "P0"
    assert result.impact.get("affected_services") == ["payment-svc"]
    assert result.possible_causes[0]["cause"] == "扩容不足"
    assert result.confidence == "high"
    assert "扩容" in result.next_steps[0]
    assert model.calls == 1

    # Acceptance 3: P0 triggers a Lark page through the gateway.
    assert called["lark"] == 1
    assert result.lark_notified is True
    assert any(c.tool_name == "lark_notify" and c.status == "success" for c in gateway.tool_calls)


@pytest.mark.e2e
def test_alert_diagnosis_p2_does_not_page_lark():
    model_json = (
        '{"impact": {"scope": "单个用户", "affected_services": ["profile-svc"], '
        '"severity": "P2"}, "possible_causes": [], "confidence": "medium", '
        '"next_steps": ["观察"]}'
    )
    audit, registry, gateway, model_gw, model, called = _build(
        _ES_RAW, _DB_RAW, _RAG_RAW, model_json
    )
    actor = _actor()

    result = asyncio.run(
        run_alert_diagnosis(
            "单个用户登录慢",
            actor=actor,
            registry=registry,
            gateway=gateway,
            model_gateway=model_gw,
            audit_service=audit,
            lark_chat_id="oncall-room",
        )
    )

    # P2 -> no page, lark handler never invoked.
    assert result.impact.get("severity") == "P2"
    assert called["lark"] == 0
    assert result.lark_notified is False
    # Read tools still ran and diagnosis produced.
    assert called["es"] == 1 and called["db"] == 1 and called["rag"] == 1
    assert model.calls == 1


@pytest.mark.e2e
def test_alert_diagnosis_partial_tool_failure():
    # db_query raises; workflow must still diagnose using ES + RAG.
    model_json = (
        '{"impact": {"scope": "支付链路", "affected_services": ["payment-svc"], '
        '"severity": "P1"}, "possible_causes": [], "confidence": "low", '
        '"next_steps": ["排查 DB"]}'
    )
    audit, registry, gateway, model_gw, model, called = _build(
        _ES_RAW, _DB_RAW, _RAG_RAW, model_json, db_fail=True
    )
    actor = _actor()

    result = asyncio.run(
        run_alert_diagnosis(
            "db 报错相关告警",
            actor=actor,
            registry=registry,
            gateway=gateway,
            model_gateway=model_gw,
            audit_service=audit,
            lark_chat_id="oncall-room",
        )
    )

    # db failure recorded, ES + RAG succeeded; workflow did not crash.
    assert "db_query" in result.tool_errors
    assert called["es"] == 1 and called["rag"] == 1
    assert result.impact.get("severity") == "P1"
    assert result.confidence == "low"
    # P1 still pages Lark.
    assert result.lark_notified is True
    assert called["lark"] == 1
