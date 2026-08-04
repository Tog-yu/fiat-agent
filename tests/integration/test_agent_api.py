"""I1 integration test: FastAPI Agent API (DEV_SPEC §I1).

Exercises the three conversation endpoints end-to-end with a fully hermetic
:class:`AgentService`: a migrated temporary sqlite database for the session
store and a fake :class:`AgentGraph` (no real LLM / MCP server / audit backend).

Run with: ``pytest -q tests/integration/test_agent_api.py``
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from apps.api.agent_service import AgentService, get_agent_service
from apps.api.main import app
from fiat_agent.config import DatabaseConfig, Settings
from fiat_agent.db import session_scope
from fiat_agent.models.orm import Base
from fiat_agent.schemas.common import ActorContext, Environment, TaskType
from fiat_agent.sessions.store import SessionStore

REPO_ROOT = Path(__file__).resolve().parents[2]


def _engine(tmp_path: Path) -> AsyncEngine:
    url = f"sqlite+aiosqlite:///{tmp_path / 'agent_api.db'}"
    engine = create_async_engine(url, future=True)
    import fiat_agent.sessions.store  # noqa: F401 - register ORM models

    async def _create() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create())
    return engine


class _FakeGraph:
    """Deterministic stand-in for :class:`AgentGraph` (no real model call).

    Echoes back the first user turn as the final answer and emits a couple of
    session events through the per-run ``session_writer`` so the API's event
    stream can be asserted.
    """

    def __init__(
        self,
        *,
        final_answer: str = "ok",
        task_type: TaskType = TaskType.RAG_QA,
        approval_state: str = "not_required",
        pending: list[str] | None = None,
    ) -> None:
        self.final_answer = final_answer
        self.task_type = task_type
        self.approval_state = approval_state
        self.pending = pending or []

    async def arun(
        self,
        *,
        actor: ActorContext,
        messages: list[Any],
        session_id: str = "",
        config: dict | None = None,
        session_writer: Any = None,
        event_emitter: Any = None,
    ) -> dict:
        user_text = ""
        for m in messages:
            if getattr(m, "role", None) == "user":
                user_text = getattr(m, "content", "") or ""
                break
        if session_writer is not None:
            await session_writer("classify", {"task_type": self.task_type.value})
            await session_writer(
                "tool_call",
                {"tools": ["rag_query"], "statuses": ["success"]},
            )
        return {
            "final_answer": self.final_answer or user_text,
            "task_type": self.task_type,
            "approval_state": self.approval_state,
            "pending_approvals": self.pending,
        }


@pytest.fixture()
def client(tmp_path: Path):
    engine = _engine(tmp_path)
    store = SessionStore()
    graph = _FakeGraph(final_answer="hello from agent")
    service = AgentService(store=store, graph=graph, engine=engine)

    async def _override() -> AgentService:
        return service

    app.dependency_overrides[get_agent_service] = _override
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_agent_service, None)
        asyncio.run(engine.dispose())


@pytest.mark.integration
def test_create_session(client: TestClient) -> None:
    r = client.post("/api/agent/sessions", json={"title": "demo", "task_type": "rag_qa"})
    assert r.status_code == 201
    body = r.json()
    assert body["session_id"]
    assert body["title"] == "demo"
    assert body["environment"] == "dev"
    assert body["status"] == "active"


@pytest.mark.integration
def test_list_sessions_includes_created(client: TestClient) -> None:
    new = client.post("/api/agent/sessions", json={"title": "listed"})
    sid = new.json()["session_id"]

    r = client.get("/api/agent/sessions")
    assert r.status_code == 200
    sessions = r.json()["sessions"]
    assert any(s["session_id"] == sid and s["title"] == "listed" for s in sessions)


@pytest.mark.integration
def test_send_message_and_events(client: TestClient) -> None:
    new = client.post("/api/agent/sessions", json={"title": "t"})
    sid = new.json()["session_id"]

    r = client.post(
        f"/api/agent/sessions/{sid}/messages",
        json={"content": "what is the refund policy?"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == sid
    assert body["final_answer"] == "hello from agent"
    assert body["task_type"] == "rag_qa"
    assert body["approval_state"] == "not_required"
    assert body["pending_tools"] == []

    # Event stream should contain the inbound user message, the graph events
    # emitted by the fake graph, and the outbound assistant message.
    ev = client.get(f"/api/agent/sessions/{sid}/events")
    assert ev.status_code == 200
    events = ev.json()["events"]
    types = [e["event_type"] for e in events]
    assert types[0] == "message" and types[-1] == "message"
    # user -> (graph events) -> assistant
    roles = [e["content"].get("role") for e in events if e["event_type"] == "message"]
    assert roles == ["user", "assistant"]
    # graph-emitted events are present (classify / tool_call).
    assert "classify" in types and "tool_call" in types


@pytest.mark.integration
def test_send_message_unknown_session_404(client: TestClient) -> None:
    r = client.post(
        "/api/agent/sessions/does-not-exist/messages",
        json={"content": "hi"},
    )
    assert r.status_code == 404
