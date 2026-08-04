"""Agent API service layer (phase I1, DEV_SPEC §I1).

Bridges the FastAPI :mod:`apps.api.routes.agent` endpoints to the agent runtime:

* the append-only :class:`~fiat_agent.sessions.store.SessionStore` for
  sessions / events, and
* the :class:`~fiat_agent.orchestrator.graph.AgentGraph` LangGraph orchestrator.

The service is intentionally small and dependency-injectable: the FastAPI
dependency :func:`get_agent_service` returns a lazily-built production instance,
and tests override it with a fully hermetic instance (fake model + fake tool
handlers + a temporary sqlite database) via ``app.dependency_overrides``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from fiat_agent.audit.service import AuditService
from fiat_agent.auth.rbac import load_tool_policies
from fiat_agent.db import get_async_engine
from fiat_agent.models.gateway import ModelGateway
from fiat_agent.orchestrator.graph import AgentGraph
from fiat_agent.orchestrator.state import ApprovalState
from fiat_agent.schemas.common import ActorContext, TaskType
from fiat_agent.sessions.store import SessionStore
from fiat_agent.tools.registry import ToolRegistry
from fiat_agent.tools.schemas import ToolDefinition


async def _create_tables(engine: AsyncEngine) -> None:
    """Create the session/event tables the service needs (idempotent)."""
    from fiat_agent.models.orm import Base

    # Importing the store module registers its ORM models on ``Base`` so
    # ``create_all`` knows about them.
    import fiat_agent.sessions.store  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _read(result: Any, key: str) -> Any:
    """Read a field from either a ``GraphState`` or a raw state dict."""
    if isinstance(result, dict):
        return result.get(key)
    return getattr(result, key, None)


# --- production tool handlers ---------------------------------------------


async def _rag_query_handler(actor: ActorContext, args: dict, ctx: Any) -> dict:
    """Real RAG query handler: spins up the RAG MCP client per call.

    Returns a structured dict (never raw text) so the agent loop and the
    session event store stay consistent. Degrades gracefully when the server
    is not configured or fails (DEV_SPEC E6).
    """
    from fiat_agent.config import load_settings
    from fiat_agent.mcp_clients.content_parser import parse_mcp_contents
    from fiat_agent.mcp_clients.rag_mcp_client import RagMcpClient

    cfg = load_settings().mcp_servers.get("rag")
    if cfg is None or not cfg.name:
        return {"status": "unavailable", "reason": "RAG MCP server 未配置"}
    try:
        async with RagMcpClient(cfg) as client:
            items = await client.query_knowledge_hub(
                args.get("query", ""),
                top_k=args.get("top_k", 5),
                collection=args.get("collection"),
            )
            parsed = parse_mcp_contents(items)
            return {
                "status": "ok",
                "answer": parsed.text_context,
                "citations": parsed.metadata,
            }
    except Exception as exc:  # noqa: BLE001 - normalize, don't leak
        return {"status": "error", "reason": str(exc)}


def _unavailable_handler_for(name: str):
    """Handler for tools whose backend adapter is not wired into the MVP build.

    Returns a deterministic structured message so the agent loop still produces
    a coherent final answer instead of crashing (the behavior is audited by the
    Tool Gateway regardless).
    """

    async def _handler(actor: ActorContext, args: dict, ctx: Any) -> dict:
        return {
            "status": "unavailable",
            "reason": f"工具 '{name}' 的后端适配尚未在 MVP 接入",
        }

    return _handler


class AgentService:
    """High-level session + message API backed by the session store and graph."""

    def __init__(
        self,
        *,
        store: SessionStore,
        graph: AgentGraph,
        engine: AsyncEngine,
    ) -> None:
        self._store = store
        self._graph = graph
        self._engine = engine

    async def create_session(
        self,
        *,
        title: str = "",
        task_type: str | None = None,
        environment: str = "dev",
        actor_id: str | None = None,
    ) -> dict:
        """Create a new task session and return its public view."""
        if self._engine is None:
            raise RuntimeError("数据库未配置（database.url 为空），无法创建会话")
        from fiat_agent.db import session_scope

        async with session_scope(engine=self._engine) as session:
            ts = await self._store.create_session(
                session,
                title=title,
                task_type=task_type,
                environment=environment,
                actor_id=actor_id,
            )
            return {
                "session_id": ts.id,
                "title": ts.title,
                "task_type": ts.task_type,
                "environment": ts.environment,
                "status": ts.status,
            }

    async def run_message(
        self, *, session_id: str, actor: ActorContext, content: str
    ) -> dict:
        """Append a user turn, run the agent graph, and persist the result.

        Persists the inbound user message and the outbound assistant answer as
        ``message`` events, and streams every graph step (classify / plan /
        tool_call / approval / final) into the session event store via the
        graph's ``session_writer`` callback.
        """
        from fiat_agent.db import session_scope
        from fiat_agent.models.base import ChatMessage

        # Guard: session must exist before we append anything.
        if self._engine is None:
            raise RuntimeError("数据库未配置（database.url 为空），无法运行会话")
        async with session_scope(engine=self._engine) as session:
            existing = await self._store._repo.get_session(session, session_id)
            if existing is None:
                raise _SessionNotFound(session_id)

        async with session_scope(engine=self._engine) as session:
            await self._store.append_event(
                session,
                session_id=session_id,
                event_type="message",
                content={"role": "user", "content": content},
            )

        async def session_writer(event_type: str, payload: dict) -> None:
            async with session_scope(engine=self._engine) as s:
                await self._store.append_event(
                    s,
                    session_id=session_id,
                    event_type=event_type,
                    content=payload,
                )

        result = await self._graph.arun(
            actor=actor,
            messages=[ChatMessage(role="user", content=content)],
            session_id=session_id,
            session_writer=session_writer,
        )

        final_answer = _read(result, "final_answer")
        task_type = _read(result, "task_type")
        approval_state = _read(result, "approval_state") or ApprovalState.NOT_REQUIRED
        pending = _read(result, "pending_approvals") or []

        assistant_event = {
            "role": "assistant",
            "content": final_answer or "",
            "approval_state": (
                approval_state.value
                if isinstance(approval_state, ApprovalState)
                else str(approval_state)
            ),
            "pending_tools": list(pending),
        }
        if isinstance(task_type, TaskType):
            assistant_event["task_type"] = task_type.value
        elif task_type is not None:
            assistant_event["task_type"] = str(task_type)

        async with session_scope(engine=self._engine) as session:
            await self._store.append_event(
                session,
                session_id=session_id,
                event_type="message",
                content=assistant_event,
            )

        return {
            "session_id": session_id,
            "final_answer": final_answer,
            "task_type": assistant_event.get("task_type"),
            "approval_state": assistant_event["approval_state"],
            "pending_tools": assistant_event["pending_tools"],
        }

    async def list_events(self, *, session_id: str) -> list[dict]:
        """Return all session events in stable ``seq`` order."""
        if self._engine is None:
            raise RuntimeError("数据库未配置（database.url 为空），无法读取事件")
        from fiat_agent.db import session_scope

        async with session_scope(engine=self._engine) as session:
            events = await self._store.list_session_events(session, session_id)
            return [
                {
                    "event_id": e.id,
                    "event_type": e.event_type,
                    "seq": e.seq,
                    "content": e.content,
                    "created_at": e.created_at.isoformat()
                    if e.created_at is not None
                    else None,
                }
                for e in events
            ]


class _SessionNotFound(Exception):
    """Raised when an API operation targets a session that does not exist."""

    def __init__(self, session_id: str) -> None:
        super().__init__(f"session '{session_id}' not found")
        self.session_id = session_id


async def build_agent_service(
    settings=None, *, engine: AsyncEngine | None = None
) -> AgentService:
    """Build a production :class:`AgentService` from config.

    Wires the real ToolRegistry (from ``config/tool_policies.yaml``), the audited
    ToolGateway, and the routing ModelGateway. RAG is wired to the real MCP
    server; pure read-only tools (cashback parse, logistics validate) use their
    module handler factories; the remaining backend-gated tools return a clear
    "not wired in MVP" message rather than crashing.

    The database is optional: when ``database.url`` is not configured the service
    runs with ``engine=None`` and every DB-backed method raises a clear error
    (rather than crashing at import / first request). This keeps the app usable
    in environments that only need the health/session-less surfaces.
    """
    if settings is None:
        from fiat_agent.config import load_settings

        settings = load_settings()

    engine = engine or _try_get_engine(settings)
    if engine is not None:
        await _create_tables(engine)

    store = SessionStore()
    audit = AuditService()  # in-memory; swap for a DB-backed repo in a later phase

    registry = ToolRegistry()
    for name, policy in load_tool_policies().items():
        registry.register(
            ToolDefinition(
                name=name,
                description=name,
                risk_level=policy.risk_level,
                approval_required=policy.approval_required,
            )
        )

    gateway = ToolGateway(audit)
    gateway.register_handler("rag_query", _rag_query_handler)
    from fiat_agent.tool_gateway.cashback_tools import make_cashback_parse_handler
    from fiat_agent.tool_gateway.logistics_tools import make_logistics_validate_handler

    gateway.register_handler("cashback_parse", make_cashback_parse_handler())
    gateway.register_handler("logistics_validate", make_logistics_validate_handler())
    for name in ("es_query", "db_query", "lark_notify", "test_env", "cashback_reconcile"):
        gateway.register_handler(name, _unavailable_handler_for(name))

    model_gateway = ModelGateway(
        audit_sink=lambda task_type, model, usage: audit.record_model_usage(
            task_type=task_type, model=model, usage=usage
        )
    )

    graph = AgentGraph(
        registry=registry,
        gateway=gateway,
        model_gateway=model_gateway,
        audit_service=audit,
    )
    return AgentService(store=store, graph=graph, engine=engine)


def _try_get_engine(settings) -> AsyncEngine | None:
    """Return an async engine, or ``None`` when ``database.url`` is unset.

    ``get_async_engine`` fail-fasts when the URL is empty; the API must degrade
    gracefully instead of refusing to boot (DEV_SPEC B1: DB-agnostic, SQLite is
    the zero-ops default but need not be mandatory for every deployment).
    """
    url = getattr(getattr(settings, "database", None), "url", None)
    if not url:
        return None
    return get_async_engine(settings)


_service: AgentService | None = None


async def get_agent_service() -> AgentService:
    """FastAPI dependency returning a lazily-built, process-wide agent service.

    Tests override this via ``app.dependency_overrides[get_agent_service]`` with
    a hermetic instance (no real LLM / MCP server / DB).
    """
    global _service
    if _service is None:
        _service = await build_agent_service()
    return _service
