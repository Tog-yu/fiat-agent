"""Unit tests for D6: model usage accounting.

Covers the two acceptance criteria from DEV_SPEC D6:

* every model call emits a usage record (via ModelGateway.audit_sink)
* usage can be aggregated by task (AuditService.usage_by_task)
"""

import asyncio

import pytest
from fiat_agent.audit.service import AuditService
from fiat_agent.models.base import (
    BaseChatModel,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    TokenUsage,
)
from fiat_agent.models.gateway import ModelGateway


class _FakeModel(BaseChatModel):
    provider = "fake"

    def __init__(self, response=None, chunks=None):
        self._response = response
        self._chunks = chunks or []

    async def chat(self, request):
        return self._response

    async def stream(self, request):
        for c in self._chunks:
            yield c


@pytest.mark.unit
def test_gateway_emits_usage_on_chat():
    usage = TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    model = _FakeModel(response=ChatResponse(content="hi", usage=usage))
    calls = []

    async def sink(task_type, model_name, u):
        calls.append((task_type, model_name, u))

    gw = ModelGateway(provider_factory=lambda p, tt, c: model, audit_sink=sink)
    asyncio.run(
        gw.chat(
            ChatRequest(messages=[ChatMessage(role="user", content="x")]),
            task_type="alert_diagnosis",
        )
    )
    assert len(calls) == 1
    assert calls[0][0] == "alert_diagnosis"
    assert calls[0][2].total_tokens == 15


@pytest.mark.unit
def test_gateway_emits_usage_on_function_call():
    usage = TokenUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3)
    model = _FakeModel(response=ChatResponse(function_calls=[], usage=usage))
    calls = []

    async def sink(task_type, model_name, u):
        calls.append(u)

    gw = ModelGateway(provider_factory=lambda p, tt, c: model, audit_sink=sink)
    asyncio.run(gw.function_call(ChatRequest(messages=[]), task_type="table_parse"))
    assert len(calls) == 1
    assert calls[0].total_tokens == 3


@pytest.mark.unit
def test_gateway_merges_stream_usage():
    chunks = [
        ChatResponse(content="a", usage=TokenUsage(prompt_tokens=10, completion_tokens=1, total_tokens=11)),
        ChatResponse(content="b", usage=TokenUsage(prompt_tokens=20, completion_tokens=2, total_tokens=22)),
    ]
    model = _FakeModel(chunks=chunks)
    calls = []

    async def sink(task_type, model_name, u):
        calls.append(u)

    gw = ModelGateway(provider_factory=lambda p, tt, c: model, audit_sink=sink)

    async def run():
        async for _ in gw.stream(ChatRequest(messages=[]), task_type="rag_qa"):
            pass

    asyncio.run(run())
    # stream usage is merged into a single emission
    assert len(calls) == 1
    assert calls[0].prompt_tokens == 30
    assert calls[0].completion_tokens == 3
    assert calls[0].total_tokens == 33


@pytest.mark.unit
def test_gateway_without_sink_does_not_raise():
    model = _FakeModel(response=ChatResponse(content="hi", usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2)))
    gw = ModelGateway(provider_factory=lambda p, tt, c: model)
    out = asyncio.run(gw.chat(ChatRequest(messages=[]), task_type="rag_qa"))
    assert out.usage.total_tokens == 2


@pytest.mark.unit
def test_audit_service_records_and_aggregates_by_task():
    svc = AuditService()

    async def run():
        await svc.record_model_usage(
            task_type="alert_diagnosis", model="gpt-x",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )
        await svc.record_model_usage(
            task_type="alert_diagnosis", model="gpt-x",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )
        await svc.record_model_usage(
            task_type="rag_qa", model="deepseek",
            usage=TokenUsage(prompt_tokens=3, completion_tokens=1, total_tokens=4),
        )
        return (
            await svc.usage_by_task("alert_diagnosis"),
            await svc.usage_by_task("rag_qa"),
            await svc.usage_by_task("nonexistent"),
        )

    a, r, z = asyncio.run(run())
    assert a.prompt_tokens == 20 and a.completion_tokens == 10 and a.total_tokens == 30
    assert r.prompt_tokens == 3 and r.total_tokens == 4
    assert z.total_tokens == 0
