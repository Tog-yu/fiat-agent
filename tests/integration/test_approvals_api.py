"""Hermetic integration test for the approval queue API (DEV_SPEC §J5).

Injects an in-memory :class:`ApprovalService` and exercises list / approve /
reject, the already-decided conflict, and the frozen-params guarantee.
"""

from __future__ import annotations

import asyncio

import pytest

from fiat_agent.approvals.service import ApprovalService, InMemoryApprovalRepository
from fiat_agent.schemas.common import RiskLevel

from apps.api.main import app
from apps.api.routes.approvals import get_approval_service


@pytest.fixture
def svc():
    s = ApprovalService(InMemoryApprovalRepository())

    async def _get():
        return s

    app.dependency_overrides[get_approval_service] = _get
    yield s
    app.dependency_overrides.pop(get_approval_service, None)


def _seed(s: ApprovalService):
    return asyncio.run(
        s.request(
            requester_id="alice",
            tool_name="db_query",
            params_summary={"query": "SELECT 1", "target": "prod_users"},
            risk_level=RiskLevel.L4,
            environment="prod",
        )
    )


def test_list_pending_and_frozen_params(svc):
    approval = _seed(svc)
    from starlette.testclient import TestClient

    with TestClient(app) as client:
        r = client.get("/api/approvals", params={"status": "pending"})
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        a = data[0]
        assert a["id"] == approval.id
        assert a["status"] == "pending"
        assert a["risk_level"] == "L4"
        # Frozen snapshot is returned verbatim; the client cannot submit params.
        assert a["params_summary"] == {"query": "SELECT 1", "target": "prod_users"}


def test_approve_then_conflict(svc):
    approval = _seed(svc)
    from starlette.testclient import TestClient

    with TestClient(app) as client:
        r = client.post(f"/api/approvals/{approval.id}/approve", json={"approver_id": "bob"})
        assert r.status_code == 200
        assert r.json()["status"] == "approved"
        assert r.json()["approver_id"] == "bob"

        # Second decision must be rejected with 409.
        r2 = client.post(f"/api/approvals/{approval.id}/approve", json={"approver_id": "carol"})
        assert r2.status_code == 409


def test_reject_with_reason(svc):
    approval = _seed(svc)
    from starlette.testclient import TestClient

    with TestClient(app) as client:
        r = client.post(
            f"/api/approvals/{approval.id}/reject",
            json={"approver_id": "bob", "reason": "not now"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "rejected"
        assert body["reason"] == "not now"


def test_decide_missing_approval(svc):
    from starlette.testclient import TestClient

    with TestClient(app) as client:
        r = client.post("/api/approvals/nope/approve", json={})
        assert r.status_code == 404
