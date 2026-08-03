"""F5 unit test: DB read-only tool contract (DEV_SPEC §F5).

Covers the acceptance criteria:
  1. only fixed, named queries are allowed (no arbitrary SQL);
  2. parameters are bound, never string-interpolated into the SQL;
  3. sensitive fields in result rows are masked.
"""

from __future__ import annotations

import asyncio

import pytest

from fiat_agent.errors import ToolContractViolation
from fiat_agent.tool_gateway.db_tools import (
    ALLOWED_QUERIES,
    DbQueryRequest,
    DbTool,
    FakeDbClient,
)


@pytest.mark.unit
def test_unknown_query_name_rejected() -> None:
    tool = DbTool(FakeDbClient())
    with pytest.raises(ToolContractViolation):
        tool.validate(DbQueryRequest(name="DROP_TABLE_evil"))
    assert "DROP_TABLE_evil" not in ALLOWED_QUERIES


@pytest.mark.unit
def test_no_arbitrary_sql_params_bound_not_interpolated() -> None:
    fake = FakeDbClient()
    tool = DbTool(fake)
    req = DbQueryRequest(
        name="user_orders", params={"user_id": 42, "limit": 5}
    )
    asyncio.run(tool.query(req))

    sql, params = fake.calls[0]
    # the executed SQL is the fixed template, with no caller value embedded.
    assert sql == ALLOWED_QUERIES["user_orders"]
    assert "42" not in sql
    # params travel separately as bound values.
    assert params == {"user_id": 42, "limit": 5}


@pytest.mark.unit
def test_sensitive_fields_masked() -> None:
    rows = [
        {"order_id": 1, "user_id": 42, "amount": 100, "phone": "13800138000", "email": "a@b.com"},
    ]
    fake = FakeDbClient({ALLOWED_QUERIES["user_orders"]: rows})
    tool = DbTool(fake)

    result = asyncio.run(tool.query(DbQueryRequest(name="user_orders", params={"user_id": 42, "limit": 5})))
    row = result.rows[0]
    # sensitive columns masked, non-sensitive preserved.
    assert row["phone"] == "***8000"
    assert row["email"] == "***.com"
    assert row["amount"] == 100
    assert row["order_id"] == 1
    # original values never leaked into the result.
    assert "13800138000" not in str(result.rows)
    assert "a@b.com" not in str(result.rows)
