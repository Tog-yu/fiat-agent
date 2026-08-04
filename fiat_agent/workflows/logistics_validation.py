"""Logistics validation workflow (phase H7, DEV_SPEC §H7).

Drives the read-only ``logistics_validate`` tool through the audited gateway and
aggregates the deterministic checks (field validation + state machine, both
mandated by DEV_SPEC §2.2 to be model-free) into a structured report that
matches the ``logistics_validation`` domain skill output schema:

    {validated, invalid, field_errors[], state_violations[]}.

Hard guarantee: this workflow is **read-only** — it only ever calls the
read-only ``logistics_validate`` tool and never performs any production write.
The (optional) production-submit guard is handled by H8.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from fiat_agent.audit.service import AuditService
from fiat_agent.context.builder import ContextBuilder
from fiat_agent.models.base import ChatMessage, ChatRequest
from fiat_agent.models.gateway import ModelGateway
from fiat_agent.schemas.common import ActorContext, FiatModel, TaskType
from fiat_agent.skills.loader import DomainSkill, load_skill
from fiat_agent.tool_gateway.gateway import ToolGateway
from fiat_agent.tools.function_calling import ToolResultStatus
from fiat_agent.tools.registry import ToolRegistry
from fiat_agent.tool_gateway.logistics_tools import make_logistics_validate_handler
from fiat_agent.workflows.production_submit import ProductionSubmitGuard

# The read-only validation tool this workflow drives (DEV_SPEC §H7).
VALIDATE_TOOL = "logistics_validate"


class LogisticsValidationResult(FiatModel):
    """Structured logistics validation report (matches the skill output schema).

    Row numbers in ``field_errors`` / ``state_violations`` are **1-based** to
    match the domain skill contract (出错行号从 1 计).
    """

    __test__ = False  # not pytest

    file_path: str = ""
    validated: int = 0
    invalid: int = 0
    field_errors: list[dict[str, Any]] = []
    state_violations: list[dict[str, Any]] = []
    narrative: str = ""
    error: Optional[str] = None


class LogisticsValidationWorkflow:
    """End-to-end, read-only logistics validation."""

    def __init__(
        self,
        registry: ToolRegistry,
        gateway: ToolGateway,
        model_gateway: Optional[ModelGateway],
        audit_service: AuditService,
        builder: Optional[ContextBuilder] = None,
        skill: Optional[DomainSkill] = None,
        *,
        validate_tool: str = VALIDATE_TOOL,
    ) -> None:
        self._registry = registry
        self._gateway = gateway
        self._model = model_gateway
        self._audit = audit_service
        self._builder = builder or ContextBuilder()
        self._skill = skill or load_skill(TaskType.LOGISTICS_VALIDATION)
        self._validate_tool = validate_tool

    async def run(
        self,
        file_path: str,
        actor: ActorContext,
        *,
        field_map: Optional[dict[str, str]] = None,
        session_id: Optional[str] = None,
        event_emitter: Optional[Callable[[str, dict], Awaitable[None]]] = None,
    ) -> LogisticsValidationResult:
        """Validate the logistics file ``file_path`` for ``actor`` (read-only)."""
        # 1) Parse + validate through the audited gateway (never writes).
        parse_result = await self._gateway.execute_tool(
            actor,
            self._validate_tool,
            {"file_path": file_path, "field_map": field_map},
        )
        if parse_result.status != ToolResultStatus.SUCCESS:
            return LogisticsValidationResult(file_path=file_path, error=parse_result.error)

        parsed = parse_result.raw or {}
        report = self._aggregate(parsed)

        # 3) Optional model narrative on top of the deterministic report.
        narrative = await self._narrate(actor, report) if self._model else ""

        if event_emitter is not None:
            await event_emitter(
                "logistics_validation",
                {
                    "file_path": file_path,
                    "session_id": session_id,
                    "validated": report["validated"],
                    "invalid": report["invalid"],
                },
            )

        return LogisticsValidationResult(
            file_path=file_path,
            narrative=narrative,
            **report,
        )

    # --- aggregation core (deterministic) --------------------------------
    def _aggregate(self, parsed: dict[str, Any]) -> dict[str, Any]:
        """Turn a parse result into the skill-shaped report dict."""
        row_count = parsed.get("row_count", 0) or 0

        field_errors: list[dict[str, Any]] = [
            {
                "row": fe["row_index"] + 1,  # 1-based per skill contract
                "field": fe["field"],
                "reason": fe["detail"],
                "type": fe.get("type", "field_error"),
            }
            for fe in parsed.get("field_errors", []) or []
        ]
        state_violations: list[dict[str, Any]] = [
            {
                "row": sv["row_index"] + 1,  # 1-based per skill contract
                "from": sv["from_status"],
                "to": sv["to_status"],
                "reason": sv["detail"],
                "type": sv.get("type", "state_violation"),
            }
            for sv in parsed.get("state_violations", []) or []
        ]

        invalid_rows = {
            fe["row_index"] for fe in parsed.get("field_errors", []) or []
        } | {sv["row_index"] for sv in parsed.get("state_violations", []) or []}
        invalid = len(invalid_rows)
        validated = row_count - invalid

        return {
            "validated": validated,
            "invalid": invalid,
            "field_errors": field_errors,
            "state_violations": state_violations,
        }

    # --- optional model narrative ----------------------------------------
    async def _narrate(self, actor: ActorContext, report: dict[str, Any]) -> str:
        """Ask the model for a short human-readable summary (best-effort)."""
        try:
            built = self._builder.build(
                actor,
                self._registry,
                task_type=TaskType.LOGISTICS_VALIDATION,
                skill=self._skill,
            )
            payload = (
                "请基于以下物流校验结果，用一句话向运营同学总结要点（不要编造数字）：\n"
                f"{report}"
            )
            response = await self._model.function_call(
                ChatRequest(
                    messages=[
                        ChatMessage(role="system", content=built.system_prompt),
                        ChatMessage(role="user", content=payload),
                    ]
                ),
                task_type=TaskType.LOGISTICS_VALIDATION.value,
            )
            return (response.content or "").strip()
        except Exception:  # noqa: BLE001 - narrative is best-effort
            return self._fallback_narrative(report)

    @staticmethod
    def _fallback_narrative(report: dict[str, Any]) -> str:
        return (
            f"物流校验完成：共 {report['validated'] + report['invalid']} 行，"
            f"通过 {report['validated']} / 异常 {report['invalid']}。"
            f"未做任何生产写入。"
        )

    # --- phase-2 reserved interface (H8) ---------------------------------
    async def submit(
        self,
        approval_id: str,
        actor: ActorContext,
        guard: ProductionSubmitGuard,
        *,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Submit the validated plan to production (phase-2 reserved).

        Gated by an approved ``Approval`` through :class:`ProductionSubmitGuard`.
        In the MVP the guard is disabled by default, so this performs only a safe
        fake stub unless the approval *and* explicit enablement are both
        satisfied. Deterministic boundary per DEV_SPEC §2.2.6 (never LLM-driven).
        """
        result = await guard.submit(approval_id, actor, params=params or {})
        await self._audit.record_event(
            type="production_submit",
            actor=actor,
            tool_name="logistics_submit",
            action="submit",
            allowed=bool(result.get("submitted")),
            metadata={"approval_id": approval_id, **result},
        )
        return result


async def run_logistics_validation(
    file_path: str,
    *,
    actor: ActorContext,
    registry: ToolRegistry,
    gateway: ToolGateway,
    model_gateway: Optional[ModelGateway] = None,
    audit_service: AuditService,
    **kwargs: Any,
) -> LogisticsValidationResult:
    """Convenience entry point mirroring :meth:`LogisticsValidationWorkflow.run`."""
    return await LogisticsValidationWorkflow(
        registry=registry,
        gateway=gateway,
        model_gateway=model_gateway,
        audit_service=audit_service,
        **kwargs,
    ).run(file_path, actor)
