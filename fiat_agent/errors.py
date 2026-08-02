"""Structured business errors for fiat-agent (phase A4, DEV_SPEC §2.2).

All business/infra errors derive from `FiatAgentError` so they carry a stable
`code`, a human `message`, and arbitrary `metadata`. These are deterministic
error types (never LLM-generated) and feed the audit/approval boundaries.
"""

from __future__ import annotations

from typing import Any


class FiatAgentError(Exception):
    """Base error: always carries `code`, `message`, `metadata`."""

    code: str = "fiat_agent_error"

    def __init__(
        self,
        message: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.metadata: dict[str, Any] = metadata or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "metadata": self.metadata,
        }


class PermissionDeniedError(FiatAgentError):
    """Actor is not allowed to perform the action (deterministic RBAC reject)."""

    code = "permission_denied"


class ToolExecutionError(FiatAgentError):
    """A tool call failed during execution (not a permission issue)."""

    code = "tool_execution_error"


class ApprovalRequiredError(FiatAgentError):
    """Action is blocked until a human approval is granted (§2.2 state machine)."""

    code = "approval_required"
