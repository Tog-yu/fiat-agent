"""Smoke test: package and CLI entry point import cleanly (phase A1).

Verifies the A1 skeleton is importable and the CLI exposes its `--help` surface.
Phase A2 (测试基座) will expand conftest / fixtures / markers.
"""

import importlib
import subprocess
import sys

import pytest


def test_fiat_agent_package_importable():
    mod = importlib.import_module("fiat_agent")
    assert mod.__name__ == "fiat_agent"


def test_cli_main_importable_and_callable():
    cli = importlib.import_module("apps.cli.main")
    assert callable(cli.main)
    assert isinstance(cli.build_parser(), object)


def test_cli_help_runs():
    result = subprocess.run(
        [sys.executable, "-m", "apps.cli.main", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "fiat-agent" in result.stdout
