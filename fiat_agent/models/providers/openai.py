"""OpenAI-compatible provider (phase D2, DEV_SPEC D2).

Implements :class:`~fiat_agent.models.base.BaseChatModel` against any
OpenAI-compatible ``/v1/chat/completions`` endpoint. OpenAI, DeepSeek, and the
private relays (My Codex / 晓 / Right Code) all speak this wire format, so a
single class serves every OpenAI-compatible backend by varying ``base_url`` /
``api_key`` / ``model`` — see ``config/model_policies.yaml`` (D3).

API-key hygiene
---------------
The key is only ever used to authenticate the outgoing HTTP request. It is
*never* copied into :class:`~fiat_agent.models.base.ChatResponse.raw`, so
responses can be serialized for audit/export/replay without leaking secrets
(DEV_SPEC D2 acceptance: 不泄露 API key).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any, Optional

from openai import AsyncOpenAI

from fiat_agent.models.base import (
    BaseChatModel,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    FunctionCall,
    TokenUsage,
)


def _resolve_api_key(
    api_key: Optional[str], api_key_env: Optional[str]
) -> Optional[str]:
    """Pick the API key: explicit arg wins, else an env var, else None.

    Callers pass the resulting value into the OpenAI client; when it is None a
    harmless placeholder is used so construction never fails offline.
    """
    if api_key is not None:
        return api_key
    if api_key_env:
        return os.environ.get(api_key_env)
    return None


def _to_openai_messages(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    """Convert neutral :class:`ChatMessage` list to OpenAI message dicts."""
    out: list[dict[str, Any]] = []
    for m in messages:
        item: dict[str, Any] = {"role": m.role}
        if m.content is not None:
            item["content"] = m.content
        if m.name:
            item["name"] = m.name
        if m.tool_call_id:
            item["tool_call_id"] = m.tool_call_id
        if m.tool_calls:
            item["tool_calls"] = [
                {
                    "id": tc.id or "",
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.arguments or ""},
                }
                for tc in m.tool_calls
            ]
        out.append(item)
    return out


class OpenAIChatModel(BaseChatModel):
    """Chat model for any OpenAI-compatible ``/v1/chat/completions`` endpoint."""

    provider: str = "openai"

    def __init__(
        self,
        model: str,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key_env: Optional[str] = None,
        timeout: float = 120.0,
        max_retries: int = 2,
        default_temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        client: Optional[AsyncOpenAI] = None,
    ) -> None:
        self.model = model
        self._default_temperature = default_temperature
        self._max_tokens = max_tokens
        if client is not None:
            self._client = client
        else:
            self._client = AsyncOpenAI(
                api_key=_resolve_api_key(api_key, api_key_env) or "sk-placeholder",
                base_url=base_url,
                timeout=timeout,
                max_retries=max_retries,
            )

    # --- request building -------------------------------------------------

    def _request_kwargs(self, request: ChatRequest) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": request.model or self.model,
            "messages": _to_openai_messages(request.messages),
            "stream": False,
        }
        if request.tools:
            kwargs["tools"] = request.tools
            kwargs["tool_choice"] = (
                request.tool_choice if request.tool_choice is not None else "auto"
            )
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        elif self._default_temperature is not None:
            kwargs["temperature"] = self._default_temperature
        if request.max_tokens is not None:
            kwargs["max_tokens"] = request.max_tokens
        elif self._max_tokens is not None:
            kwargs["max_tokens"] = self._max_tokens
        return kwargs

    # --- BaseChatModel ----------------------------------------------------

    async def chat(self, request: ChatRequest) -> ChatResponse:
        resp = await self._client.chat.completions.create(
            **self._request_kwargs(request)
        )
        return self._normalize(resp)

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatResponse]:
        kwargs = self._request_kwargs(request)
        kwargs["stream"] = True
        stream = await self._client.chat.completions.create(**kwargs)
        async for chunk in stream:
            yield self._normalize_chunk(chunk)

    # --- normalization ----------------------------------------------------

    @staticmethod
    def _usage(oa_usage: Any) -> Optional[TokenUsage]:
        if oa_usage is None:
            return None
        return TokenUsage(
            prompt_tokens=getattr(oa_usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(oa_usage, "completion_tokens", 0) or 0,
            total_tokens=getattr(oa_usage, "total_tokens", 0) or 0,
        )

    def _normalize(self, resp: Any) -> ChatResponse:
        choice = resp.choices[0]
        message = choice.message
        function_calls: Optional[list[FunctionCall]] = None
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            function_calls = [
                FunctionCall(
                    name=tc.function.name,
                    arguments=tc.function.arguments or "",
                    id=tc.id,
                )
                for tc in tool_calls
            ]
        return ChatResponse(
            model=getattr(resp, "model", None),
            content=getattr(message, "content", None),
            function_calls=function_calls,
            usage=self._usage(getattr(resp, "usage", None)),
            finish_reason=getattr(choice, "finish_reason", None),
            raw=resp.model_dump() if hasattr(resp, "model_dump") else None,
        )

    def _normalize_chunk(self, chunk: Any) -> ChatResponse:
        choice = chunk.choices[0] if getattr(chunk, "choices", None) else None
        content = None
        function_calls = None
        finish_reason = None
        if choice is not None:
            delta = getattr(choice, "delta", None)
            if delta is not None:
                content = getattr(delta, "content", None)
                delta_tcs = getattr(delta, "tool_calls", None)
                if delta_tcs:
                    function_calls = [
                        FunctionCall(
                            name=getattr(tc.function, "name", None) or "",
                            arguments=getattr(tc.function, "arguments", None) or "",
                            id=getattr(tc, "id", None),
                        )
                        for tc in delta_tcs
                    ]
            finish_reason = getattr(choice, "finish_reason", None)
        return ChatResponse(
            model=getattr(chunk, "model", None),
            content=content,
            function_calls=function_calls,
            usage=self._usage(getattr(chunk, "usage", None)),
            finish_reason=finish_reason,
            raw=chunk.model_dump() if hasattr(chunk, "model_dump") else None,
        )
