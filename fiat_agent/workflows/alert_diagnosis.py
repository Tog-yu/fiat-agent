"""告警诊断 workflow (phase H3, DEV_SPEC §H3 / §6).

Implements the alert triage business workflow:

1. **并行查询 ES / DB / RAG** — ``es_query`` (logs/metrics), ``db_query``
   (business data) and ``rag_query`` (runbooks / docs) are issued concurrently
   through the audited :class:`ToolGateway`, so each call is policy-gated and
   recorded for audit like every other tool.
2. **结构化诊断** — the collected evidence plus the H1 ``alert_diagnosis``
   :class:`DomainSkill` prompt are fed to :class:`ModelGateway`; the model
   returns JSON matching the skill ``output_schema`` (impact / possible_causes /
   confidence / next_steps).
3. **可发 Lark 通知** — when the diagnosed ``severity`` is ``P0``/``P1`` (or the
   caller forces it), the workflow deterministically sends a ``lark_notify``
   summary through the gateway and records ``lark_notified`` on the result.

The workflow only reads and notifies — it never performs any write or change
action, matching the skill's "只读诊断与通知" constraint.

Contracts with the tool handlers:

* ``es_query`` / ``db_query`` — return anything coercible to a string summary
  (str / dict / list). The summary is shown to the model.
* ``rag_query`` — returns a :class:`~fiat_agent.rag.context_merge.MergedRagContext`
  (or a string/dict best-effort coerced); its ``answer`` feeds the model.
* ``lark_notify`` — receives ``{"chat_id": str, "content": str}`` and returns a
  send receipt (any shape; only success/error matters to the workflow).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable, Optional

from fiat_agent.audit.service import AuditService
from fiat_agent.context.builder import ContextBuilder
from fiat_agent.models.base import ChatMessage, ChatRequest
from fiat_agent.models.gateway import ModelGateway
from fiat_agent.rag.context_merge import MergedRagContext
from fiat_agent.schemas.common import ActorContext, FiatModel, TaskType
from fiat_agent.skills.loader import DomainSkill, load_skill
from fiat_agent.tool_gateway.gateway import ToolGateway
from fiat_agent.tools.function_calling import ToolResultStatus
from fiat_agent.tools.registry import ToolRegistry

# Tool names (policy keys / registered handler names). H3 wires four of the
# alert_diagnosis skill's tools; all are configurable for testing.
ES_TOOL = "es_query"
DB_TOOL = "db_query"
RAG_TOOL = "rag_query"
LARK_TOOL = "lark_notify"

# Severity levels that warrant a proactive Lark page.
_HIGH_SEVERITY = {"P0", "P1"}

# Detectors run when no real Lark tenant is available; the workflow only needs
# to know whether the notification was sent.
_NO_LARK_CHAT = "NO_LARK_CHAT"


class AlertDiagnosisResult(FiatModel):
    """Structured diagnosis for the alert workflow (matches the skill schema).

    ``lark_notified`` is set by the *workflow* (it orchestrates the page), not by
    the model, so callers can trust it reflects an actual gateway call.
    """

    __test__ = False  # not a pytest test class

    alert: str = ""
    impact: dict[str, Any] = {}
    possible_causes: list[dict[str, Any]] = []
    confidence: str = "low"  # high | medium | low
    next_steps: list[str] = []
    lark_notified: bool = False
    evidence: dict[str, Any] = {}
    tool_errors: dict[str, str] = {}
    error: Optional[str] = None


def _coerce_summary(raw: Any) -> str:
    """Best-effort text summary of a tool's raw output for the model context."""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, MergedRagContext):
        return raw.answer or ""
    if isinstance(raw, (dict, list)):
        try:
            return json.dumps(raw, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return str(raw)
    return str(raw)


def _parse_model_json(content: Optional[str]) -> dict[str, Any]:
    """Extract a JSON object from a model reply, tolerating code fences."""
    if not content:
        return {}
    text = content.strip()
    # Strip a ```json ... ``` or ``` ... ``` fence if present.
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


class AlertDiagnosisWorkflow:
    """End-to-end alert diagnosis workflow."""

    def __init__(
        self,
        registry: ToolRegistry,
        gateway: ToolGateway,
        model_gateway: ModelGateway,
        audit_service: AuditService,
        builder: Optional[ContextBuilder] = None,
        skill: Optional[DomainSkill] = None,
        *,
        es_tool: str = ES_TOOL,
        db_tool: str = DB_TOOL,
        rag_tool: str = RAG_TOOL,
        lark_tool: str = LARK_TOOL,
    ) -> None:
        self._registry = registry
        self._gateway = gateway
        self._model = model_gateway
        self._audit = audit_service
        self._builder = builder or ContextBuilder()
        self._skill = skill or load_skill(TaskType.ALERT_DIAGNOSIS)
        self._es_tool = es_tool
        self._db_tool = db_tool
        self._rag_tool = rag_tool
        self._lark_tool = lark_tool

    async def run(
        self,
        alert: str,
        actor: ActorContext,
        *,
        lark_chat_id: Optional[str] = None,
        force_lark: bool = False,
        session_id: Optional[str] = None,
        event_emitter: Optional[Callable[[str, dict], Awaitable[None]]] = None,
    ) -> AlertDiagnosisResult:
        """Diagnose ``alert`` for ``actor``.

        Args:
            alert: the alert text / symptom description.
            actor: the acting principal (drives tool authorization).
            lark_chat_id: target Lark chat for the page; if ``None`` and a page is
                warranted, ``lark_notified`` stays ``False`` (no recipient).
            force_lark: send the page regardless of severity (for explicit asks).
            session_id: optional session id for traceability / events.
            event_emitter: optional ``(type, payload)`` sink for the event bus (K).
        """
        # 1) Parallel evidence collection: ES + DB + RAG through the audited gateway.
        es_task = self._gateway.execute_tool(actor, self._es_tool, {"query": alert})
        db_task = self._gateway.execute_tool(actor, self._db_tool, {"query": alert})
        rag_task = self._gateway.execute_tool(actor, self._rag_tool, {"query": alert})
        es_res, db_res, rag_res = await asyncio.gather(es_task, db_task, rag_task)

        evidence: dict[str, Any] = {}
        tool_errors: dict[str, str] = {}
        rag_context: Optional[MergedRagContext] = None

        for tool_name, res in (
            (self._es_tool, es_res),
            (self._db_tool, db_res),
            (self._rag_tool, rag_res),
        ):
            if res.status != ToolResultStatus.SUCCESS:
                tool_errors[tool_name] = res.error or "tool failed"
                continue
            if tool_name == self._rag_tool and isinstance(res.raw, MergedRagContext):
                rag_context = res.raw
                evidence["rag"] = rag_context.answer or ""
            else:
                evidence[tool_name] = _coerce_summary(res.raw)

        # 2) Structured diagnosis: assemble context (skill prompt + evidence) + model.
        built = self._builder.build(
            actor,
            self._registry,
            task_type=TaskType.ALERT_DIAGNOSIS,
            rag_context=rag_context,
            skill=self._skill,
        )
        evidence_block = "\n".join(
            f"【{src}】\n{text}" for src, text in evidence.items() if text
        )
        user_content = alert
        if evidence_block:
            user_content = f"{alert}\n\n收集到的证据：\n{evidence_block}"

        messages = [
            ChatMessage(role="system", content=built.system_prompt),
            ChatMessage(role="user", content=user_content),
        ]
        response = await self._model.function_call(
            ChatRequest(messages=messages),
            task_type=TaskType.ALERT_DIAGNOSIS.value,
        )
        parsed = _parse_model_json(response.content)

        impact = parsed.get("impact", {})
        possible_causes = parsed.get("possible_causes", [])
        confidence = parsed.get("confidence", "low")
        next_steps = parsed.get("next_steps", [])

        # 3) Lark page on high severity (or when forced), through the audited gateway.
        severity = str(impact.get("severity", "")).upper() if isinstance(impact, dict) else ""
        lark_notified = False
        if (force_lark or severity in _HIGH_SEVERITY) and lark_chat_id:
            summary = self._lark_summary(alert, impact, severity)
            lark_res = await self._gateway.execute_tool(
                actor,
                self._lark_tool,
                {"chat_id": lark_chat_id, "content": summary},
            )
            lark_notified = lark_res.status == ToolResultStatus.SUCCESS
            if not lark_notified:
                tool_errors[self._lark_tool] = lark_res.error or "lark notify failed"

        if event_emitter is not None:
            await event_emitter(
                "alert_diagnosis",
                {
                    "alert": alert,
                    "session_id": session_id,
                    "severity": severity,
                    "lark_notified": lark_notified,
                    "tool_errors": tool_errors,
                },
            )

        return AlertDiagnosisResult(
            alert=alert,
            impact=impact if isinstance(impact, dict) else {},
            possible_causes=possible_causes if isinstance(possible_causes, list) else [],
            confidence=confidence if confidence in {"high", "medium", "low"} else "low",
            next_steps=next_steps if isinstance(next_steps, list) else [],
            lark_notified=lark_notified,
            evidence=evidence,
            tool_errors=tool_errors,
            error=None,
        )

    @staticmethod
    def _lark_summary(alert: str, impact: dict[str, Any], severity: str) -> str:
        """Concise human-readable page for the on-call chat."""
        scope = impact.get("scope", "未知范围") if isinstance(impact, dict) else "未知范围"
        services = impact.get("affected_services", []) if isinstance(impact, dict) else []
        svc = ", ".join(services) if services else "未知服务"
        return (
            f"[告警诊断] 严重级别 {severity or '未知'}\n"
            f"告警：{alert}\n"
            f"影响范围：{scope}\n"
            f"受影响服务：{svc}"
        )


async def run_alert_diagnosis(
    alert: str,
    *,
    actor: ActorContext,
    registry: ToolRegistry,
    gateway: ToolGateway,
    model_gateway: ModelGateway,
    audit_service: AuditService,
    **kwargs: Any,
) -> AlertDiagnosisResult:
    """Convenience entry point mirroring :meth:`AlertDiagnosisWorkflow.run`.

    ``lark_chat_id`` / ``force_lark`` / ``session_id`` / ``event_emitter`` are
    forwarded to :meth:`AlertDiagnosisWorkflow.run`; the rest configure the
    workflow instance.
    """
    run_keys = {"lark_chat_id", "force_lark", "session_id", "event_emitter"}
    run_kwargs = {k: kwargs.pop(k) for k in run_keys if k in kwargs}
    return await AlertDiagnosisWorkflow(
        registry=registry,
        gateway=gateway,
        model_gateway=model_gateway,
        audit_service=audit_service,
        **kwargs,
    ).run(alert, actor, **run_kwargs)
