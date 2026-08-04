"""fiat-agent CLI entry point (DEV_SPEC §I3).

Three run modes:
  - ``once``   : single non-interactive Q&A (``fiat-agent once --message "..."``)
  - ``chat``   : interactive multi-turn REPL (reads stdin until /exit or EOF)
  - ``server`` : boots the FastAPI app via uvicorn

The agent is reached through the same :class:`~apps.api.agent_service.AgentService`
the HTTP API uses. The service is produced by :data:`_SERVICE_FACTORY`, which the
e2e tests monkeypatch with a hermetic (fake-graph, in-memory sqlite) instance so
no real LLM / MCP server is required.

Run as ``python -m apps.cli.main --help``.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Awaitable, Callable

from apps.api.agent_service import AgentService, build_agent_service
from apps.cli.runner import CliRunner

# Tests override this to inject a hermetic service factory (no real LLM/DB).
_SERVICE_FACTORY: Callable[[], Awaitable[AgentService]] = build_agent_service


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fiat-agent",
        description="法币定制 Agent CLI (fiat-agent)",
    )
    sub = parser.add_subparsers(dest="command", help="运行模式")

    once = sub.add_parser("once", help="单次问答（非交互）")
    once.add_argument(
        "-m", "--message", required=True, help="要发送给 Agent 的消息"
    )
    once.add_argument(
        "--environment",
        default="dev",
        choices=["dev", "staging", "prod"],
        help="运行环境（默认 dev）",
    )

    chat = sub.add_parser("chat", help="交互式多轮对话（/exit 退出）")
    chat.add_argument(
        "--environment",
        default="dev",
        choices=["dev", "staging", "prod"],
        help="运行环境（默认 dev）",
    )

    server = sub.add_parser("server", help="启动 FastAPI 服务")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8000)

    return parser


async def _run(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "server":
        import uvicorn

        uvicorn.run("apps.api.main:app", host=args.host, port=args.port)
        return 0

    service = await _SERVICE_FACTORY()
    runner = CliRunner(service)

    if args.command == "once":
        result = await runner.once(args.message)
        sys.stdout.write(f"{result.get('final_answer') or ''}\n")
        sys.stdout.flush()
        return 0

    if args.command == "chat":
        await runner.chat()
        return 0

    parser.print_help()
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    return asyncio.run(_run(argv))


if __name__ == "__main__":
    sys.exit(main())
