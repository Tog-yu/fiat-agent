"""Approval model + service (phase B6, DEV_SPEC B6).

Guarantees:
- an approval can be decided only once (immutable after approve/reject);
- the requested ``params_summary`` is a frozen snapshot, never mutated;
- L5 tools require two distinct approvers (dual-approval placeholder).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fiat_agent.approvals.policies import requires_dual_approval
from fiat_agent.schemas.common import FiatModel, RiskLevel


class ApprovalError(Exception):
    """Base error for approval operations."""


class AlreadyDecidedError(ApprovalError):
    """Raised when trying to approve/reject an already-decided approval."""


class Approval(FiatModel):
    id: str
    requester_id: str
    tool_name: str
    params_summary: dict  # frozen snapshot, never changed after request
    risk_level: str
    environment: str
    status: str = "pending"  # pending | approved | rejected
    dual_approval: bool = False
    first_approver_id: Optional[str] = None
    second_approver_id: Optional[str] = None
    approver_id: Optional[str] = None
    reason: Optional[str] = None
    decided_at: Optional[datetime] = None


class ApprovalRepository:
    async def add(self, approval: Approval) -> None:  # pragma: no cover
        raise NotImplementedError

    async def get(self, approval_id: str) -> Optional[Approval]:  # pragma: no cover
        raise NotImplementedError

    async def update(self, approval: Approval) -> None:  # pragma: no cover
        raise NotImplementedError

    async def list(self, *, status: Optional[str] = None) -> list[Approval]:  # pragma: no cover
        raise NotImplementedError


class InMemoryApprovalRepository(ApprovalRepository):
    def __init__(self) -> None:
        self._store: dict[str, Approval] = {}

    async def add(self, approval: Approval) -> None:
        self._store[approval.id] = approval

    async def get(self, approval_id: str) -> Optional[Approval]:
        return self._store.get(approval_id)

    async def update(self, approval: Approval) -> None:
        self._store[approval.id] = approval

    async def list(self, *, status: Optional[str] = None) -> list[Approval]:
        items = list(self._store.values())
        if status is not None:
            items = [a for a in items if a.status == status]
        # Newest first by id (uuid hex sort is chronological enough for display).
        items.sort(key=lambda a: a.id, reverse=True)
        return items


class ApprovalService:
    def __init__(self, repository: ApprovalRepository | None = None) -> None:
        self._repo = repository or InMemoryApprovalRepository()

    async def request(
        self,
        *,
        requester_id: str,
        tool_name: str,
        params_summary: dict,
        risk_level: RiskLevel,
        environment: str,
    ) -> Approval:
        approval = Approval(
            id=uuid4().hex,
            requester_id=requester_id,
            tool_name=tool_name,
            params_summary=dict(params_summary),  # snapshot copy
            risk_level=risk_level.value,
            environment=environment,
            dual_approval=requires_dual_approval(risk_level),
        )
        await self._repo.add(approval)
        return approval

    async def get(self, approval_id: str) -> Optional[Approval]:
        """Look up an approval by id (read-only; used by the submit guard)."""
        return await self._repo.get(approval_id)

    async def list(self, *, status: Optional[str] = None) -> list[Approval]:
        """List approvals, optionally filtered by ``status`` (newest first)."""
        return await self._repo.list(status=status)

    async def approve(self, approval_id: str, approver_id: str) -> Approval:
        approval = await self._repo.get(approval_id)
        if approval is None:
            raise ApprovalError(f"approval '{approval_id}' not found")
        if approval.status != "pending":
            raise AlreadyDecidedError(
                f"approval '{approval_id}' already {approval.status}"
            )

        if approval.dual_approval:
            if approval.first_approver_id is None:
                approval.first_approver_id = approver_id
                await self._repo.update(approval)
                return approval
            if (
                approval.second_approver_id is None
                and approver_id != approval.first_approver_id
            ):
                approval.second_approver_id = approver_id
                approval.status = "approved"
                approval.approver_id = approver_id
                approval.decided_at = datetime.now(timezone.utc)
                await self._repo.update(approval)
                return approval
            raise ApprovalError("dual approval requires two distinct approvers")

        approval.status = "approved"
        approval.approver_id = approver_id
        approval.decided_at = datetime.now(timezone.utc)
        await self._repo.update(approval)
        return approval

    async def reject(
        self, approval_id: str, approver_id: str, reason: str | None = None
    ) -> Approval:
        approval = await self._repo.get(approval_id)
        if approval is None:
            raise ApprovalError(f"approval '{approval_id}' not found")
        if approval.status != "pending":
            raise AlreadyDecidedError(
                f"approval '{approval_id}' already {approval.status}"
            )
        approval.status = "rejected"
        approval.approver_id = approver_id
        approval.reason = reason
        approval.decided_at = datetime.now(timezone.utc)
        await self._repo.update(approval)
        return approval
