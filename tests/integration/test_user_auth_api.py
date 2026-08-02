"""B7 integration test: user/permission API (DEV_SPEC B7).

Uses FastAPI's TestClient (no running server needed).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app


@pytest.mark.integration
def test_users_me() -> None:
    client = TestClient(app)
    r = client.get("/api/users/me")
    assert r.status_code == 200
    body = r.json()
    assert "roles" in body and "actor_id" in body


@pytest.mark.integration
def test_auth_check_allows_oncall_es() -> None:
    client = TestClient(app)
    r = client.post("/api/auth/check", json={"tool_name": "es_query", "environment": "prod"})
    assert r.status_code == 200
    assert r.json()["allowed"] is True


@pytest.mark.integration
def test_auth_check_denies_ops_prod_submit() -> None:
    client = TestClient(app)
    r = client.post(
        "/api/auth/check", json={"tool_name": "cashback_submit", "environment": "prod"}
    )
    assert r.status_code == 200
    assert r.json()["allowed"] is False
