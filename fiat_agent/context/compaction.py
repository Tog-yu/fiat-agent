"""Context compaction (phase C5, DEV_SPEC C5).

Compresses a session's event window into a :class:`CompactionSummary` so the
agent context can be trimmed before it overflows. Original events are NEVER
deleted — compaction only appends a new ``compaction`` event referencing the
originals (DEV_SPEC C5: "原始事件不删除").
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from pydantic import Field

from fiat_agent.schemas.common import FiatModel
from fiat_agent.sessions.store import SessionStore, TaskSessionEvent

_RISK_ORDER = {"L1": 1, "L2": 2, "L3": 3, "L4": 4, "L5": 5}


class CompactionSummary(FiatModel):
    """Condensed view of a window of session events."""

    user_goal: str = ""
    tool_results: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    approval_status: str = "none"  # none | pending | approved | rejected
    risk_status: str = "none"  # none | L1..L5 (highest seen)
    next_steps: list[str] = Field(default_factory=list)
    original_event_ids: list[str] = Field(default_factory=list)
    compacted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def _estimate_tokens(content: Optional[dict]) -> int:
    if not content:
        return 0
    return len(json.dumps(content, ensure_ascii=False, default=str)) // 4 + 1


def should_compact(events: list[TaskSessionEvent], *, token_threshold: int = 4000) -> bool:
    """True when the window's estimated tokens exceed ``token_threshold`` (or it
    is empty). The estimator is a cheap char/4 heuristic — good enough to decide
    whether to compact before the real LLM context window overflows."""
    if not events:
        return False
    total = sum(_estimate_tokens(e.content) for e in events)
    return total > token_threshold


def compact_events(events: list[TaskSessionEvent]) -> CompactionSummary:
    """Build a :class:`CompactionSummary` from a window of events.

    Heuristic (pragmatic, deterministic):
      - ``user_goal``: text of the first user message (or ``goal``/``task`` field)
      - ``tool_results``: one line per tool_call event ("name: short result")
      - ``references``: any ``references`` lists found on events
      - ``approval_status``: approved > rejected > pending > none
      - ``risk_status``: highest RiskLevel seen across events
      - ``next_steps``: ``next_steps`` field on the last event (if present)
    """
    summary = CompactionSummary(original_event_ids=[e.id for e in events])

    for ev in events:
        c = ev.content or {}

        if ev.event_type == "message" and c.get("role") == "user" and not summary.user_goal:
            summary.user_goal = (c.get("text") or c.get("goal") or c.get("task") or "").strip()

        if ev.event_type == "tool_call":
            name = c.get("tool_name") or "tool"
            result = c.get("result")
            snippet = (json.dumps(result, ensure_ascii=False, default=str)[:120]
                       if result is not None else "")
            summary.tool_results.append(f"{name}: {snippet}".strip())

        refs = c.get("references")
        if isinstance(refs, list):
            summary.references.extend(str(r) for r in refs)

        if ev.event_type == "approval":
            status = (c.get("status") or "none").lower()
            rank = {"rejected": 3, "approved": 2, "pending": 1, "none": 0}
            if rank.get(status, 0) > rank.get(summary.approval_status, 0):
                summary.approval_status = status

        risk = c.get("risk_level")
        if risk and _RISK_ORDER.get(risk, 0) > _RISK_ORDER.get(summary.risk_status, 0):
            summary.risk_status = risk

    last = events[-1].content or {}
    nxt = last.get("next_steps")
    if isinstance(nxt, list):
        summary.next_steps.extend(str(s) for s in nxt)

    return summary


class CompactionService:
    """Appends compaction summaries without touching original events."""

    def __init__(self, store: SessionStore | None = None) -> None:
        self._store = store or SessionStore()

    async def append_compaction_event(
        self,
        session,
        *,
        session_id: str,
        summary: CompactionSummary,
        parent_event_id: str | None = None,
    ) -> TaskSessionEvent:
        """Append a ``compaction`` event referencing the originals. No deletes."""
        return await self._store.append_event(
            session,
            session_id=session_id,
            event_type="compaction",
            content=summary.model_dump(mode="json"),
            parent_event_id=parent_event_id,
        )
