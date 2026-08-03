"""F7 unit test: test-environment tool contract (DEV_SPEC §F7).

Covers the acceptance criteria:
  1. test-env actions run ONLY in the DEV environment;
  2. unknown actions are rejected;
  3. every generated resource is stamped with the `TEST_` marker + is_test=True.
"""

from __future__ import annotations

import asyncio

import pytest

from fiat_agent.errors import ToolContractViolation
from fiat_agent.schemas.common import Environment
from fiat_agent.tool_gateway.test_env_tools import (
    TEST_MARKER,
    FakeTestEnvClient,
    TestEnvRequest,
    TestEnvTool,
)


@pytest.mark.unit
def test_only_dev_environment_allowed() -> None:
    tool = TestEnvTool(FakeTestEnvClient())
    for env in (Environment.STAGING, Environment.PROD):
        with pytest.raises(ToolContractViolation):
            tool.validate(TestEnvRequest(environment=env, action="create_account"))
    # DEV is accepted.
    tool.validate(TestEnvRequest(environment=Environment.DEV, action="create_account"))


@pytest.mark.unit
def test_unknown_action_rejected() -> None:
    tool = TestEnvTool(FakeTestEnvClient())
    with pytest.raises(ToolContractViolation):
        tool.validate(TestEnvRequest(environment=Environment.DEV, action="drop_prod"))


@pytest.mark.unit
def test_resource_stamped_as_test_data() -> None:
    fake = FakeTestEnvClient()
    tool = TestEnvTool(fake)

    result = asyncio.run(
        tool.execute(
            TestEnvRequest(
                environment=Environment.DEV,
                action="recharge",
                payload={"amount": 100},
            )
        )
    )
    # marker + flag present on the result and forwarded to the backend.
    assert result.resource_id.startswith(TEST_MARKER)
    assert result.is_test is True
    assert fake.ops[0][3] == result.resource_id
    assert fake.ops[0][0] == "recharge"


@pytest.mark.unit
def test_kyc_also_stamped() -> None:
    fake = FakeTestEnvClient()
    tool = TestEnvTool(fake)
    result = asyncio.run(
        tool.execute(
            TestEnvRequest(environment=Environment.DEV, action="kyc", payload={"uid": "u9"})
        )
    )
    assert result.resource_id.startswith(TEST_MARKER)
    assert fake.ops[0][0] == "kyc"
