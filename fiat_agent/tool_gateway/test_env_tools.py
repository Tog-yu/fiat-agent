"""Test-environment tool contract (phase F7, DEV_SPEC §F7).

High-risk test-env automations (create test account / recharge / KYC) are gated
so they can **only** run in the DEV environment, and every generated resource is
stamped with a ``TEST_`` marker + ``is_test=True`` so test data is never
confused with production data (DEV_SPEC §F7: 仅测试环境可执行 / 所有测试数据带标识).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fiat_agent.errors import ToolContractViolation
from fiat_agent.schemas.common import Environment, FiatModel

# Only these actions are exposed; everything else is rejected.
ALLOWED_ACTIONS: frozenset[str] = frozenset({"create_account", "recharge", "kyc"})
# Test-env tools may only run here.
ALLOWED_ENVIRONMENTS: frozenset[Environment] = frozenset({Environment.DEV})
TEST_MARKER = "TEST_"


class TestEnvRequest(FiatModel):
    """A request for one test-env action. Must target the DEV environment."""

    __test__ = False  # not a pytest test class

    environment: Environment
    action: str
    payload: dict[str, Any] = {}


class TestEnvResult(FiatModel):
    """Outcome of a test-env action; always carries the test marker."""

    action: str
    environment: str
    resource_id: str
    is_test: bool = True
    detail: dict[str, Any] = {}


class FakeTestEnvClient:
    """In-memory stand-in for the test-env backend (tests)."""

    def __init__(self) -> None:
        self.ops: list[tuple[str, str, dict[str, Any], str]] = []

    async def run(
        self, action: str, environment: str, payload: dict[str, Any], resource_id: str
    ) -> dict[str, Any]:
        self.ops.append((action, environment, payload, resource_id))
        return {"ok": True, "resource_id": resource_id}


class TestEnvTool:
    """Test-env automation tool bound to a client (real or :class:`FakeTestEnvClient`)."""

    __test__ = False  # not a pytest test class

    def __init__(self, client: Any) -> None:
        self._client = client

    def validate(self, request: TestEnvRequest) -> None:
        if request.environment not in ALLOWED_ENVIRONMENTS:
            raise ToolContractViolation(
                f"test-env tools only run in {sorted(e.value for e in ALLOWED_ENVIRONMENTS)}",
                metadata={"environment": request.environment.value},
            )
        if request.action not in ALLOWED_ACTIONS:
            raise ToolContractViolation(
                f"action '{request.action}' is not allowed",
                metadata={"allowed_actions": sorted(ALLOWED_ACTIONS)},
            )

    def _stamp(self, action: str) -> str:
        """Generate a resource id that is unambiguously test data."""
        return f"{TEST_MARKER}{action}_{uuid4().hex[:8]}"

    async def execute(self, request: TestEnvRequest) -> TestEnvResult:
        """Run the test-env action; stamp the resource as test data."""
        self.validate(request)
        resource_id = self._stamp(request.action)
        detail = await self._client.run(
            request.action, request.environment.value, request.payload, resource_id
        )
        return TestEnvResult(
            action=request.action,
            environment=request.environment.value,
            resource_id=resource_id,
            is_test=True,
            detail=detail,
        )
