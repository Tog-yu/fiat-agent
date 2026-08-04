"""Cashback reconciliation (dry-run) workflow (phase H6, DEV_SPEC §H6).

Generates a rebate reconciliation report + change plan from a parsed cashback
file. The reconciliation math (total / record / status / arrival-gap checks and
the matched-vs-mismatched tally) is computed **deterministically** — no LLM is
involved in the numbers, consistent with DEV_SPEC §2.2 (determinism first). The
model is only used, optionally, to draft a human-readable narrative on top of
the structured report.

Hard guarantee: this workflow is read-only. It only ever calls the read-only
``cashback_parse`` tool through the audited gateway and never invokes
``cashback_submit`` (production write). ``is_dry_run`` is therefore always
``True`` and cannot be flipped by a caller.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Awaitable, Callable, Optional

from fiat_agent.audit.service import AuditService
from fiat_agent.context.builder import ContextBuilder
from fiat_agent.models.base import ChatMessage, ChatRequest
from fiat_agent.models.gateway import ModelGateway
from fiat_agent.schemas.common import ActorContext, FiatModel, TaskType
from fiat_agent.skills.loader import DomainSkill, load_skill
from fiat_agent.tool_gateway.cashback_tools import make_cashback_parse_handler
from fiat_agent.tool_gateway.gateway import ToolGateway
from fiat_agent.tools.function_calling import ToolResultStatus
from fiat_agent.tools.registry import ToolRegistry

# The read-only parse tool this workflow drives (DEV_SPEC §H5).
PARSE_TOOL = "cashback_parse"

# Statuses considered valid for a rebate record. Anything else is flagged as a
# status anomaly; ``paid`` with a missing/non-positive amount is an arrival gap.
VALID_STATUSES = {"paid", "pending", "processing", "failed"}

# Deterministic mapping from an issue type to a suggested remediation action.
_PLAN_FOR: dict[str, tuple[str, str]] = {
    "duplicate": ("dedupe", "删除重复记录，保留首次出现"),
    "amount_format": ("fix_amount", "修正金额格式（去除符号/分隔符后重新解析）"),
    "status_invalid": ("normalize_status", "将状态规范为合法枚举值"),
    "status_missing": ("fill_status", "补齐状态字段"),
    "arrival_gap": ("investigate", "核查到账缺口：paid 但金额缺失或<=0"),
}


class CashbackReconcileResult(FiatModel):
    """Structured reconciliation report (matches the ``cashback_reconcile`` skill).

    ``is_dry_run`` is hardcoded ``True`` — this report never mutates production.
    """

    __test__ = False  # not a pytest test class

    file_path: str = ""
    summary: dict[str, Any] = {}
    issues: list[dict[str, Any]] = []
    change_plan: list[dict[str, Any]] = []
    is_dry_run: bool = True
    narrative: str = ""
    error: Optional[str] = None


def _plan_for(issue: dict[str, Any]) -> dict[str, Any]:
    """Suggest a remediation action for a detected issue."""
    action, description = _PLAN_FOR.get(
        issue["type"], ("review", "人工复核该记录")
    )
    target = f"row {issue['row_index']}"
    if issue.get("txn_id"):
        target = f"{target} (txn {issue['txn_id']})"
    return {"action": action, "target": target, "description": description}


class CashbackReconcileWorkflow:
    """End-to-end cashback reconciliation (dry-run)."""

    def __init__(
        self,
        registry: ToolRegistry,
        gateway: ToolGateway,
        model_gateway: Optional[ModelGateway],
        audit_service: AuditService,
        builder: Optional[ContextBuilder] = None,
        skill: Optional[DomainSkill] = None,
        *,
        parse_tool: str = PARSE_TOOL,
    ) -> None:
        self._registry = registry
        self._gateway = gateway
        self._model = model_gateway
        self._audit = audit_service
        self._builder = builder or ContextBuilder()
        self._skill = skill or load_skill(TaskType.CASHBACK_RECONCILE)
        self._parse_tool = parse_tool

    async def run(
        self,
        file_path: str,
        actor: ActorContext,
        *,
        field_map: Optional[dict[str, str]] = None,
        session_id: Optional[str] = None,
        event_emitter: Optional[Callable[[str, dict], Awaitable[None]]] = None,
    ) -> CashbackReconcileResult:
        """Reconcile ``file_path`` as a cashback statement for ``actor``.

        Args:
            file_path: path to the ``.csv`` / ``.xlsx`` rebate file.
            actor: the acting principal (drives parse-tool authorization).
            field_map: optional column->field override for the parser.
            session_id: optional session id for traceability / events.
            event_emitter: optional ``(type, payload)`` sink for the event bus (K).
        """
        # 1) Parse through the audited gateway (read-only; never writes).
        parse_result = await self._gateway.execute_tool(
            actor,
            self._parse_tool,
            {"file_path": file_path, "field_map": field_map},
        )
        if parse_result.status != ToolResultStatus.SUCCESS:
            # Parse failure -> surface as an error report; still dry-run.
            return CashbackReconcileResult(
                file_path=file_path,
                is_dry_run=True,
                error=parse_result.error,
            )

        parsed = parse_result.raw or {}
        recon = self._reconcile(parsed)

        # 3) Optional model narrative on top of the deterministic report.
        narrative = await self._narrate(actor, recon) if self._model else ""

        if event_emitter is not None:
            await event_emitter(
                "cashback_reconcile",
                {
                    "file_path": file_path,
                    "session_id": session_id,
                    "record_count": recon["summary"]["record_count"],
                    "mismatched": recon["summary"]["mismatched"],
                    "is_dry_run": True,
                },
            )

        return CashbackReconcileResult(
            file_path=file_path,
            is_dry_run=True,
            narrative=narrative,
            **recon,
        )

    # --- reconciliation core (deterministic) -----------------------------
    def _reconcile(self, parsed: dict[str, Any]) -> dict[str, Any]:
        """Compute the structured reconciliation report from a parse result.

        Returns ``{"summary": ..., "issues": ..., "change_plan": ...}``.
        """
        records = parsed.get("records", []) or []
        row_count = parsed.get("row_count", len(records)) or len(records)

        # Index which issue types hit each row (so a row is counted once).
        row_issue_types: dict[int, list[str]] = {}
        for kind in ("duplicates", "amount_errors"):
            for iss in parsed.get(kind, []) or []:
                row = iss["row_index"]
                row_issue_types.setdefault(row, []).append(iss["type"])

        extra_issues: list[dict[str, Any]] = []
        total = Decimal("0")
        for rec in records:
            idx = rec["row_index"]
            amount = Decimal(rec["amount"]) if rec.get("amount") else None
            status = rec.get("status")

            # Status validation: missing or unknown status is an anomaly.
            if status is None:
                row_issue_types.setdefault(idx, []).append("status_missing")
                extra_issues.append(
                    {"type": "status_missing", "detail": "缺少状态字段",
                     "row_index": idx, "txn_id": rec.get("txn_id")}
                )
            elif status not in VALID_STATUSES:
                row_issue_types.setdefault(idx, []).append("status_invalid")
                extra_issues.append(
                    {"type": "status_invalid",
                     "detail": f"未知状态 {status!r}（合法值：{sorted(VALID_STATUSES)}）",
                     "row_index": idx, "txn_id": rec.get("txn_id")}
                )

            # Arrival gap: paid but the amount is missing / non-positive.
            if status == "paid" and (amount is None or amount <= 0):
                row_issue_types.setdefault(idx, []).append("arrival_gap")
                extra_issues.append(
                    {"type": "arrival_gap",
                     "detail": "状态为 paid 但金额缺失或<=0（疑似到账缺口）",
                     "row_index": idx, "txn_id": rec.get("txn_id")}
                )

            # Gross parsed total (only records that yielded a number).
            if amount is not None:
                total += amount

        # Per-record matched/mismatched tally (each record counted once).
        matched = sum(1 for rec in records if not row_issue_types.get(rec["row_index"]))
        mismatched = row_count - matched

        # Assemble the full, de-duplicated issue list.
        issues: list[dict[str, Any]] = []
        seen_keys: set[tuple[int, str]] = set()
        for iss in (
            list(parsed.get("duplicates", []) or [])
            + list(parsed.get("amount_errors", []) or [])
            + extra_issues
        ):
            key = (iss["row_index"], iss["type"])
            if key in seen_keys:
                continue
            seen_keys.add(key)
            issues.append(
                {
                    "type": iss["type"],
                    "detail": iss["detail"],
                    "row_index": iss["row_index"],
                    "txn_id": iss.get("txn_id"),
                }
            )

        change_plan = [_plan_for(iss) for iss in issues]

        summary = {
            "total_amount": total,
            "record_count": row_count,
            "matched": matched,
            "mismatched": mismatched,
        }
        return {"summary": summary, "issues": issues, "change_plan": change_plan}

    # --- optional model narrative ----------------------------------------
    async def _narrate(self, actor: ActorContext, recon: dict[str, Any]) -> str:
        """Ask the model for a short human-readable summary (best-effort)."""
        try:
            built = self._builder.build(
                actor,
                self._registry,
                task_type=TaskType.CASHBACK_RECONCILE,
                skill=self._skill,
            )
            payload = (
                "请基于以下对账结果，用一句话向运营同学总结要点（不要编造数字）：\n"
                f"{recon}"
            )
            response = await self._model.function_call(
                ChatRequest(
                    messages=[
                        ChatMessage(role="system", content=built.system_prompt),
                        ChatMessage(role="user", content=payload),
                    ]
                ),
                task_type=TaskType.CASHBACK_RECONCILE.value,
            )
            return (response.content or "").strip()
        except Exception:  # noqa: BLE001 - narrative is best-effort
            return self._fallback_narrative(recon)

    @staticmethod
    def _fallback_narrative(recon: dict[str, Any]) -> str:
        s = recon["summary"]
        return (
            f"返现对账 dry-run 完成：共 {s['record_count']} 条记录，"
            f"匹配 {s['matched']} / 异常 {s['mismatched']}，"
            f"对账总额 {s['total_amount']}。"
            f"is_dry_run=true，未做任何生产写入。"
        )


async def run_cashback_reconcile(
    file_path: str,
    *,
    actor: ActorContext,
    registry: ToolRegistry,
    gateway: ToolGateway,
    model_gateway: Optional[ModelGateway] = None,
    audit_service: AuditService,
    **kwargs: Any,
) -> CashbackReconcileResult:
    """Convenience entry point mirroring :meth:`CashbackReconcileWorkflow.run`."""
    return await CashbackReconcileWorkflow(
        registry=registry,
        gateway=gateway,
        model_gateway=model_gateway,
        audit_service=audit_service,
        **kwargs,
    ).run(file_path, actor)
