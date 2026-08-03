"""Build-context node (phase G3, DEV_SPEC §G3).

LangGraph node that turns the current :class:`AgentState` into a built context
via :class:`fiat_agent.context.builder.ContextBuilder` and writes the
``system_prompt`` and permission-filtered ``tool_schemas`` back onto the state
for the model/plan step.
"""

from __future__ import annotations

from fiat_agent.context.builder import ContextBuilder, BuiltContext
from fiat_agent.orchestrator.state import AgentState
from fiat_agent.tools.registry import ToolRegistry


def build_context_node(state: AgentState, registry: ToolRegistry) -> dict:
    """Build the run context and return the state delta to merge.

    Returns ``{"system_prompt": ..., "tool_schemas": [...]}``. Only tools the
    actor is permitted to use are included in ``tool_schemas``.
    """
    builder = ContextBuilder()
    ctx: BuiltContext = builder.build(
        actor=state.actor,
        registry=registry,
        task_type=state.task_type,
        environment=state.actor.environment,
    )
    return {
        "system_prompt": ctx.system_prompt,
        "tool_schemas": ctx.tool_schemas,
    }
