"""Shared pytest fixtures for the fiat-agent test base (phase A2).

Implements the testing principles from DEV_SPEC §9:
  - §9.2.1 LLM calls are mocked by default  -> `mock_llm`
  - §9.2.3 production writes use a fake backend -> `fake_backend`
  - tests run from the repo root, so config/ is discoverable -> `repo_root`

These fixtures are intentionally dependency-free (stdlib + pytest only) so the
base works before the heavy stack (FastAPI / LangGraph / SQLAlchemy) is installed
in later phases. Later task-specific fixtures should be added here.
"""

from __future__ import annotations

import dataclasses
import pathlib

import pytest

# tests/conftest.py -> repo root (fiat-agent/)
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


@dataclasses.dataclass
class FakeModelResponse:
    """Minimal stand-in for a chat-model response used by `mock_llm`."""

    content: str = "ok"
    tool_calls: list = dataclasses.field(default_factory=list)
    usage: dict = dataclasses.field(default_factory=dict)


class MockLLM:
    """Deterministic stand-in for a chat model (DEV_SPEC §9.2.1).

    Records every `complete` call so tests can assert on model interaction
    without touching a real provider or leaking an API key.
    """

    def __init__(self, response: FakeModelResponse | None = None):
        self.response = response or FakeModelResponse()
        self.calls: list[tuple[list, dict]] = []

    def complete(self, messages: list, **kwargs) -> FakeModelResponse:
        self.calls.append((messages, kwargs))
        return self.response


class FakeBackend:
    """Fake production backend: writes are recorded no-ops (DEV_SPEC §9.2.3).

    High-risk production writes (SQL, refunds, logistics state changes) must go
    through a fake backend in tests so nothing touches a real system.
    """

    def __init__(self) -> None:
        self.writes: list[dict] = []

    def write(self, payload: dict) -> dict:
        self.writes.append(payload)
        return {"ok": True, "fake": True}


@pytest.fixture
def repo_root() -> pathlib.Path:
    """Absolute path to the fiat-agent repo root."""
    return REPO_ROOT


@pytest.fixture
def mock_llm() -> MockLLM:
    """A deterministic, side-effect-free chat-model stand-in."""
    return MockLLM()


@pytest.fixture
def fake_backend() -> FakeBackend:
    """A fake production backend that records (but does not perform) writes."""
    return FakeBackend()


@pytest.fixture
def rag_server_config():
    """Runnable `McpServerConfig` for the real MODULAR-RAG-MCP-SERVER, or None.

    The shipped settings use ``command: python``, but the RAG server's deps live
    in its own ``.venv``; we prefer that interpreter so the server can actually
    start in this local dev environment. Returns ``None`` when the server
    directory or its venv interpreter is absent (tests should skip).
    """
    from fiat_agent.config import McpServerConfig, load_settings
    from pathlib import Path

    base = load_settings().mcp_servers.get("rag")
    if base is None or not base.cwd:
        return None
    cwd = Path(base.cwd)
    if not cwd.exists():
        return None
    venv_python = cwd / ".venv" / "bin" / "python"
    command = str(venv_python) if venv_python.exists() else (base.command or "python")
    return McpServerConfig(
        name=base.name,
        transport=base.transport,
        cwd=str(cwd),
        command=command,
        args=list(base.args),
    )
