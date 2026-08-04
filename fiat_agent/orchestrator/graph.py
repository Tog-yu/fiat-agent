"""Agent orchestrator graph (phase G8, DEV_SPEC §G8).

Wires the G1–G7 nodes into one complete LangGraph ReAct loop:

    START -> classify -> build_context -> model
    model --(tool_calls)--> plan -> approval --(ok)--> tool -> model
    model --(no tool_calls)--> final -> END
    approval --(PENDING)--> END   (await human approval; no execution)

* ``classify_node`` (G2) sets the task type from the latest user turn.
* ``build_context_node`` (G3) assembles the permission-filtered system prompt
  and tool schemas.
* ``model`` step calls the :class:`~fiat_agent.models.gateway.ModelGateway`
  (deterministic planning / function calling) and appends the assistant turn.
* ``plan_node`` (G4) derives a structured plan from the model's tool calls and
  validates it (deterministic, never LLM-driven gating).
* ``approval_node`` (G6) inspects the candidate tools and halts high-risk runs
  until a human approves.
* ``tool_node`` (G5) dispatches through the audited, policy-gated
  :class:`~fiat_agent.tool_gateway.gateway.ToolGateway` and feeds every result
  back to the model.
* ``final_node`` (G7) renders the fixed-format answer.

Every step emits session/event records through optional callbacks, so a run is
observable (session writes + event stream) without coupling the graph to a
specific store (phases C / K).
"""

from __future__ import annotations

from typing import Annotated, Any, Awaitable, Callable, Optional
from uuid import uuid4

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from fiat_agent.auth.policy import can_execute
from fiat_agent.auth.rbac import load_tool_policies
from fiat_agent.models.base import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    FunctionCall,
)
from fiat_agent.models.gateway import ModelGateway
from fiat_agent.orchestrator.nodes.approval import approval_node
from fiat_agent.orchestrator.nodes.build_context import build_context_node
from fiat_agent.orchestrator.nodes.classify import classify_node
from fiat_agent.orchestrator.nodes.final import final_node
from fiat_agent.orchestrator.nodes.plan import PlanStatus, PlanningResult, plan_node
from fiat_agent.orchestrator.nodes.tool import tool_node
from fiat_agent.orchestrator.state import AgentState, ApprovalState
from fiat_agent.schemas.agent import ToolResult as SchemaToolResult
from fiat_agent.schemas.common import ActorContext, RiskLevel
from fiat_agent.tool_gateway.gateway import ToolGateway
from fiat_agent.tools.registry import ToolRegistry


def _concat(left: Any, right: Any) -> Any:
    """Append-reducer: concatenate the update list onto the existing channel."""
    return (left or []) + (right or [])


class GraphState(AgentState):
    """LangGraph state schema for the orchestrator.

    Extends :class:`AgentState` with the channels the G-nodes write back
    (``plan`` / ``plan_status`` from G4, ``pending_approvals`` from G6,
    ``final_answer`` from G7). ``messages`` and ``tool_results`` use append
    reducers so the ReAct loop accumulates history across turns instead of
    overwriting it.
    """

    # Append-only channels (ReAct loop accumulates across turns).
    messages: Annotated[list[ChatMessage], _concat] = []  # type: ignore[assignment]
    tool_results: Annotated[list[SchemaToolResult], _concat] = []  # type: ignore[assignment]

    # Plan / approval / final channels written by the G-nodes.
    plan: Optional[PlanningResult] = None
    plan_status: Optional[PlanStatus] = None
    pending_approvals: list[str] = []
    final_answer: Optional[str] = None


# Optional observer callbacks invoked at each major step so the run is
# observable. Both receive ``(event_type, payload)``.
SessionWriter = Callable[[str, dict[str, Any]], Awaitable[None]]
EventEmitter = Callable[[str, dict[str, Any]], Awaitable[None]]

# Trace sink records one dict per node invocation; see ``record_trace`` in
# :mod:`fiat_agent.audit.service`. Keys: session_id, actor_id, round, step,
# node, status, detail.
TraceSink = Callable[[dict[str, Any]], Awaitable[None]]


class AgentGraph:
    """Builds and runs the complete fiat-agent LangGraph."""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        gateway: ToolGateway,
        model_gateway: ModelGateway,
        audit_service: Any = None,
        approval_service: Any = None,
        session_writer: Optional[SessionWriter] = None,
        event_emitter: Optional[EventEmitter] = None,
        trace_sink: Optional[TraceSink] = None,
    ) -> None:
        self.registry = registry
        self.gateway = gateway
        self.model_gateway = model_gateway
        self.audit_service = audit_service
        self.approval_service = approval_service
        self.session_writer = session_writer
        self.event_emitter = event_emitter
        self.trace_sink = trace_sink
        self._compiled = None
        # Per-run trace context (set in arun); round increments per model call.
        self._round = 0
        self._trace_session = ""
        self._trace_actor = ""

    # --- node steps ----------------------------------------------------

    async def _classify_step(self, state: GraphState) -> dict:
        async def work():
            delta = classify_node(state)
            await self._emit("classify", {"task_type": delta.get("task_type")})
            return delta

        return await self._run_traced("classify", "classify", work())

    async def _build_context_step(self, state: GraphState) -> dict:
        async def work():
            return build_context_node(state, self.registry)

        return await self._run_traced("build_context", "build_context", work())

    async def _model_step(self, state: GraphState) -> dict:
        self._round += 1  # each model call starts a new ReAct round

        async def work():
            request = self._build_request(state)
            task_type = state.task_type.value if state.task_type else None
            response: ChatResponse = await self.model_gateway.function_call(
                request, task_type=task_type
            )
            assistant = self._response_to_message(response)
            await self._emit(
                "model_call",
                {
                    "finish_reason": response.finish_reason,
                    "has_tool_calls": bool(assistant.tool_calls),
                    "usage": response.usage.model_dump() if response.usage else None,
                },
            )
            return {"messages": [assistant]}

        return await self._run_traced("model_call", "model", work())

    def _build_request(self, state: GraphState) -> ChatRequest:
        system = ChatMessage(role="system", content=state.system_prompt or "")
        return ChatRequest(messages=[system, *state.messages], tools=state.tool_schemas or None)

    @staticmethod
    def _response_to_message(response: ChatResponse) -> ChatMessage:
        tool_calls = None
        if response.function_calls:
            tool_calls = [
                FunctionCall(
                    name=fc.name,
                    arguments=fc.arguments or "",
                    id=fc.id or uuid4().hex,
                )
                for fc in response.function_calls
            ]
        return ChatMessage(role="assistant", content=response.content, tool_calls=tool_calls)

    async def _plan_step(self, state: GraphState) -> dict:
        async def work():
            available = {
                t.name
                for t in self.registry.filter(
                    state.actor, environment=state.actor.environment
                )
            }
            delta = plan_node(state, self._derive_plan, available_tools=available)
            plan = delta.get("plan")
            await self._emit(
                "plan",
                {
                    "plan_status": delta.get("plan_status"),
                    "required_tools": list(plan.required_tools) if plan else [],
                },
            )
            return delta

        return await self._run_traced("plan", "plan", work())

    def _derive_plan(self, state: GraphState) -> Optional[dict]:
        """Deterministic planner: derive a structured plan from the model's pending tool calls.

        Used as the ``planner`` callable for :func:`plan_node`. It never calls an
        LLM — it reads the assistant message's tool calls and classifies each via
        the deterministic ``can_execute`` boundary (DEV_SPEC §2.2).
        """
        calls = []
        for msg in reversed(state.messages):
            if msg.role == "assistant" and msg.tool_calls:
                calls = msg.tool_calls
                break
        if not calls:
            return None
        names = [c.name for c in calls]
        risk = RiskLevel.L1
        need_approval = False
        for name in names:
            decision = can_execute(state.actor, name)
            if decision.risk_level is not None and decision.risk_level.value > risk.value:
                risk = decision.risk_level
            if decision.approval_required:
                need_approval = True
        return {
            "steps": [f"call {n}" for n in names],
            "required_tools": names,
            "risk_level": risk,
            "need_approval": need_approval,
        }

    async def _approval_step(self, state: GraphState) -> dict:
        async def work():
            delta = await approval_node(
                state,
                plan=state.plan,
                audit_service=self.audit_service,
                approval_service=self.approval_service,
            )
            await self._emit(
                "approval",
                {
                    "approval_state": delta.get("approval_state"),
                    "pending": delta.get("pending_approvals"),
                    "approval_id": delta.get("approval_id"),
                },
            )
            return delta

        return await self._run_traced("approval", "approval", work())

    async def _tool_step(self, state: GraphState) -> dict:
        def _tool_status(delta: dict) -> tuple[str, dict]:
            """Mark the tool node as failed when any tool reported an error."""
            results = delta.get("tool_results", [])
            failed = [
                r
                for r in results
                if getattr(r.status, "value", r.status) != "success"
            ]
            if failed:
                return "error", {
                    "failed_tools": [r.tool_name for r in failed],
                    "errors": [getattr(r, "error", None) for r in failed],
                }
            return "ok", None

        async def work():
            delta = await tool_node(state, self.gateway, context=None)
            results = delta.get("tool_results", [])
            # Enrich with per-tool detail (arguments, status, risk, duration) so the
            # web console tool-call trace (J3) and audit page (J6) can render richly.
            policy_risk = {
                name: p.risk_level for name, p in load_tool_policies().items()
            }
            recent = self.gateway.tool_calls[-len(results):] if self.gateway else []
            calls = []
            for r in results:
                rec = next(
                    (x for x in reversed(recent) if x.tool_name == r.tool_name), None
                )
                calls.append(
                    {
                        "tool_name": r.tool_name,
                        "arguments": (rec.arguments if rec else {}),
                        "status": r.status.value,
                        "risk_level": policy_risk.get(r.tool_name),
                        "duration_ms": (
                            round(rec.duration_ms, 1) if rec is not None else None
                        ),
                    }
                )
            await self._emit(
                "tool_call",
                {
                    "tools": [r.tool_name for r in results],
                    "statuses": [r.status.value for r in results],
                    "calls": calls,
                },
            )
            return delta

        return await self._run_traced("tool_call", "tool", work(), status_fn=_tool_status)

    async def _final_step(self, state: GraphState) -> dict:
        async def work():
            # For RAG answers the answer text is carried by the tool result;
            # final_node renders tool_results when no explicit rag_context is set.
            delta = final_node(state, rag_context=None)
            await self._emit("final", {"answer": (delta.get("final_answer") or "")[:200]})
            await self._emit("session_final", {"final_answer": delta.get("final_answer")})
            return delta

        return await self._run_traced("final", "final", work())

    async def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.session_writer is not None:
            await self.session_writer(event_type, payload)
        if self.event_emitter is not None:
            await self.event_emitter(event_type, payload)

    async def _trace(
        self,
        step: str,
        node: str,
        status: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        """Record one agent-trace step (DEV_SPEC §K3), if a sink is wired."""
        if self.trace_sink is None:
            return
        await self.trace_sink(
            {
                "session_id": self._trace_session,
                "actor_id": self._trace_actor,
                "round": self._round,
                "step": step,
                "node": node,
                "status": status,
                "detail": detail or {},
            }
        )

    async def _run_traced(
        self,
        step: str,
        node: str,
        coro,
        status_fn=None,
    ):
        """Run a node coroutine, recording ok/error in the agent trace.

        ``status_fn(result) -> (status, detail)`` lets a node declare a
        logical failure even when it returns normally (e.g. a tool that
        completed but reported an error result), so the failed node stays
        locatable (DEV_SPEC §K3). On an raised exception, ``error`` is recorded
        and the exception re-raised for normal propagation.
        """
        try:
            result = await coro
            if status_fn is not None:
                status, detail = status_fn(result)
            else:
                status, detail = "ok", None
            await self._trace(step, node, status, detail)
            return result
        except Exception as e:  # noqa: BLE001 - record then propagate
            await self._trace(step, node, "error", {"error": str(e)})
            raise

    # --- routing -------------------------------------------------------

    @staticmethod
    def _route_after_model(state: GraphState) -> str:
        for msg in reversed(state.messages):
            if msg.role == "assistant":
                return "plan" if msg.tool_calls else "final"
        return "final"

    @staticmethod
    def _route_after_approval(state: GraphState) -> str:
        return END if state.approval_state == ApprovalState.PENDING else "tool"

    # --- compile / run -------------------------------------------------

    def _get_graph(self):
        if self._compiled is None:
            g = StateGraph(GraphState)
            g.add_node("classify", self._classify_step)
            g.add_node("build_context", self._build_context_step)
            g.add_node("model", self._model_step)
            g.add_node("plan", self._plan_step)
            g.add_node("approval", self._approval_step)
            g.add_node("tool", self._tool_step)
            g.add_node("final", self._final_step)

            g.set_entry_point("classify")
            g.add_edge("classify", "build_context")
            g.add_edge("build_context", "model")
            g.add_conditional_edges(
                "model", self._route_after_model, {"plan": "plan", "final": "final"}
            )
            g.add_edge("plan", "approval")
            g.add_conditional_edges(
                "approval", self._route_after_approval, {"tool": "tool", END: END}
            )
            g.add_edge("tool", "model")
            g.add_edge("final", END)

            self._compiled = g.compile(checkpointer=MemorySaver())
        return self._compiled

    async def arun(
        self,
        *,
        actor: ActorContext,
        messages: list[ChatMessage],
        session_id: str = "",
        config: Optional[dict] = None,
        session_writer: Optional[SessionWriter] = None,
        event_emitter: Optional[EventEmitter] = None,
        trace_sink: Optional[TraceSink] = None,
    ) -> GraphState:
        """Run one agent turn end-to-end and return the final :class:`GraphState`.

        ``session_writer`` / ``event_emitter`` are accepted per-run (in addition
        to the instance-level callbacks set at construction) so a single shared
        :class:`AgentGraph` can stream events into different destinations per
        session — e.g. the FastAPI API writes each run's events into that
        session's append-only event store (phase I1). When omitted, the
        instance-level callbacks are used.
        """
        graph = self._get_graph()
        thread_id = session_id or uuid4().hex
        cfg = config or {"configurable": {"thread_id": thread_id}}
        inputs = {
            "actor": actor,
            "messages": messages,
            "session_id": session_id,
        }
        # Per-run observer overrides, restored afterwards so the shared instance
        # keeps its construction-time callbacks for other callers.
        prev_writer, prev_emitter, prev_trace = (
            self.session_writer,
            self.event_emitter,
            self.trace_sink,
        )
        if session_writer is not None:
            self.session_writer = session_writer
        if event_emitter is not None:
            self.event_emitter = event_emitter
        if trace_sink is not None:
            self.trace_sink = trace_sink
        # Reset per-run trace context.
        self._round = 0
        self._trace_session = session_id
        self._trace_actor = actor.actor_id if actor else ""
        try:
            result = await graph.ainvoke(inputs, config=cfg, recursion_limit=25)
        finally:
            self.session_writer, self.event_emitter, self.trace_sink = (
                prev_writer,
                prev_emitter,
                prev_trace,
            )
        try:
            return GraphState(**result)
        except Exception:  # noqa: BLE001 - fall back to the raw state dict
            return result
