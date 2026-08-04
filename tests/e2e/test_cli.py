"""I3 e2e test: fiat-agent CLI (DEV_SPEC §I3).

Drives the real CLI entry point (``apps.cli.main.main``) through its ``once`` and
``chat`` modes against a hermetic :class:`AgentService` (fake graph + temporary
sqlite). The service is injected by monkeypatching ``_SERVICE_FACTORY`` so no
real LLM / MCP server is needed.

Run with: ``pytest -q tests/e2e/test_cli.py``
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from apps.api.agent_service import AgentService
from apps.api.main import app  # noqa: F401 - ensure app importable for server mode
from apps.cli import main as cli_main
from fiat_agent.models.orm import Base
from fiat_agent.schemas.common import ActorContext, Environment, TaskType
from fiat_agent.sessions.store import SessionStore

REPO_ROOT = Path(__file__).resolve().parents[2]


def _engine(tmp_path: Path) -> AsyncEngine:
    url = f"sqlite+aiosqlite:///{tmp_path / 'cli.db'}"
    engine = create_async_engine(url, future=True)
    import fiat_agent.sessions.store  # noqa: F401 - register ORM models

    async def _create() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create())
    return engine


class _FakeGraph:
    """Deterministic stand-in for :class:`AgentGraph` (no real model call)."""

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
        return {
            "final_answer": f"echo: {user_text}",
            "task_type": TaskType.RAG_QA,
            "approval_state": "not_required",
            "pending_approvals": [],
        }


@pytest.fixture()
def fake_service_factory(tmp_path: Path, monkeypatch):
    engine = _engine(tmp_path)
    store = SessionStore()
    graph = _FakeGraph()
    service = AgentService(store=store, graph=graph, engine=engine)

    async def _factory() -> AgentService:
        return service

    monkeypatch.setattr(cli_main, "_SERVICE_FACTORY", _factory)
    yield service
    asyncio.run(engine.dispose())


@pytest.mark.e2e
def test_once_outputs_result(fake_service_factory, capsys) -> None:
    rc = cli_main.main(["once", "--message", "what is the refund policy?"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "echo: what is the refund policy?" in out


@pytest.mark.e2e
def test_chat_multi_turn(fake_service_factory, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO("first question\nsecond question\n/exit\n"),
    )
    rc = cli_main.main(["chat"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "agent> echo: first question" in out
    assert "agent> echo: second question" in out
    assert "bye." in out


@pytest.mark.e2e
def test_help_lists_modes(monkeypatch, capsys) -> None:
    rc = cli_main.main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "once" in out and "chat" in out and "server" in out
