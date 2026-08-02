"""RBAC policy model + loader (phase B3, DEV_SPEC B3).

Defines the policy data structures consumed by the deterministic
``can_execute`` check in B4. Policies are declared in
``config/tool_policies.yaml`` and loaded here — no LLM involvement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import yaml

from fiat_agent.schemas.common import RiskLevel


class Permission(str, Enum):
    """Actions a policy can gate."""

    EXECUTE = "execute"
    READ = "read"
    WRITE = "write"
    SUBMIT_PROD = "submit_prod"


@dataclass
class ToolPolicy:
    """Per-tool authorization policy."""

    tool: str
    risk_level: RiskLevel
    allowed_roles: list[str] = field(default_factory=list)
    allowed_environments: list[str] = field(default_factory=list)
    approval_required: bool = False
    allowed_scopes: list[str] = field(default_factory=list)
    # role -> list of collection ids the role may touch with this tool.
    collection_scopes: dict[str, list[str]] = field(default_factory=dict)
    # actions explicitly denied for this tool (e.g. "submit_prod").
    denied_actions: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "ToolPolicy":
        return cls(
            tool=d["tool"],
            risk_level=RiskLevel(d["risk_level"]),
            allowed_roles=list(d.get("allowed_roles", [])),
            allowed_environments=list(d.get("allowed_environments", [])),
            approval_required=bool(d.get("approval_required", False)),
            allowed_scopes=list(d.get("allowed_scopes", [])),
            collection_scopes=dict(d.get("collection_scopes", {})),
            denied_actions=list(d.get("denied_actions", [])),
        )

    def allows_role_env(self, role: str, environment: str) -> bool:
        """Whether ``role`` may use this tool in ``environment`` at all."""
        return role in self.allowed_roles and environment in self.allowed_environments

    def collections_for_role(self, role: str) -> list[str]:
        """Collection ids ``role`` may access with this tool (empty = none)."""
        return list(self.collection_scopes.get(role, []))


def load_tool_policies(path: str | Path | None = None) -> dict[str, ToolPolicy]:
    """Load tool policies from YAML into a ``{tool: ToolPolicy}`` map."""
    if path is None:
        path = (
            Path(__file__).resolve().parent.parent.parent
            / "config"
            / "tool_policies.yaml"
        )
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return {p["tool"]: ToolPolicy.from_dict(p) for p in raw.get("policies", [])}
