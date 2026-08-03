"""Model Gateway — unified LLM interface (phase D1, DEV_SPEC D1).

Defines the provider-agnostic chat contract used by the orchestrator and Tool
Gateway. Concrete providers (OpenAI / Anthropic / private, phase D2+) subclass
:class:`BaseChatModel`; the request/response schemas are Pydantic v2 models so
they are validated and JSON-serializable.

The ORM declarative ``Base`` now lives in :mod:`fiat_agent.models.orm` (phase
B2) so the persistence layer and the LLM contract stay cleanly separated.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any, ClassVar, Optional

from pydantic import BaseModel, Field


# --- LLM contract ---------------------------------------------------------


class TokenUsage(BaseModel):
    """Token accounting for a single model call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class FunctionCall(BaseModel):
    """A single tool invocation requested by the model.

    ``arguments`` is a JSON *string* (provider-neutral): every backend emits
    tool args as a string, so callers parse it on demand via ``json.loads``.
    """

    name: str
    arguments: str = Field(default="")
    id: Optional[str] = None


class ChatMessage(BaseModel):
    """One turn in a conversation, loosely mirroring the OpenAI message shape."""

    role: str
    content: Optional[str] = None
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[list[FunctionCall]] = None


class ChatRequest(BaseModel):
    """Provider-neutral chat request."""

    model: Optional[str] = None
    messages: list[ChatMessage]
    tools: Optional[list[dict[str, Any]]] = None
    tool_choice: Optional[Any] = None
    stream: bool = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    """Provider-neutral chat response.

    Every response carries ``usage`` so the gateway can do cost/token accounting
    (DEV_SPEC D6). Either ``content`` (text) or ``function_calls`` (tool calls)
    is populated, depending on the model turn.
    """

    model: Optional[str] = None
    content: Optional[str] = None
    function_calls: Optional[list[FunctionCall]] = None
    usage: Optional[TokenUsage] = None
    finish_reason: Optional[str] = None
    raw: Optional[dict[str, Any]] = None


class BaseChatModel(ABC):
    """Unified chat-model interface.

    Subclasses implement :meth:`chat` (one non-streaming turn, returning text
    and/or function calls) and :meth:`stream` (yielding partial
    :class:`ChatResponse` chunks). :meth:`function_call` is a thin convenience
    over :meth:`chat` for tool-calling flows — the actual tool-execution loop
    lives in the orchestrator / Tool Gateway, not in the model client.
    """

    provider: ClassVar[str] = "base"

    @abstractmethod
    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Run one (non-streaming) chat turn. Returns text and/or function calls."""
        raise NotImplementedError

    @abstractmethod
    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatResponse]:
        """Stream a chat turn, yielding partial :class:`ChatResponse` chunks."""
        yield  # pragma: no cover  (abstract async generator; overridden by subclasses)

    async def function_call(self, request: ChatRequest) -> ChatResponse:
        """Convenience: run a chat turn that may request tool calls.

        Returns the :class:`ChatResponse` from :meth:`chat`, which carries any
        ``function_calls`` the model produced. Does not execute tools itself.
        """
        return await self.chat(request)
