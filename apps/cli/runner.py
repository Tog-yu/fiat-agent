"""CLI runner logic (DEV_SPEC §I3).

Holds the interactive/one-shot behavior in a small, dependency-injectable class
so the argparse / uvicorn layers in :mod:`apps.cli.main` stay thin and the whole
thing is unit-testable without a real LLM or MCP server.

The runner consumes an :class:`~apps.api.agent_service.AgentService` (the same
component the FastAPI API uses), so the CLI and the HTTP API share one code path.
"""

from __future__ import annotations

import sys
from typing import Any, TextIO

from fiat_agent.schemas.common import ActorContext, Environment

# The actor the CLI acts as. A CLI operator is an on-call engineer on the dev
# environment by default; override via :meth:`CliRunner.__init__`.
_DEFAULT_ACTOR = ActorContext(
    actor_id="cli",
    roles=["oncall"],
    environment=Environment.DEV,
)


class CliRunner:
    """Drives the agent through the shared :class:`AgentService`."""

    def __init__(
        self,
        service: Any,
        *,
        actor: ActorContext | None = None,
        out_stream: TextIO | None = None,
    ) -> None:
        self._service = service
        self._actor = actor or _DEFAULT_ACTOR
        self._out = out_stream or sys.stdout

    async def once(self, content: str) -> dict:
        """Single question -> answer. Returns the run result dict.

        Creates a throwaway session, sends one user turn, and returns the
        :class:`AgentService.run_message` result (includes ``final_answer``).
        """
        session = await self._service.create_session(
            title="cli-once", task_type=None
        )
        return await self._service.run_message(
            session_id=session["session_id"],
            actor=self._actor,
            content=content,
        )

    async def chat(self, in_stream: TextIO | None = None) -> dict:
        """Interactive multi-turn loop. Reads lines from ``in_stream`` (stdin by
        default) and writes agent replies to :attr:`_out`.

        Exits on EOF, ``/exit``, ``/quit`` or an empty ``/quit`` line. Returns a
        small summary (session id + turn count) for testing.
        """
        in_stream = in_stream or sys.stdin
        session = await self._service.create_session(
            title="cli-chat", task_type=None
        )
        sid = session["session_id"]
        self._out.write("fiat-agent chat — 输入消息开始，/exit 退出\n")
        self._out.flush()

        turns = 0
        for raw in in_stream:
            line = raw.rstrip("\n")
            if line in ("/exit", "/quit"):
                break
            if not line.strip():
                continue
            result = await self._service.run_message(
                session_id=sid, actor=self._actor, content=line
            )
            answer = result.get("final_answer") or ""
            self._out.write(f"agent> {answer}\n")
            self._out.flush()
            turns += 1

        self._out.write("bye.\n")
        self._out.flush()
        return {"session_id": sid, "turns": turns}
