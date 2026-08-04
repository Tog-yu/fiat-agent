"""RAG 问答 workflow (phase H2, DEV_SPEC §H2 / §6).

Implements the knowledge-base Q&A business workflow:

1. **自动调用 MCP RAG** — the ``rag_query`` tool (backed by the MCP RAG server)
   is invoked through the audited :class:`ToolGateway`, so the call is gated by
   policy and recorded for audit like every other tool.
2. **回答带来源** — the retrieved chunks become :class:`Citation`\\ s that travel
   with the answer, and the model is prompted with the merged RAG context so it
   can ground its reply in the sources.
3. **无依据时拒答** — when the RAG lookup returns no citations, the workflow
   refuses with a deterministic, evidence-free message instead of guessing.

The workflow reuses the H1 ``rag_qa`` :class:`DomainSkill` for the domain system
prompt and :class:`~fiat_agent.context.builder.ContextBuilder` for assembling the
model context, keeping the agent loop's contracts intact.

Contract with the ``rag_query`` handler: it should return a
:class:`~fiat_agent.rag.context_merge.MergedRagContext` (the production handler
wraps ``RagMcpClient.query_knowledge_hub`` + ``merge_rag_context``). Other shapes
(string / dict / list of MCP content items) are coerced best-effort.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from fiat_agent.audit.service import AuditService
from fiat_agent.context.builder import ContextBuilder
from fiat_agent.models.base import ChatMessage, ChatRequest
from fiat_agent.models.gateway import ModelGateway
from fiat_agent.rag.context_merge import (
    Citation,
    MergedRagContext,
    merge_rag_context,
)
from fiat_agent.schemas.common import ActorContext, FiatModel, TaskType
from fiat_agent.skills.loader import DomainSkill, load_skill
from fiat_agent.tool_gateway.gateway import ToolGateway
from fiat_agent.tools.function_calling import ToolResultStatus
from fiat_agent.tools.registry import ToolRegistry

# The policy key / registered tool name for the RAG search (DEV_SPEC §F2 / H1).
RAG_TOOL = "rag_query"

# Deterministic refusal when the knowledge base has no relevant evidence.
_NO_EVIDENCE_ANSWER = (
    "无法确认该问题（知识库无相关依据），建议咨询对应业务负责人或补充知识库。"
)
_RAG_ERROR_ANSWER = (
    "知识库查询失败，无法确认该问题，建议稍后重试或咨询对应业务负责人。"
)


class RagQaResult(FiatModel):
    """Structured answer for the RAG-QA workflow (matches the ``rag_qa`` skill schema).

    ``confidence`` is one of ``high`` / ``medium`` / ``low``; ``has_evidence`` is
    ``False`` on every refusal so callers can branch without string-matching.
    """

    __test__ = False  # not a pytest test class

    query: str = ""
    answer: str = ""
    citations: list[Citation] = []
    confidence: str = "low"  # high | medium | low
    has_evidence: bool = False
    rag_status: str = "ok"  # ok | error
    error: Optional[str] = None


def _as_merged_rag_context(query: str, raw: Any) -> Optional[MergedRagContext]:
    """Coerce a ``rag_query`` handler output into a :class:`MergedRagContext`."""
    if raw is None:
        return None
    if isinstance(raw, MergedRagContext):
        return raw
    if isinstance(raw, list):
        return merge_rag_context(query, raw)
    if isinstance(raw, dict):
        answer = str(raw.get("answer", ""))
        cites_raw = raw.get("citations") or []
        if isinstance(cites_raw, list):
            cites: list[Citation] = [
                c if isinstance(c, Citation) else Citation(**c) for c in cites_raw
            ]
        else:
            cites = []
        return MergedRagContext(query=query, answer=answer, citations=cites)
    # str or other scalar: treat as answer text with no structured citations.
    return MergedRagContext(query=query, answer=str(raw), citations=[])


class RagQaWorkflow:
    """End-to-end RAG question-answering workflow."""

    def __init__(
        self,
        registry: ToolRegistry,
        gateway: ToolGateway,
        model_gateway: ModelGateway,
        audit_service: AuditService,
        builder: Optional[ContextBuilder] = None,
        skill: Optional[DomainSkill] = None,
        *,
        rag_tool: str = RAG_TOOL,
    ) -> None:
        self._registry = registry
        self._gateway = gateway
        self._model = model_gateway
        self._audit = audit_service
        self._builder = builder or ContextBuilder()
        self._skill = skill or load_skill(TaskType.RAG_QA)
        self._rag_tool = rag_tool

    async def run(
        self,
        query: str,
        actor: ActorContext,
        *,
        session_id: Optional[str] = None,
        event_emitter: Optional[Callable[[str, dict], Awaitable[None]]] = None,
    ) -> RagQaResult:
        """Answer ``query`` as a knowledge-base question for ``actor``.

        Args:
            query: the user's knowledge-base question.
            actor: the acting principal (drives RAG tool authorization).
            session_id: optional session id for traceability / events.
            event_emitter: optional ``(type, payload)`` sink for the event bus (K).
        """
        # 1) Automatically call RAG through the audited gateway.
        rag_result = await self._gateway.execute_tool(
            actor, self._rag_tool, {"query": query}
        )
        if rag_result.status != ToolResultStatus.SUCCESS:
            # RAG lookup failed -> no evidence, refuse deterministically.
            return RagQaResult(
                query=query,
                answer=_RAG_ERROR_ANSWER,
                citations=[],
                confidence="low",
                has_evidence=False,
                rag_status="error",
                error=rag_result.error,
            )

        merged = _as_merged_rag_context(query, rag_result.raw)
        citations = merged.citations if merged is not None else []

        # 2) Refuse when there is no evidence — never guess.
        if not citations:
            return RagQaResult(
                query=query,
                answer=_NO_EVIDENCE_ANSWER,
                citations=[],
                confidence="low",
                has_evidence=False,
            )

        # 3) Answer with sources: assemble context (skill prompt + RAG) and call model.
        built = self._builder.build(
            actor,
            self._registry,
            task_type=TaskType.RAG_QA,
            rag_context=merged,
            skill=self._skill,
        )
        messages = [
            ChatMessage(role="system", content=built.system_prompt),
            ChatMessage(role="user", content=query),
        ]
        response = await self._model.function_call(
            ChatRequest(messages=messages),
            task_type=TaskType.RAG_QA.value,
        )
        answer = response.content or ""

        if event_emitter is not None:
            await event_emitter(
                "rag_qa",
                {
                    "query": query,
                    "session_id": session_id,
                    "has_evidence": True,
                    "citation_count": len(citations),
                },
            )

        return RagQaResult(
            query=query,
            answer=answer,
            citations=citations,
            confidence="high",
            has_evidence=True,
            rag_status="ok",
        )


async def run_rag_qa(
    query: str,
    *,
    actor: ActorContext,
    registry: ToolRegistry,
    gateway: ToolGateway,
    model_gateway: ModelGateway,
    audit_service: AuditService,
    **kwargs: Any,
) -> RagQaResult:
    """Convenience entry point mirroring :meth:`RagQaWorkflow.run`."""
    return await RagQaWorkflow(
        registry=registry,
        gateway=gateway,
        model_gateway=model_gateway,
        audit_service=audit_service,
        **kwargs,
    ).run(query, actor)
