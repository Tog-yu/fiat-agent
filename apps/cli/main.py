"""fiat-agent CLI entry point.

Phase A1 skeleton: defines the `chat` / `once` / `server` subcommands and a
minimal `--help` surface so the package is runnable as
`python -m apps.cli.main --help`. Real behavior is implemented in later phases.
"""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fiat-agent",
        description="法币定制 Agent CLI (fiat-agent)",
    )
    sub = parser.add_subparsers(dest="command", help="运行模式")

    sub.add_parser("chat", help="交互式多轮对话")
    sub.add_parser("once", help="单次问答（非交互）")
    sub.add_parser("server", help="启动 FastAPI 服务")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    # A1 占位：实际逻辑在后续阶段（D 模型网关 / G 编排 / I 入口适配器）实现。
    print(f"[fiat-agent] 子命令 '{args.command}' 尚未实现（阶段 A1 骨架）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
