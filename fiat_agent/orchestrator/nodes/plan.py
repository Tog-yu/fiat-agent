"""Planning node (phase G4, DEV_SPEC §G4).

Produces a structured execution plan and validates it. A malformed plan is
rejected so the orchestrator can ask the model to **retry**; a plan that
references tools the actor can't use is **degraded** to a safe subset rather
than failing outright.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Optional

from fiat_agent.orchestrator.state import AgentState
from fiat_agent.schemas.common import FiatModel, RiskLevel


class PlanStatus(str, Enum):
    """Outcome of planning for this turn."""

    OK = "ok"
    RETRY = "retry"  # structurally invalid -> ask the model to retry
    DEGRADED = "degraded"  # valid but trimmed to an allowed safe subset


class PlanningResult(FiatModel):
    """A structured execution plan produced by the planner (model or rule)."""

    steps: list[str] = []
    required_tools: list[str] = []
    risk_level: RiskLevel = RiskLevel.L1
    need_approval: bool = False


def validate_plan(raw: Any) -> Optional[PlanningResult]:
    """Coerce ``raw`` into a :class:`PlanningResult`, or ``None`` if malformed.

    Structural rules (DEV_SPEC §G4): ``steps`` must be a non-empty list,
    ``required_tools`` a list, ``risk_level`` a valid :class:`RiskLevel`, and
    ``need_approval`` a bool.
    """
    try:
        pr = raw if isinstance(raw, PlanningResult) else PlanningResult(**raw)
    except Exception:  # noqa: BLE001 - any coercion/validation error -> invalid
        return None
    if not isinstance(pr.steps, list) or len(pr.steps) == 0:
        return None
    if not isinstance(pr.required_tools, list):
        return None
    if not isinstance(pr.risk_level, RiskLevel):
        return None
    if not isinstance(pr.need_approval, bool):
        return None
    return pr


def plan_node(
    state: AgentState,
    planner: Callable[[AgentState], Any],
    available_tools: Optional[set[str]] = None,
) -> dict:
    """Run the planner, validate, and return a state delta.

    Returns ``{"plan": PlanningResult|None, "plan_status": PlanStatus}``. When a
    plan references tools outside ``available_tools``, it is degraded to the
    allowed subset (status ``DEGRADED``); when structurally invalid, the plan is
    dropped (status ``RETRY``) so the graph can loop back to the model.
    """
    pr = validate_plan(planner(state))
    if pr is None:
        return {"plan": None, "plan_status": PlanStatus.RETRY}

    if available_tools is not None:
        allowed = [t for t in pr.required_tools if t in available_tools]
        if allowed != pr.required_tools:
            # trim to the safe subset; keep going if at least one tool remains.
            pr = pr.model_copy(update={"required_tools": allowed})
            if not allowed:
                return {"plan": None, "plan_status": PlanStatus.RETRY}
            return {"plan": pr, "plan_status": PlanStatus.DEGRADED}

    return {"plan": pr, "plan_status": PlanStatus.OK}
