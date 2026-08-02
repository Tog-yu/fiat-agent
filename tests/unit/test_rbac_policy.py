"""B3 unit test: RBAC policy model + loader (DEV_SPEC B3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from fiat_agent.auth.rbac import load_tool_policies

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def policies() -> dict:
    return load_tool_policies(REPO_ROOT / "config" / "tool_policies.yaml")


@pytest.mark.unit
def test_ops_cashback_dryrun_allowed_in_dev(policies) -> None:
    p = policies["cashback_reconcile"]
    assert p.allows_role_env("ops", "dev") is True
    # staging also allowed, prod is not (dry-run never touches prod)
    assert p.allows_role_env("ops", "staging") is True
    assert p.allows_role_env("ops", "prod") is False


@pytest.mark.unit
def test_ops_cannot_submit_prod(policies) -> None:
    p = policies["cashback_submit"]
    assert "ops" not in p.allowed_roles
    assert p.allows_role_env("ops", "prod") is False
    assert "submit_prod" in p.denied_actions


@pytest.mark.unit
def test_oncall_es_db_rag_allowed(policies) -> None:
    assert policies["es_query"].allows_role_env("oncall", "prod") is True
    assert policies["db_query"].allows_role_env("oncall", "prod") is True
    assert policies["rag_query"].allows_role_env("oncall", "dev") is True


@pytest.mark.unit
def test_collection_scope_filtered_by_role(policies) -> None:
    p = policies["cashback_reconcile"]
    assert p.collections_for_role("oncall") == ["cashback_readonly"]
    assert p.collections_for_role("ops") == ["cashback_all"]
    assert p.collections_for_role("viewer") == []
