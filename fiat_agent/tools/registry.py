"""Tool registry (phase F2, DEV_SPEC §6.4 / §F2).

Unifies business tools (declared in code) and MCP-derived tools (from the RAG
MCP server, E2) under a single ``name -> ToolDefinition`` map. It enforces
unique names so a business tool can never silently shadow — or be shadowed by —
an MCP tool.

Authorization stays declarative and deterministic: the ``filter`` method
delegates to :func:`fiat_agent.auth.policy.filter_tools`, which looks every
tool name up against the policies in ``config/tool_policies.yaml``. No LLM is
ever consulted for visibility.
"""

from __future__ import annotations

from typing import Iterable

from fiat_agent.auth.policy import filter_tools
from fiat_agent.schemas.common import ActorContext
from fiat_agent.tools.schemas import ToolDefinition


class DuplicateToolNameError(Exception):
    """Raised when registering a tool whose name is already registered."""


class ToolRegistry:
    """Single source of truth for every callable tool the agent may use."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    # --- registration -------------------------------------------------
    def register(self, tool: ToolDefinition) -> None:
        """Register one tool, rejecting duplicate names.

        Raises:
            DuplicateToolNameError: if ``tool.name`` is already present.
        """
        if tool.name in self._tools:
            raise DuplicateToolNameError(
                f"tool name '{tool.name}' is already registered"
            )
        self._tools[tool.name] = tool

    def register_tools(self, tools: Iterable[ToolDefinition]) -> None:
        """Bulk-register an iterable of tools (order-preserving, atomic-ish)."""
        for tool in tools:
            self.register(tool)

    async def sync_mcp_tools(self, client) -> list[ToolDefinition]:
        """Discover tools from an MCP ``client`` (E2) and register them.

        Delegates discovery to
        :func:`fiat_agent.mcp_clients.tool_registry.sync_mcp_tools` and adds each
        result. A duplicate name (business vs MCP collision) is raised rather
        than silently overwritten. Returns the discovered MCP tools.
        """
        from fiat_agent.mcp_clients.tool_registry import (
            sync_mcp_tools as _sync_mcp_tools,
        )

        mcp_tools = await _sync_mcp_tools(client)
        self.register_tools(mcp_tools)
        return mcp_tools

    # --- queries ------------------------------------------------------
    @property
    def tools(self) -> list[ToolDefinition]:
        """All registered tools (insertion order preserved)."""
        return list(self._tools.values())

    def by_name(self, name: str) -> ToolDefinition | None:
        """Look up a single tool by name, or ``None``."""
        return self._tools.get(name)

    def names(self) -> list[str]:
        """All registered tool names."""
        return list(self._tools.keys())

    def filter(
        self, actor: ActorContext, environment=None
    ) -> list[ToolDefinition]:
        """Return only the tools ``actor`` is permitted to execute.

        Tools missing a policy — or failing the role/environment gate — are
        excluded. Approval-gated tools are still returned (approval gates
        execution, not visibility).
        """
        return filter_tools(actor, self.tools, environment=environment)
