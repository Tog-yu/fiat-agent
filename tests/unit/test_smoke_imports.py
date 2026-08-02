"""Smoke test: package and CLI entry point import cleanly (phase A1).

Phase A2 (测试基座) adds `tests/conftest.py` with shared fixtures
(`mock_llm`, `fake_backend`, `repo_root`) and registers the
unit / integration / e2e markers. This file exercises both: the A1 import
surface and the A2 fixture base.
"""

import importlib
import subprocess
import sys

import pytest


@pytest.mark.unit
def test_fiat_agent_package_importable():
    mod = importlib.import_module("fiat_agent")
    assert mod.__name__ == "fiat_agent"


@pytest.mark.unit
def test_cli_main_importable_and_callable():
    cli = importlib.import_module("apps.cli.main")
    assert callable(cli.main)
    assert isinstance(cli.build_parser(), object)


@pytest.mark.unit
def test_cli_help_runs():
    result = subprocess.run(
        [sys.executable, "-m", "apps.cli.main", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "fiat-agent" in result.stdout


@pytest.mark.unit
def test_test_base_fixtures_available(mock_llm, fake_backend, repo_root):
    # Prove the A2 test base is wired up: conftest fixtures are injectable and
    # follow DEV_SPEC §9 testing principles (LLM mocked, prod writes faked).
    resp = mock_llm.complete([{"role": "user", "content": "hi"}])
    assert resp.content == "ok"
    assert len(mock_llm.calls) == 1

    result = fake_backend.write({"op": "refund", "amount": 100})
    assert result == {"ok": True, "fake": True}
    assert len(fake_backend.writes) == 1

    assert repo_root.is_dir()
    assert (repo_root / "pyproject.toml").exists()
