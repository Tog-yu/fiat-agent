"""Unit tests for the OpenAI-compatible provider (phase D2, DEV_SPEC D2).

HTTP is mocked at the transport layer (httpx.MockTransport) for non-streaming
calls, and the streaming path is exercised with a fake client that yields
``ChatCompletionChunk`` objects — no network, no real API key needed. The API
key is asserted to never appear in the serialized response.

Async coroutines are driven via ``asyncio.run`` (the project pins no
pytest-asyncio plugin; see tests/unit/test_model_base.py for the same pattern).
"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_chunk import ChoiceDelta

from fiat_agent.models.base import ChatMessage, ChatRequest, ChatResponse
from fiat_agent.models.providers.openai import (
    OpenAIChatModel,
    _resolve_api_key,
)


def _mock_client(handler) -> AsyncOpenAI:
    """Build an AsyncOpenAI whose HTTP is fully mocked by ``handler``."""
    transport = httpx.MockTransport(handler)
    return AsyncOpenAI(
        api_key="sk-test-xxxx",
        base_url="http://test.local/v1",
        http_client=httpx.AsyncClient(transport=transport),
    )


# --- key resolution -------------------------------------------------------


@pytest.mark.unit
def test_resolve_api_key_explicit_wins() -> None:
    assert _resolve_api_key("a", "ENV") == "a"


@pytest.mark.unit
def test_resolve_api_key_from_env(monkeypatch) -> None:
    monkeypatch.setenv("FIAT_TEST_KEY", "b")
    assert _resolve_api_key(None, "FIAT_TEST_KEY") == "b"


@pytest.mark.unit
def test_resolve_api_key_missing_returns_none() -> None:
    assert _resolve_api_key(None, None) is None


# --- non-streaming chat (HTTP mocked) ------------------------------------


@pytest.mark.unit
def test_chat_text_with_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "model": "gpt-5.6-terra",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "hello"},
                    }
                ],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 2,
                    "total_tokens": 7,
                },
            },
        )

    async def _run() -> None:
        model = OpenAIChatModel("gpt-5.6-terra", client=_mock_client(handler))
        resp = await model.chat(
            ChatRequest(messages=[ChatMessage(role="user", content="hi")])
        )
        assert resp.content == "hello"
        assert resp.finish_reason == "stop"
        assert resp.model == "gpt-5.6-terra"
        assert resp.usage is not None
        assert resp.usage.total_tokens == 7
        assert resp.usage.prompt_tokens == 5
        assert resp.function_calls is None

    asyncio.run(_run())


@pytest.mark.unit
def test_chat_function_call() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "c1",
                "model": "gpt-5.6-terra",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "get_weather",
                                        "arguments": '{"city":"BJ"}',
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 4,
                    "total_tokens": 14,
                },
            },
        )

    async def _run() -> None:
        model = OpenAIChatModel("gpt-5.6-terra", client=_mock_client(handler))
        req = ChatRequest(
            messages=[ChatMessage(role="user", content="weather?")],
            tools=[
                {
                    "type": "function",
                    "function": {"name": "get_weather", "parameters": {}},
                }
            ],
        )
        resp = await model.chat(req)
        assert resp.function_calls
        fc = resp.function_calls[0]
        assert fc.name == "get_weather"
        assert fc.id == "call_1"
        assert json.loads(fc.arguments) == {"city": "BJ"}

    asyncio.run(_run())


@pytest.mark.unit
def test_api_key_not_leaked_in_raw() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={
                "id": "c",
                "model": "m",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "ok"},
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            },
        )

    async def _run() -> None:
        model = OpenAIChatModel("m", client=_mock_client(handler))
        resp = await model.chat(
            ChatRequest(messages=[ChatMessage(role="user", content="hi")])
        )
        raw_str = json.dumps(resp.raw or {})
        # The key travels on the wire (Authorization header) ...
        assert captured["auth"] == "Bearer sk-test-xxxx"
        # ... but is NEVER copied into the response payload.
        assert "sk-test-xxxx" not in raw_str
        assert "sk-" not in raw_str

    asyncio.run(_run())


# --- streaming (fake client yielding chunks) -----------------------------


class _FakeCompletions:
    def __init__(self, chunks: list[ChatCompletionChunk]):
        self._chunks = chunks

    async def create(self, **kwargs):
        async def gen() -> AsyncIterator[ChatCompletionChunk]:
            for c in self._chunks:
                yield c

        return gen()


class _FakeClient:
    def __init__(self, chunks: list[ChatCompletionChunk]):
        self.chat = type("Chat", (), {"completions": _FakeCompletions(chunks)})()


def _chunk(content: str | None = None, finish_reason: str | None = None):
    delta = ChoiceDelta(content=content)
    return ChatCompletionChunk(
        id="s1",
        model="gpt-5.6-terra",
        created=0,
        object="chat.completion.chunk",
        choices=[{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    )


@pytest.mark.unit
def test_stream_yields_chunks() -> None:
    chunks = [
        _chunk(content="He"),
        _chunk(content="llo"),
        _chunk(finish_reason="stop"),
    ]

    async def _run() -> None:
        model = OpenAIChatModel("gpt-5.6-terra", client=_FakeClient(chunks))
        collected: list[ChatResponse] = [
            c
            async for c in model.stream(
                ChatRequest(messages=[ChatMessage(role="user", content="hi")])
            )
        ]
        assert len(collected) == 3
        assert "".join(c.content or "" for c in collected) == "Hello"
        assert collected[-1].finish_reason == "stop"

    asyncio.run(_run())
