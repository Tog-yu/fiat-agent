"""I4 integration test: Lark bot (DEV_SPEC §I4).

Drives the Lark event endpoint against hermetic fakes: a fake
:class:`AgentService` (FakeGraph + temp sqlite), an in-memory
:class:`ApprovalService`, and a capturing :class:`LarkSender`. No real Lark API,
LLM, or MCP server is touched.

Run with: ``pytest -q tests/integration/test_lark_bot.py``
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from apps.api.agent_service import AgentService, get_agent_service
from apps.lark_bot.app import app, get_approval_service
from apps.lark_bot.handlers import LarkSender
from fiat_agent.approvals.service import ApprovalService, RiskLevel
from fiat_agent.models.orm import Base
from fiat_agent.schemas.common import ActorContext, Environment, TaskType
from fiat_agent.sessions.store import SessionStore

REPO_ROOT = Path(__file__).resolve().parents[2]


def _engine(tmp_path: Path) -> AsyncEngine:
    url = f"sqlite+aiosqlite:///{tmp_path / 'lark.db'}"
    engine = create_async_engine(url, future=True)
    import fiat_agent.sessions.store  # noqa: F401 - register ORM models

    async def _create() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create())
    return engine


class _FakeGraph:
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
            "final_answer": f"ans: {user_text}",
            "task_type": TaskType.RAG_QA,
            "approval_state": "not_required",
            "pending_approvals": [],
        }


class _CapturingSender(LarkSender):
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_text(self, open_id: str, text: str) -> None:
        self.sent.append((open_id, text))


@pytest.fixture()
def client(tmp_path: Path):
    engine = _engine(tmp_path)
    store = SessionStore()
    graph = _FakeGraph()
    agent = AgentService(store=store, graph=graph, engine=engine)

    approvals = ApprovalService()
    sender = _CapturingSender()

    async def _agent() -> AgentService:
        return agent

    async def _approval() -> ApprovalService:
        return approvals

    app.dependency_overrides[get_agent_service] = _agent
    app.dependency_overrides[get_approval_service] = _approval

    # Patch the sender dependency by swapping the function reference.
    import apps.lark_bot.app as lark_app

    def _sender() -> LarkSender:
        return sender

    app.dependency_overrides[lark_app.get_lark_sender] = _sender

    try:
        with TestClient(app) as c:
            yield c, approvals, sender
    finally:
        app.dependency_overrides.pop(get_agent_service, None)
        app.dependency_overrides.pop(get_approval_service, None)
        app.dependency_overrides.pop(lark_app.get_lark_sender, None)
        asyncio.run(engine.dispose())


@pytest.mark.integration
def test_url_verification(client) -> None:
    c, _, _ = client
    r = c.post("/lark/events", json={"type": "url_verification", "challenge": "abc123"})
    assert r.status_code == 200
    assert r.json()["challenge"] == "abc123"


@pytest.mark.integration
def test_message_event_runs_agent_and_replies(client) -> None:
    c, _, sender = client
    payload = {
        "header": {"event_type": "im.message.receive_v1"},
        "event": {
            "sender": {"sender_id": {"open_id": "ou_alice"}},
            "message": {
                "message_type": "text",
                "content": '{"text": "what is the refund policy?"}',
            },
        },
    }
    r = c.post("/lark/events", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "message"
    assert body["answer"] == "ans: what is the refund policy?"
    # The outbound reply was dispatched to the asking user.
    assert sender.sent and sender.sent[0] == ("ou_alice", "ans: what is the refund policy?")


@pytest.mark.integration
def test_approval_card_callback_approves(client) -> None:
    c, approvals, sender = client
    # Seed a pending approval directly via the service.
    approval = asyncio.run(
        approvals.request(
            requester_id="ou_bob",
            tool_name="es_query",
            params_summary={"q": "*"},
            risk_level=RiskLevel.L3,
            environment="dev",
        )
    )
    payload = {
        "header": {"event_type": "card.action.trigger"},
        "event": {
            "operator": {"open_id": "ou_approver"},
            "action": {"value": {"approval_id": approval.id, "action": "approve"}},
        },
    }
    r = c.post("/lark/events", json=payload)
    assert r.status_code == 200
    assert r.json()["type"] == "card"
    assert r.json()["action"] == "approve"

    # Approval is now decided.
    decided = asyncio.run(approvals.get(approval.id))
    assert decided is not None
    assert decided.status == "approved"
    assert decided.approver_id == "ou_approver"
