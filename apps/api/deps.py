"""API dependencies (phase B7, DEV_SPEC B7).

``get_current_actor`` is a placeholder until real authentication lands in
phase I (Entry Adapters). It returns a fixed dev actor so the user/permission
APIs are exercisable end-to-end now.
"""

from __future__ import annotations

from fiat_agent.schemas.common import ActorContext, Environment


def get_current_actor() -> ActorContext:
    """Return the currently authenticated actor (placeholder)."""
    return ActorContext(
        actor_id="dev-user",
        roles=["ops", "oncall"],
        environment=Environment.DEV,
    )
