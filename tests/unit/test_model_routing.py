"""Unit tests for model routing (phase D3, DEV_SPEC D3).

Verifies task-type / complexity -> provider selection and the configurable
fallback chain, without any network call. Provider construction is exercised
(real OpenAIChatModel objects are built but never invoked), and the gateway's
delegation is checked via an injected stub factory.
"""

import asyncio

import pytest

from fiat_agent.models.base import (
    BaseChatModel,
    ChatMessage,
    ChatRequest,
    ChatResponse,
)
from fiat_agent.models.gateway import ModelGateway
from fiat_agent.models.policies import (
    ModelPolicies,
    load_model_policies,
    resolve_tier,
    select_provider,
)
from fiat_agent.models.providers.openai import OpenAIChatModel


@pytest.fixture
def policies() -> ModelPolicies:
    return load_model_policies()


@pytest.mark.unit
def test_complex_task_routes_to_gpt(policies) -> None:
    # alert_diagnosis -> complex -> gpt (My Codex, gpt-5.6-terra)
    model = select_provider(policies, task_type="alert_diagnosis")
    assert isinstance(model, OpenAIChatModel)
    assert model.model == "gpt-5.6-terra"


@pytest.mark.unit
def test_rag_qa_falls_back_from_disabled_local_to_deepseek(policies) -> None:
    # rag_qa -> simple -> local (disabled) -> fallback medium -> deepseek
    model = select_provider(policies, task_type="rag_qa")
    assert isinstance(model, OpenAIChatModel)
    assert model.model == "deepseek-v4-flash"


@pytest.mark.unit
def test_explicit_complexity_overrides_task_tier(policies) -> None:
    model = select_provider(policies, task_type="rag_qa", complexity="complex")
    assert model.model == "gpt-5.6-terra"


@pytest.mark.unit
def test_unknown_task_uses_default_tier(policies) -> None:
    # unknown task_type -> default_tier (medium) -> deepseek
    model = select_provider(policies, task_type="does_not_exist")
    assert model.model == "deepseek-v4-flash"


@pytest.mark.unit
def test_simple_tier_resolves_via_fallback_when_local_disabled(policies) -> None:
    model = select_provider(policies, complexity="simple")
    assert model.model == "deepseek-v4-flash"


@pytest.mark.unit
def test_resolve_tier_maps_task_and_default() -> None:
    p = load_model_policies()
    assert resolve_tier(p, "alert_diagnosis") == "complex"
    assert resolve_tier(p, "rag_qa") == "simple"
    assert resolve_tier(p, "nope") == p.default_tier


@pytest.mark.unit
def test_gateway_select_uses_injected_factory() -> None:
    class Stub(BaseChatModel):
        provider = "stub"

        async def chat(self, request):
            return None

        async def stream(self, request):
            yield None

    calls: dict[str, object] = {}

    def factory(p, task_type, complexity):
        calls["task_type"] = task_type
        calls["complexity"] = complexity
        return Stub()

    gw = ModelGateway(load_model_policies(), provider_factory=factory)
    selected = gw.select(task_type="rag_qa", complexity="complex")
    assert isinstance(selected, Stub)
    assert calls == {"task_type": "rag_qa", "complexity": "complex"}


@pytest.mark.unit
def test_gateway_chat_delegates_to_selected_provider() -> None:
    class Stub(BaseChatModel):
        provider = "stub"

        async def chat(self, request):
            return ChatResponse(content="stubbed")

        async def stream(self, request):
            yield ChatResponse(content="x")

    def factory(p, task_type, complexity):
        return Stub()

    gw = ModelGateway(load_model_policies(), provider_factory=factory)

    async def _run() -> None:
        resp = await gw.chat(
            ChatRequest(messages=[ChatMessage(role="user", content="hi")]),
            task_type="rag_qa",
        )
        assert resp.content == "stubbed"

    asyncio.run(_run())
