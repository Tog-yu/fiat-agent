"""Agent state for the LangGraph orchestrator (phase G1, DEV_SPEC §G1).

:class:`AgentState` is the single mutable object threaded through every graph
node (classify -> plan -> tool -> approval -> final). It deliberately holds only
*serializable* building blocks (``ActorContext``, ``ChatMessage``,
``ToolResult``) so a snapshot can be persisted to the session event store and
later resumed / compacted.

Fields required by the spec: ``actor``, ``session``, ``messages``,
``task_type``, ``tool_results``, ``approval_state``.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from fiat_agent.models.base import ChatMessage
from fiat_agent.schemas.agent import ToolResult
from fiat_agent.schemas.common import ActorContext, FiatModel, TaskType


class ApprovalState(str, Enum):
    """Lifecycle of an approval requirement for the current run.

    ``NOT_REQUIRED`` until a node flags a high-risk tool; ``PENDING`` while a
    human decision is awaited; ``APPROVED`` / ``REJECTED`` once resolved (G6).
    """

    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class AgentState(FiatModel):
    """The orchestrator's working state — one object per agent run."""

    # Who is acting, in which environment, on which task (deterministic boundary).
    actor: ActorContext

    # Session this run belongs to (append-only event store key, phase C).
    session_id: str = ""

    # Conversation turns so far (model + tool messages).
    messages: list[ChatMessage] = []

    # Classified task type (G2); None until classified.
    task_type: Optional[TaskType] = None

    # Normalized results returned by executed tools (F3 / schemas.agent).
    tool_results: list[ToolResult] = []

    # Approval lifecycle for this run (G6).
    approval_state: ApprovalState = ApprovalState.NOT_REQUIRED

    # Built by the context node (G3): the system prompt and the permission-
    # filtered tool schemas handed to the model on the next turn.
    system_prompt: str = ""
    tool_schemas: list[dict[str, Any]] = []
