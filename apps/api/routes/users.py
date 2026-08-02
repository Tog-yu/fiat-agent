"""User / role query API (phase B7, DEV_SPEC B7)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.api.deps import get_current_actor
from fiat_agent.schemas.common import ActorContext

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/me")
def users_me(actor: ActorContext = Depends(get_current_actor)) -> dict:
    """Return the current user's id and roles."""
    return {
        "actor_id": actor.actor_id,
        "roles": actor.roles,
        "environment": actor.environment.value,
    }
