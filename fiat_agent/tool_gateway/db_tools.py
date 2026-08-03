"""Database read-only tool contract (phase F5, DEV_SPEC §F5).

The agent may only run a fixed set of **named** queries. Raw SQL is never
accepted — the SQL is looked up from :data:`ALLOWED_QUERIES` and parameters are
passed as bound values (never string-interpolated). Result rows have sensitive
columns masked before they ever reach the model.
"""

from __future__ import annotations

from typing import Any

from fiat_agent.errors import ToolContractViolation
from fiat_agent.schemas.common import FiatModel

# Fixed, safe, parameterized queries. Keys are the only query names the agent
# may invoke; values are the (immutable) SQL templates. Adding a query is a code
# change, not a runtime input — so arbitrary SQL is structurally impossible.
ALLOWED_QUERIES: dict[str, str] = {
    "cashback_summary": (
        "SELECT user_id, amount, status FROM cashback "
        "WHERE created_at >= %(since)s LIMIT %(limit)s"
    ),
    "user_orders": (
        "SELECT order_id, user_id, amount, phone, email FROM orders "
        "WHERE user_id = %(user_id)s LIMIT %(limit)s"
    ),
}

# Columns redacted from any result row (DEV_SPEC §F5: 敏感字段脱敏).
SENSITIVE_FIELDS: frozenset[str] = frozenset(
    {"phone", "id_card", "bank_card", "email", "password", "token", "id_no"}
)


class DbQueryRequest(FiatModel):
    """A request for one fixed query by name — never raw SQL."""

    name: str
    params: dict[str, Any] = {}


class DbQueryResult(FiatModel):
    """Masked result rows for one fixed query."""

    name: str
    rows: list[dict[str, Any]] = []


class FakeDbClient:
    """In-memory stand-in for a DB client (tests)."""

    def __init__(self, rows_by_sql: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.rows_by_sql = rows_by_sql or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        self.calls.append((sql, params))
        return self.rows_by_sql.get(sql, [])


def mask_value(value: Any) -> str:
    """Mask a sensitive scalar: keep the last 4 chars, replace the rest."""
    s = str(value)
    return ("***" + s[-4:]) if len(s) > 4 else "***"


def mask_row(row: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``row`` with sensitive columns masked."""
    return {
        k: (mask_value(v) if k in SENSITIVE_FIELDS else v) for k, v in row.items()
    }


class DbTool:
    """Read-only DB query tool bound to a client (real or :class:`FakeDbClient`)."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def validate(self, request: DbQueryRequest) -> None:
        if request.name not in ALLOWED_QUERIES:
            raise ToolContractViolation(
                f"query '{request.name}' is not an allowed fixed query",
                metadata={"allowed_queries": sorted(ALLOWED_QUERIES)},
            )

    async def query(self, request: DbQueryRequest) -> DbQueryResult:
        """Run the named fixed query with bound params; mask sensitive fields."""
        self.validate(request)
        sql = ALLOWED_QUERIES[request.name]  # fixed template, never caller SQL
        raw_rows = await self._client.execute(sql, request.params)
        return DbQueryResult(
            name=request.name, rows=[mask_row(r) for r in raw_rows]
        )
