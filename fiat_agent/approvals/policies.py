"""Approval policies (phase B6, DEV_SPEC B6).

Deterministic rules about when an approval requires a second approver. No LLM.
"""

from __future__ import annotations

from fiat_agent.schemas.common import RiskLevel


def requires_dual_approval(risk_level: RiskLevel) -> bool:
    """L5 (highest risk) requires two distinct approvers (placeholder).

    Lower tiers need a single approver.
    """
    return risk_level == RiskLevel.L5
