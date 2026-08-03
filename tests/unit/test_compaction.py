"""C5 unit test: context compaction (DEV_SPEC C5).

Pure logic (should_compact / compact_events) plus the append path, using a
temporary sqlite database (no external service, per §9).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from fiat_agent.context.compaction import (
    CompactionService,
    CompactionSummary,
    compact_events,
    should_compact,
)
from fiat_agent.models.orm import Base
from fiat_agent.sessions.store import SessionStore, TaskSessionEvent


def _engine(tmp_path: Path):
    return create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'compaction.db'}")


def _ev(id: str, event_type: str, content: dict) -> TaskSessionEvent:
    return TaskSessionEvent(id=id, session_id="s1", event_type=event_type, content=content)


@pytest.mark.unit
def test_should_compact_threshold(tmp_path: Path) -> None:
    small = [_ev("e1", "message", {"role": "user", "text": "hi"})]
    assert should_compact(small, token_threshold=4000) is False
    big = [_ev(f"e{i}", "message", {"role": "user", "text": "x" * 400}) for i in range(50)]
    assert should_compact(big, token_threshold=4000) is True
    assert should_compact([], token_threshold=4000) is False


@pytest.mark.unit
def test_compact_events_summary(tmp_path: Path) -> None:
    events = [
        _ev("e1", "message", {"role": "user", "text": "诊断支付失败"}),
        _ev("e2", "tool_call", {"tool_name": "shell", "result": {"exit": 0}}),
        _ev("e3", "approval", {"status": "approved", "risk_level": "L3"}),
        _ev("e4", "message", {"role": "assistant", "references": ["doc-a"], "next_steps": ["复核"]}),
    ]
    summary = compact_events(events)
    assert isinstance(summary, CompactionSummary)
    assert summary.user_goal == "诊断支付失败"
    assert any("shell" in r for r in summary.tool_results)
    assert summary.references == ["doc-a"]
    assert summary.approval_status == "approved"
    assert summary.risk_status == "L3"
    assert summary.next_steps == ["复核"]
    assert summary.original_event_ids == ["e1", "e2", "e3", "e4"]


@pytest.mark.unit
def test_compact_highest_risk_and_status(tmp_path: Path) -> None:
    events = [
        _ev("e1", "approval", {"status": "pending", "risk_level": "L2"}),
        _ev("e2", "approval", {"status": "approved", "risk_level": "L5"}),
    ]
    summary = compact_events(events)
    assert summary.approval_status == "approved"
    assert summary.risk_status == "L5"


@pytest.mark.unit
def test_append_compaction_does_not_delete_originals(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    store = SessionStore()
    service = CompactionService(store=store)

    async def _run() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with maker() as s:
            ts = await store.create_session(s, title="c")
            await s.commit()
            sid = ts.id
            e1 = await store.append_event(s, session_id=sid, event_type="message", content={"role": "user", "text": "goal"})
            await s.commit()

            summary = compact_events([e1])
            cp = await service.append_compaction_event(
                s, session_id=sid, summary=summary, parent_event_id=e1.id
            )
            await s.commit()
            assert cp.event_type == "compaction"
            assert cp.content["user_goal"] == "goal"
            # Originals intact — still exactly one message event + the compaction.
            all_events = await store.list_session_events(s, sid)
            types = [e.event_type for e in all_events]
            assert types == ["message", "compaction"]

    asyncio.run(_run())
    asyncio.run(engine.dispose())
