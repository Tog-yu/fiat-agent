"""Model Gateway (phase D3, DEV_SPEC D3).

Thin orchestration layer over the routing policy: pick the right
:class:`~fiat_agent.models.base.BaseChatModel` for a task and delegate
``chat`` / ``stream`` / ``function_call``.

Usage accounting (D6) plugs in via the optional ``audit_sink``: every model
call emits its :class:`~fiat_agent.models.base.TokenUsage` to the sink, which the
caller wires to :class:`~fiat_agent.audit.service.AuditService`. This keeps the
gateway free of any DB/session knowledge.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Awaitable, Callable, Optional

from fiat_agent.models.base import BaseChatModel, ChatRequest, ChatResponse
from fiat_agent.models.policies import (
    ModelPolicies,
    load_model_policies,
    select_provider,
)

# (task_type, model_name, usage) -> recorded. Awaitable so a real sink can do IO.
AuditSink = Callable[[Optional[str], str, Any], Awaitable[None]]


class ModelGateway:
    """Selects a provider per task and delegates chat calls to it."""

    def __init__(
        self,
        policies: Optional[ModelPolicies] = None,
        *,
        provider_factory: Optional[Callable[..., BaseChatModel]] = None,
        audit_sink: Optional[AuditSink] = None,
    ) -> None:
        self.policies = policies or load_model_policies()
        self._factory = provider_factory
        self._audit_sink = audit_sink

    def select(
        self,
        task_type: Optional[str] = None,
        complexity: Optional[str] = None,
    ) -> BaseChatModel:
        """Return the :class:`BaseChatModel` for this task.

        ``provider_factory`` (if set) is called as
        ``factory(policies, task_type, complexity)`` — used for tests/injection.
        """
        if self._factory is not None:
            return self._factory(self.policies, task_type, complexity)
        return select_provider(
            self.policies, task_type=task_type, complexity=complexity
        )

    async def chat(
        self,
        request: ChatRequest,
        *,
        task_type: Optional[str] = None,
        complexity: Optional[str] = None,
    ) -> ChatResponse:
        model = self.select(task_type=task_type, complexity=complexity)
        response = await model.chat(request)
        await self._emit_usage(task_type, request, model, response)
        return response

    async def function_call(
        self,
        request: ChatRequest,
        *,
        task_type: Optional[str] = None,
        complexity: Optional[str] = None,
    ) -> ChatResponse:
        model = self.select(task_type=task_type, complexity=complexity)
        response = await model.function_call(request)
        await self._emit_usage(task_type, request, model, response)
        return response

    async def stream(
        self,
        request: ChatRequest,
        *,
        task_type: Optional[str] = None,
        complexity: Optional[str] = None,
    ) -> AsyncIterator[ChatResponse]:
        model = self.select(task_type=task_type, complexity=complexity)
        model_name = self._model_name(request, model)
        merged: Optional[Any] = None
        async for chunk in model.stream(request):
            if chunk.usage is not None:
                merged = _merge_usage(merged, chunk.usage)
            yield chunk
        if self._audit_sink is not None and merged is not None:
            await self._audit_sink(task_type, model_name, merged)

    def _model_name(self, request: ChatRequest, model: BaseChatModel) -> str:
        return (
            request.model
            or getattr(model, "model", None)
            or getattr(model, "provider", "unknown")
        )

    async def _emit_usage(
        self,
        task_type: Optional[str],
        request: ChatRequest,
        model: BaseChatModel,
        response: ChatResponse,
    ) -> None:
        if self._audit_sink is None or response.usage is None:
            return
        await self._audit_sink(task_type, self._model_name(request, model), response.usage)


def _merge_usage(a: Optional[Any], b: Any) -> Any:
    """Sum two TokenUsage-shaped objects; returns a new instance of ``b``'s type."""
    if a is None:
        return b
    cls = type(b)
    return cls(
        prompt_tokens=a.prompt_tokens + b.prompt_tokens,
        completion_tokens=a.completion_tokens + b.completion_tokens,
        total_tokens=a.total_tokens + b.total_tokens,
    )
