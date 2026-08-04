"""Claude Code MCP adapter (DEV_SPEC §I5).

Exposes fiat-agent capabilities as an MCP server so Claude Code (or any MCP
client) can call them. Every tool routes through the same audited
:class:`~fiat_agent.tool_gateway.gateway.ToolGateway` the rest of the system
uses, so calls are subject to the deterministic RBAC policy (``can_execute``)
and are written to the audit trail — never bypassing fiat-agent permission/audit.

External tool names (what MCP clients see) map to internal fiat tool names:
  fiat.rag_search       -> rag_query
  fiat.alert_diagnose   -> alert_diagnosis
  fiat.cashback_parse   -> cashback_parse
  fiat.logistics_validate -> logistics_validate
  fiat.es_query         -> es_query
  fiat.db_query         -> db_query
  fiat.lark_notify      -> lark_notify
  fiat.test_env         -> test_env
  fiat.cashback_reconcile -> cashback_reconcile

The MCP server runs over stdio (``python -m adapters.claude_code_mcp.server``).
For hermetic testing, call :func:`dispatch` directly with an injected
:class:`FiatMcpContext` (tests set ``server._context``).
"""

from __future__ import annotations

from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from fiat_agent.audit.service import AuditService
from fiat_agent.schemas.common import ActorContext, Environment
from fiat_agent.tool_gateway.gateway import ToolGateway

# external MCP tool name -> internal fiat tool name
_TOOL_MAP: dict[str, str] = {
    "fiat.rag_search": "rag_query",
    "fiat.alert_diagnose": "alert_diagnosis",
    "fiat.cashback_parse": "cashback_parse",
    "fiat.logistics_validate": "logistics_validate",
    "fiat.es_query": "es_query",
    "fiat.db_query": "db_query",
    "fiat.lark_notify": "lark_notify",
    "fiat.test_env": "test_env",
    "fiat.cashback_reconcile": "cashback_reconcile",
}

# Default actor roles when an MCP caller does not specify one.
_DEFAULT_ROLES = ["oncall"]


class FiatMcpContext:
    """Holds the wiring the MCP tools dispatch into (gateway + audit)."""

    def __init__(self, gateway: ToolGateway, audit: AuditService) -> None:
        self.gateway = gateway
        self.audit = audit


_context: FiatMcpContext | None = None


def _build_default_context() -> FiatMcpContext:
    """Lazily build the production context (mirrors ``build_agent_service`` wiring).

    Registers real handlers for the read-only tools and clear MVP stubs for the
    backend-gated ones, so an unmocked run degrades gracefully instead of crashing.
    """
    global _context
    if _context is None:
        audit = AuditService()
        gateway = ToolGateway(audit)

        from apps.api.agent_service import _rag_query_handler, _unavailable_handler_for
        from fiat_agent.tool_gateway.cashback_tools import make_cashback_parse_handler
        from fiat_agent.tool_gateway.logistics_tools import (
            make_logistics_validate_handler,
        )

        gateway.register_handler("rag_query", _rag_query_handler)
        gateway.register_handler("cashback_parse", make_cashback_parse_handler())
        gateway.register_handler("logistics_validate", make_logistics_validate_handler())
        # alert_diagnosis is read-only at the policy level; the full workflow
        # needs an LLM backend, so the MVP stub explains the wiring gap.
        gateway.register_handler(
            "alert_diagnosis", _unavailable_handler_for("alert_diagnosis")
        )
        for name in (
            "es_query",
            "db_query",
            "lark_notify",
            "test_env",
            "cashback_reconcile",
        ):
            gateway.register_handler(name, _unavailable_handler_for(name))

        _context = FiatMcpContext(gateway, audit)
    return _context


def _get_context() -> FiatMcpContext:
    return _build_default_context()


def _actor_from(
    *,
    actor_id: str = "mcp",
    roles: Any = None,
    environment: str = "dev",
) -> ActorContext:
    if isinstance(roles, str):
        roles = [r.strip() for r in roles.split(",") if r.strip()]
    return ActorContext(
        actor_id=actor_id,
        roles=list(roles or _DEFAULT_ROLES),
        environment=Environment(environment),
    )


async def dispatch(tool_name: str, args: dict, actor: ActorContext) -> dict:
    """Run one MCP tool through the audited gateway.

    Returns a small dict (``status`` / ``content`` / ``error`` / ``tool``). The
    call is always recorded to the audit trail by the gateway, whether allowed,
    denied, or errored — satisfying the "through permission and audit" criterion.
    """
    ctx = _get_context()
    internal = _TOOL_MAP.get(tool_name)
    if internal is None:
        return {
            "status": "error",
            "error": f"unknown tool '{tool_name}'",
            "tool": None,
        }
    result = await ctx.gateway.execute_tool(actor, internal, args or {})
    return {
        "status": result.status.value,
        "content": result.content,
        "error": result.error,
        "tool": internal,
    }


mcp = FastMCP("fiat-agent")


@mcp.tool(name="fiat.rag_search")
async def rag_search(
    query: str,
    top_k: int = 5,
    collection: Optional[str] = None,
    actor_id: str = "mcp",
    roles: str = "oncall",
    environment: str = "dev",
) -> dict:
    """Search the knowledge base (RAG). Returns answer + citations."""
    actor = _actor_from(actor_id=actor_id, roles=roles, environment=environment)
    return await dispatch(
        "fiat.rag_search",
        {"query": query, "top_k": top_k, "collection": collection},
        actor,
    )


@mcp.tool(name="fiat.alert_diagnose")
async def alert_diagnose(
    alert: str,
    actor_id: str = "mcp",
    roles: str = "oncall",
    environment: str = "dev",
) -> dict:
    """Diagnose an alert from its text (read-only evidence + analysis)."""
    actor = _actor_from(actor_id=actor_id, roles=roles, environment=environment)
    return await dispatch("fiat.alert_diagnose", {"alert": alert}, actor)


@mcp.tool(name="fiat.cashback_parse")
async def cashback_parse(
    file_path: str,
    sheet: Optional[str] = None,
    actor_id: str = "mcp",
    roles: str = "oncall",
    environment: str = "dev",
) -> dict:
    """Parse a cashback spreadsheet (read-only)."""
    actor = _actor_from(actor_id=actor_id, roles=roles, environment=environment)
    return await dispatch(
        "fiat.cashback_parse",
        {"file_path": file_path, "sheet": sheet},
        actor,
    )


@mcp.tool(name="fiat.logistics_validate")
async def logistics_validate(
    file_path: str,
    sheet: Optional[str] = None,
    actor_id: str = "mcp",
    roles: str = "oncall",
    environment: str = "dev",
) -> dict:
    """Validate a logistics spreadsheet against the state machine (read-only)."""
    actor = _actor_from(actor_id=actor_id, roles=roles, environment=environment)
    return await dispatch(
        "fiat.logistics_validate",
        {"file_path": file_path, "sheet": sheet},
        actor,
    )


@mcp.tool(name="fiat.es_query")
async def es_query(
    query: str,
    actor_id: str = "mcp",
    roles: str = "oncall",
    environment: str = "dev",
) -> dict:
    """Read-only Elasticsearch query (MVP backend not wired)."""
    actor = _actor_from(actor_id=actor_id, roles=roles, environment=environment)
    return await dispatch("fiat.es_query", {"query": query}, actor)


@mcp.tool(name="fiat.db_query")
async def db_query(
    query: str,
    actor_id: str = "mcp",
    roles: str = "oncall",
    environment: str = "dev",
) -> dict:
    """Read-only database query (MVP backend not wired)."""
    actor = _actor_from(actor_id=actor_id, roles=roles, environment=environment)
    return await dispatch("fiat.db_query", {"query": query}, actor)


@mcp.tool(name="fiat.lark_notify")
async def lark_notify(
    message: str,
    chat_id: str = "",
    actor_id: str = "mcp",
    roles: str = "oncall",
    environment: str = "dev",
) -> dict:
    """Send a non-destructive Lark notification (MVP backend not wired)."""
    actor = _actor_from(actor_id=actor_id, roles=roles, environment=environment)
    return await dispatch(
        "fiat.lark_notify", {"message": message, "chat_id": chat_id}, actor
    )


@mcp.tool(name="fiat.test_env")
async def test_env(
    action: str,
    actor_id: str = "mcp",
    roles: str = "oncall",
    environment: str = "dev",
) -> dict:
    """Drive test-environment automation (dev only; MVP backend not wired)."""
    actor = _actor_from(actor_id=actor_id, roles=roles, environment=environment)
    return await dispatch("fiat.test_env", {"action": action}, actor)


@mcp.tool(name="fiat.cashback_reconcile")
async def cashback_reconcile(
    file_path: str,
    actor_id: str = "mcp",
    roles: str = "oncall",
    environment: str = "dev",
) -> dict:
    """Reconcile cashback data (dry-run; MVP backend not wired)."""
    actor = _actor_from(actor_id=actor_id, roles=roles, environment=environment)
    return await dispatch(
        "fiat.cashback_reconcile", {"file_path": file_path}, actor
    )


def main() -> None:
    """Entry point: run the MCP server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
