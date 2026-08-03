"""C7 unit test: session JSONL exporter (DEV_SPEC C7).

Exports the active-branch events of a session as newline-delimited JSON.
Mirrors the C6 unit-test DB setup (temporary sqlite, no external service, per §9).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from fiat_agent.models.orm import Base
from fiat_agent.sessions.branches import BranchManager
from fiat_agent.sessions.jsonl_exporter import export_session_jsonl
from fiat_agent.sessions.store import SessionStore


def _engine(tmp_path: Path):
    return create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'jsonl.db'}")


@pytest.mark.unit
def test_export_matches_active_branch_and_includes_event_types(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    store = SessionStore()

    async def _run() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with maker() as s:
            ts = await store.create_session(s, title="export")
            await s.commit()
            sid = ts.id
            e1 = await store.append_event(s, session_id=sid, event_type="message", content={"role": "user", "text": "hi"})
            e2 = await store.append_event(s, session_id=sid, event_type="tool_call", parent_event_id=e1.id, content={"tool_name": "shell", "result": {"ok": 1}})
            e3 = await store.append_event(s, session_id=sid, event_type="compaction", parent_event_id=e2.id, content={"summary": "compacted"})
            e4 = await store.append_event(s, session_id=sid, event_type="approval", parent_event_id=e3.id, content={"status": "approved", "risk_level": "L3"})
            await s.commit()

            lines = [line async for line in export_session_jsonl(s, sid)]

        # One line per event, in active-branch (root -> tip) order.
        assert len(lines) == 4
        ids = [json.loads(line)["id"] for line in lines]
        assert ids == [e1.id, e2.id, e3.id, e4.id]

        # Every line is valid JSON and carries the event type + content.
        types = [json.loads(line)["event_type"] for line in lines]
        assert types == ["message", "tool_call", "compaction", "approval"]
        for line in lines:
            obj = json.loads(line)  # must not raise
            assert "created_at" in obj
            assert obj["content"] is not None

    asyncio.run(_run())
    asyncio.run(engine.dispose())


@pytest.mark.unit
def test_export_respects_branch_rollback(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    store = SessionStore()
    branches = BranchManager(store=store)

    async def _run() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with maker() as s:
            ts = await store.create_session(s, title="rollback-export")
            await s.commit()
            sid = ts.id
            e1 = await store.append_event(s, session_id=sid, event_type="message", content={"n": 1})
            e2 = await store.append_event(s, session_id=sid, event_type="message", parent_event_id=e1.id, content={"n": 2})
            e3 = await store.append_event(s, session_id=sid, event_type="message", parent_event_id=e2.id, content={"n": 3})
            await s.commit()

            # Roll back to e2, then fork a new branch: e3 is off the active path.
            await branches.rollback_to_event(s, session_id=sid, event_id=e2.id)
            e4 = await store.append_event(s, session_id=sid, event_type="message", parent_event_id=e2.id, content={"n": 4})
            await s.commit()

            lines = [line async for line in export_session_jsonl(s, sid)]

        ids = [json.loads(line)["id"] for line in lines]
        assert ids == [e1.id, e2.id, e4.id]  # e3 excluded (rolled back off active branch)

    asyncio.run(_run())
    asyncio.run(engine.dispose())


@pytest.mark.unit
def test_export_empty_session_yields_nothing(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    store = SessionStore()

    async def _run() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with maker() as s:
            ts = await store.create_session(s, title="empty")
            await s.commit()
            sid = ts.id
            lines = [line async for line in export_session_jsonl(s, sid)]
        assert lines == []

    asyncio.run(_run())
    asyncio.run(engine.dispose())
