"""Agent session + message API (phase I1, DEV_SPEC §I1).

Exposes the conversation surface of the agent:

* ``POST   /api/agent/sessions``            — create a task session
* ``POST   /api/agent/sessions/:id/messages`` — send a user turn, run the graph
* ``GET    /api/agent/sessions/:id/events``   — list the session event stream

All three depend on :func:`apps.api.agent_service.get_agent_service`, which the
test suite overrides with a hermetic instance.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from apps.api.agent_service import AgentService, _SessionNotFound, get_agent_service
from apps.api.deps import get_current_actor
from fiat_agent.schemas.common import ActorContext

router = APIRouter(prefix="/api/agent", tags=["agent"])


class CreateSessionRequest(BaseModel):
    title: str = ""
    task_type: str | None = None


class CreateSessionResponse(BaseModel):
    session_id: str
    title: str
    task_type: str | None = None
    environment: str
    status: str


class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1)


class SendMessageResponse(BaseModel):
    session_id: str
    final_answer: str | None = None
    task_type: str | None = None
    approval_state: str
    pending_tools: list[str] = Field(default_factory=list)


class EventView(BaseModel):
    event_id: str
    event_type: str
    seq: int
    content: dict | None = None
    created_at: str | None = None


class SessionView(BaseModel):
    session_id: str
    title: str
    task_type: str | None = None
    environment: str
    status: str
    created_at: str | None = None
    updated_at: str | None = None


class SessionsResponse(BaseModel):
    sessions: list[SessionView]


class EventsResponse(BaseModel):
    session_id: str
    events: list[EventView]


@router.get(
    "/sessions",
    response_model=SessionsResponse,
)
async def list_sessions(
    service: AgentService = Depends(get_agent_service),
) -> SessionsResponse:
    """List all task sessions (most-recently-updated first)."""
    rows = await service.list_sessions()
    return SessionsResponse(sessions=[SessionView(**r) for r in rows])


@router.post(
    "/sessions",
    response_model=CreateSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    req: CreateSessionRequest,
    actor: ActorContext = Depends(get_current_actor),
    service: AgentService = Depends(get_agent_service),
) -> CreateSessionResponse:
    """Create a new task session owned by the current actor."""
    view = await service.create_session(
        title=req.title,
        task_type=req.task_type,
        environment=actor.environment.value,
        actor_id=actor.actor_id,
    )
    return CreateSessionResponse(**view)


@router.post(
    "/sessions/{session_id}/messages",
    response_model=SendMessageResponse,
)
async def send_message(
    session_id: str,
    req: SendMessageRequest,
    actor: ActorContext = Depends(get_current_actor),
    service: AgentService = Depends(get_agent_service),
) -> SendMessageResponse:
    """Append a user message and run the agent graph for this session.

    Returns the final answer (or, for high-risk tools, an approval-pending
    state). Raises 404 if the session does not exist.
    """
    try:
        result = await service.run_message(
            session_id=session_id, actor=actor, content=req.content
        )
    except _SessionNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"session '{session_id}' not found",
        ) from None
    return SendMessageResponse(**result)


@router.get(
    "/sessions/{session_id}/events",
    response_model=EventsResponse,
)
async def list_events(
    session_id: str,
    service: AgentService = Depends(get_agent_service),
) -> EventsResponse:
    """Return the append-only event stream for a session in ``seq`` order."""
    events = await service.list_events(session_id=session_id)
    return EventsResponse(
        session_id=session_id,
        events=[EventView(**e) for e in events],
    )
