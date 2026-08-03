"""Model Gateway (phase D3, DEV_SPEC D3).

Thin orchestration layer over the routing policy: pick the right
:class:`~fiat_agent.models.base.BaseChatModel` for a task and delegate
``chat`` / ``stream`` / ``function_call``.

Usage accounting (D6) and audit hooks plug in here later without changing the
selection contract — callers keep passing ``task_type`` / ``complexity``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Callable, Optional

from fiat_agent.models.base import BaseChatModel, ChatRequest, ChatResponse
from fiat_agent.models.policies import (
    ModelPolicies,
    load_model_policies,
    select_provider,
)


class ModelGateway:
    """Selects a provider per task and delegates chat calls to it."""

    def __init__(
        self,
        policies: Optional[ModelPolicies] = None,
        *,
        provider_factory: Optional[Callable[..., BaseChatModel]] = None,
    ) -> None:
        self.policies = policies or load_model_policies()
        self._factory = provider_factory

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
        return await model.chat(request)

    async def stream(
        self,
        request: ChatRequest,
        *,
        task_type: Optional[str] = None,
        complexity: Optional[str] = None,
    ) -> AsyncIterator[ChatResponse]:
        model = self.select(task_type=task_type, complexity=complexity)
        async for chunk in model.stream(request):
            yield chunk

    async def function_call(
        self,
        request: ChatRequest,
        *,
        task_type: Optional[str] = None,
        complexity: Optional[str] = None,
    ) -> ChatResponse:
        model = self.select(task_type=task_type, complexity=complexity)
        return await model.function_call(request)
