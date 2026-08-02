"""B5 unit test: audit service records events with redaction (DEV_SPEC B5)."""

from __future__ import annotations

import asyncio

import pytest

from fiat_agent.audit.repository import InMemoryAuditRepository
from fiat_agent.audit.service import AuditService
from fiat_agent.auth.policy import PolicyDecision
from fiat_agent.schemas.common import ActorContext, Environment


@pytest.mark.unit
def test_audit_records_tool_call_policy_decision_approval() -> None:
    async def _run() -> None:
        svc = AuditService(InMemoryAuditRepository())
        actor = ActorContext(actor_id="u1", roles=["ops"], environment=Environment.DEV)

        await svc.record_tool_call(
            actor,
            "es_query",
            arguments={"index": "logs", "api_key": "sk-secret"},
            result={"hits": 3},
        )
        await svc.record_policy_decision(
            actor, "cashback_submit", PolicyDecision(False, "role not permitted")
        )
        await svc.record_approval(
            actor_id="u1",
            tool_name="cashback_submit",
            approval_id="ap1",
            outcome="rejected",
            reason="needs dual approval",
        )

        events = await svc._repo.list()
        assert len(events) == 3

        tc = next(e for e in events if e.type == "tool_call")
        assert tc.tool_name == "es_query"
        # nested sensitive field redacted
        assert tc.metadata["arguments"]["api_key"] == "***"

        pd = next(e for e in events if e.type == "policy_decision")
        assert pd.allowed is False
        assert pd.reason == "role not permitted"

        ap = next(e for e in events if e.type == "approval")
        assert ap.allowed is False
        assert ap.metadata["outcome"] == "rejected"

    asyncio.run(_run())
