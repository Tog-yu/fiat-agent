"""Production submit guard (phase H8, DEV_SPEC §H8 / §13.2).

Reserves the interface for phase-2 *controlled* production submission while
keeping the MVP strictly safe:

- submission is gated by an **approved** ``Approval`` (deterministic state check);
- in the MVP the guard is **disabled by default**
  (``production_submit_enabled=False``); a disabled guard still enforces the
  approval gate but performs only a *fake* submission that records intent and
  never mutates production data.

This is a deterministic module (DEV_SPEC §2.2.6): the approval check, the
enabled flag, and the fake-vs-real branch are all plain logic, never LLM-driven.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from fiat_agent.approvals.service import Approval, ApprovalService
from fiat_agent.errors import ApprovalRequiredError
from fiat_agent.schemas.common import ActorContext

# The actual production-write callable.
# Signature: (actor, approved_approval, params) -> result dict.
SubmitFn = Callable[[ActorContext, Approval, dict[str, Any]], Awaitable[dict[str, Any]]]


class ProductionSubmitGuard:
    """Gate production submission behind an approved ``Approval`` + an MVP switch."""

    def __init__(
        self,
        approval_service: ApprovalService,
        *,
        production_submit_enabled: bool = False,
    ) -> None:
        self._approvals = approval_service
        # MVP safety: disabled by default. Flip only after the phase-2 submit
        # contract (idempotency, dual approval, compensation) has landed.
        self._enabled = production_submit_enabled

    @property
    def enabled(self) -> bool:
        """Whether a real production write may happen (vs. fake stub)."""
        return self._enabled

    async def ensure_approved(self, approval_id: str) -> Approval:
        """Return the approval, raising ``ApprovalRequiredError`` if not approved.

        Deterministic boundary: a missing or non-approved approval blocks submit
        before any write is even attempted.
        """
        approval = await self._approvals.get(approval_id)
        if approval is None:
            raise ApprovalRequiredError(
                f"approval '{approval_id}' not found; cannot submit",
                metadata={"approval_id": approval_id},
            )
        if approval.status != "approved":
            raise ApprovalRequiredError(
                f"approval '{approval_id}' is '{approval.status}', not approved; "
                "production submit is blocked until approved",
                metadata={"approval_id": approval_id, "status": approval.status},
            )
        return approval

    async def submit(
        self,
        approval_id: str,
        actor: ActorContext,
        *,
        params: Optional[dict[str, Any]] = None,
        do_submit: Optional[SubmitFn] = None,
    ) -> dict[str, Any]:
        """Submit only after the approval is granted (deterministic gate).

        Returns a result dict always containing ``approved`` and ``submitted``.
        When the MVP switch is disabled, ``submitted`` is ``False`` and ``fake``
        is ``True`` — a dry stub that recorded intent but wrote nothing. When
        enabled and an ``do_submit`` handler is supplied, the real write runs.
        """
        approval = await self.ensure_approved(approval_id)
        params = params or {}

        if not self._enabled:
            # MVP default: the approval gate was enforced above, but no real
            # production write ever happens.
            return {
                "approved": True,
                "submitted": False,
                "fake": True,
                "approval_id": approval.id,
                "reason": "production submit disabled in MVP (phase-2 contract pending)",
            }

        if do_submit is None:
            raise ApprovalRequiredError(
                "production submit is enabled but no submit handler was provided",
                metadata={"approval_id": approval.id},
            )

        result = await do_submit(actor, approval, params)
        result.setdefault("approved", True)
        result.setdefault("submitted", True)
        result["fake"] = False
        result["approval_id"] = approval.id
        return result
