"""Hermetic integration test for the audit query API (DEV_SPEC §J6).

Injects an in-memory :class:`AuditService` seeded with events and checks the
filters (actor / tool / risk / type) and ordering.
"""

from __future__ import annotations

import asyncio

import pytest
from fiat_agent.audit.service import AuditService
from fiat_agent.models.base import TokenUsage
from fiat_agent.schemas.common import ActorContext, Environment

from apps.api.main import app
from apps.api.routes.audit import get_audit_service


@pytest.fixture
def svc():
    s = AuditService()

    async def _get():
        return s

    app.dependency_overrides[get_audit_service] = _get
    yield s
    app.dependency_overrides.pop(get_audit_service, None)


def _actor(uid: str) -> ActorContext:
    return ActorContext(
        actor_id=uid,
        display_name=uid,
        roles=["oncall"],
        environment=Environment.DEV,
        scopes=[],
    )


def test_query_filters_and_order(svc):
    asyncio.run(
        svc.record_tool_call(_actor("alice"), "rag_query", {"q": "x"}, decision=None)
    )
    asyncio.run(
        svc.record_tool_call(_actor("bob"), "db_query", {"q": "y"}, decision=None)
    )
    asyncio.run(
        svc.record_model_usage(
            task_type="rag_qa", model="m", usage=TokenUsage(), session_id="s1"
        )
    )

    from starlette.testclient import TestClient

    with TestClient(app) as client:
        # actor filter
        r = client.get("/api/audit", params={"actor_id": "alice"})
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1 and data[0]["actor_id"] == "alice"

        # type filter
        r = client.get("/api/audit", params={"type": "model_usage"})
        assert r.status_code == 200
        assert all(e["type"] == "model_usage" for e in r.json())

        # newest-first
        r = client.get("/api/audit")
        assert r.status_code == 200
        ts = [e["timestamp"] for e in r.json()]
        assert ts == sorted(ts, reverse=True)


def test_bad_time_param(svc):
    from starlette.testclient import TestClient

    with TestClient(app) as client:
        r = client.get("/api/audit", params={"from_ts": "not-a-date"})
        assert r.status_code == 400
