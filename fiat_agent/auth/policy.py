"""Deterministic authorization service (phase B4, DEV_SPEC B4).

``can_execute`` / ``filter_tools`` are pure, side-effect-free functions over
the declarative policies loaded from ``config/tool_policies.yaml``. They never
call an LLM, so authorization is reproducible and auditable.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from fiat_agent.auth.rbac import ToolPolicy, load_tool_policies
from fiat_agent.schemas.common import ActorContext, Environment, RiskLevel
from fiat_agent.tools.schemas import ToolDefinition

# Risk tiers that always require an explicit approval, regardless of the
# per-tool flag. L4/L5 are production-impacting.
_HIGH_RISK = {RiskLevel.L4, RiskLevel.L5}


@dataclass
class PolicyDecision:
    allowed: bool
    reason: str
    approval_required: bool = False
    risk_level: Optional[RiskLevel] = None


@lru_cache(maxsize=1)
def _policies() -> dict[str, ToolPolicy]:
    return load_tool_policies()


def _env_value(environment) -> str:
    if environment is None:
        return ""
    if isinstance(environment, Environment):
        return environment.value
    return str(environment)


def can_execute(
    actor: ActorContext,
    tool_name: str,
    environment=None,
    resource=None,
    action: Optional[str] = None,
) -> PolicyDecision:
    """Decide whether ``actor`` may execute ``tool_name``.

    Args:
        actor: the acting principal (roles + environment from ActorContext).
        tool_name: policy key.
        environment: override environment (str/Environment); defaults to
            ``actor.environment``.
        resource: optional resource/collection id (reserved for scoping).
        action: optional action (e.g. "submit_prod") checked against denied
            actions.

    Returns:
        A :class:`PolicyDecision` with ``allowed``, a human-readable
        ``reason`` (always set, even on allow), ``approval_required`` and the
        tool's ``risk_level``.
    """
    policy = _policies().get(tool_name)
    if policy is None:
        return PolicyDecision(
            False, f"no policy defined for tool '{tool_name}'", risk_level=None
        )

    env = _env_value(environment) or _env_value(actor.environment)
    if not policy.allows_role_env(actor.roles and actor.roles[0] or "", env):
        # Distinguish role vs environment denial for a useful reason.
        if not any(r in policy.allowed_roles for r in actor.roles):
            return PolicyDecision(
                False,
                f"role(s) {actor.roles} not permitted for '{tool_name}'",
                risk_level=policy.risk_level,
            )
        return PolicyDecision(
            False,
            f"environment '{env}' not permitted for '{tool_name}'",
            risk_level=policy.risk_level,
        )

    if action is not None and action in policy.denied_actions:
        return PolicyDecision(
            False,
            f"action '{action}' denied for '{tool_name}'",
            risk_level=policy.risk_level,
        )

    approval_required = policy.approval_required or policy.risk_level in _HIGH_RISK
    return PolicyDecision(
        True, "allowed", approval_required=approval_required, risk_level=policy.risk_level
    )


def filter_tools(
    actor: ActorContext, tools: list[ToolDefinition], environment=None
) -> list[ToolDefinition]:
    """Return only the tools ``actor`` is permitted to execute.

    Tools that require approval are still included — approval gates execution,
    not visibility.
    """
    allowed = []
    for tool in tools:
        if can_execute(actor, tool.name, environment=environment).allowed:
            allowed.append(tool)
    return allowed
