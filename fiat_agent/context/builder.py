"""Context builder (phase G3, DEV_SPEC §G3 / §6.3).

Assembles the model-facing run context: a system prompt, the **permission-
filtered** tool schemas (only what the actor may use), short/long-term memory,
and the RAG answer with its citations. The filtering reuses the deterministic
:func:`fiat_agent.auth.policy.filter_tools` (F2/ToolRegistry), so the model is
never shown tools it couldn't call.
"""

from __future__ import annotations

from typing import Any, Optional

from fiat_agent.rag.context_merge import MergedRagContext
from fiat_agent.schemas.common import ActorContext, FiatModel, TaskType
from fiat_agent.tools.function_calling import to_openai_tool_schema
from fiat_agent.tools.registry import ToolRegistry


class BuiltContext(FiatModel):
    """The assembled, model-ready context for one turn."""

    system_prompt: str = ""
    tool_schemas: list[dict[str, Any]] = []
    memory: str = ""
    rag_context: str = ""  # RAG answer + attached citations


_DEFAULT_SYSTEM = (
    "你是 fiat-agent，一个面向法币业务的内部 Agent。"
    "严格遵守权限与审批边界：只能调用被授予的工具，高危操作必须经审批。"
    "对无依据的问题如实说明无法确认。"
)


class ContextBuilder:
    """Builds the system prompt + tool schemas + memory + RAG context."""

    def __init__(self, base_system_prompt: str = _DEFAULT_SYSTEM) -> None:
        self._base = base_system_prompt

    def build_system_prompt(
        self,
        actor: ActorContext,
        task_type: Optional[TaskType] = None,
        memory: str = "",
    ) -> str:
        """Compose the system prompt from the base, task and memory sections."""
        parts = [self._base]
        if task_type is not None:
            parts.append(f"当前任务类型：{task_type.value}。")
        if memory:
            parts.append(f"记忆：\n{memory}")
        return "\n".join(parts)

    def build_tool_schemas(
        self,
        actor: ActorContext,
        registry: ToolRegistry,
        environment: Any = None,
    ) -> list[dict[str, Any]]:
        """Return OpenAI-style tool schemas for tools the actor may use.

        Filtering is delegated to ``ToolRegistry.filter`` -> ``filter_tools``
        (deterministic RBAC), so only permission-allowed tools are exposed.
        """
        allowed = registry.filter(actor, environment=environment)
        return [to_openai_tool_schema(t) for t in allowed]

    def build(
        self,
        actor: ActorContext,
        registry: ToolRegistry,
        task_type: Optional[TaskType] = None,
        memory: str = "",
        rag_context: Optional[MergedRagContext] = None,
        environment: Any = None,
    ) -> BuiltContext:
        """Assemble the full context for one turn."""
        rag_text = rag_context.context if rag_context is not None else ""
        return BuiltContext(
            system_prompt=self.build_system_prompt(actor, task_type, memory),
            tool_schemas=self.build_tool_schemas(actor, registry, environment),
            memory=memory,
            rag_context=rag_text,
        )
