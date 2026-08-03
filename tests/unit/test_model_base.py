"""D1 unit test: unified LLM interface (DEV_SPEC D1).

Exercises the provider-agnostic contract (chat / stream / function_call) and
schema serialization without touching a real provider or leaking an API key
(DEV_SPEC §9.2.1). A tiny in-memory stub subclasses :class:`BaseChatModel`.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import pytest

from fiat_agent.models.base import (
    BaseChatModel,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    FunctionCall,
    TokenUsage,
)


class StubChatModel(BaseChatModel):
    """Minimal in-memory model: echoes text, emits a function call when tools
    are present, and streams one char per chunk."""

    provider = "stub"

    async def chat(self, request: ChatRequest) -> ChatResponse:
        last = request.messages[-1].content or ""
        if request.tools:
            return ChatResponse(
                model=request.model,
                function_calls=[FunctionCall(name="lookup", arguments='{"q": "x"}')],
                usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                finish_reason="tool_calls",
            )
        return ChatResponse(
            model=request.model,
            content=f"echo:{last}",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            finish_reason="stop",
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatResponse]:
        text = request.messages[-1].content or ""
        for ch in text:
            yield ChatResponse(content=ch, usage=TokenUsage(completion_tokens=1))
        yield ChatResponse(
            content="",
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=len(text)),
        )


@pytest.mark.unit
def test_chat_returns_text_and_usage() -> None:
    async def _run() -> None:
        m = StubChatModel()
        req = ChatRequest(model="stub-1", messages=[ChatMessage(role="user", content="hi")])
        resp = await m.chat(req)
        assert resp.content == "echo:hi"
        assert resp.usage is not None
        assert resp.usage.total_tokens == 15
        assert resp.finish_reason == "stop"

    asyncio.run(_run())


@pytest.mark.unit
def test_function_call_returns_function_calls() -> None:
    async def _run() -> None:
        m = StubChatModel()
        req = ChatRequest(
            model="stub-1",
            messages=[ChatMessage(role="user", content="go")],
            tools=[{"type": "function", "function": {"name": "lookup"}}],
        )
        resp = await m.function_call(req)
        assert resp.function_calls is not None
        assert resp.function_calls[0].name == "lookup"
        assert resp.function_calls[0].arguments == '{"q": "x"}'

    asyncio.run(_run())


@pytest.mark.unit
def test_stream_yields_chunks_with_final_usage() -> None:
    async def _run() -> None:
        m = StubChatModel()
        req = ChatRequest(
            model="stub-1",
            messages=[ChatMessage(role="user", content="abc")],
            stream=True,
        )
        chunks = [c async for c in m.stream(req)]
        assert chunks[-1].finish_reason == "stop"
        joined = "".join(c.content or "" for c in chunks if c.content)
        assert joined == "abc"
        assert chunks[-1].usage is not None

    asyncio.run(_run())


@pytest.mark.unit
def test_schemas_are_json_serializable() -> None:
    fc = FunctionCall(name="f", arguments='{"a": 1}')
    req = ChatRequest(model="m", messages=[ChatMessage(role="user", content="hi")])
    resp = ChatResponse(
        content="ok",
        function_calls=[fc],
        usage=TokenUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
    )
    assert json.loads(resp.model_dump_json())["usage"]["total_tokens"] == 3
    assert json.loads(req.model_dump_json())["messages"][0]["role"] == "user"


@pytest.mark.unit
def test_base_chat_model_is_abstract() -> None:
    with pytest.raises(TypeError):
        BaseChatModel()  # cannot instantiate without implementing chat/stream
