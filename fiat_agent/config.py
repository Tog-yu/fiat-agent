"""Configuration loading for fiat-agent (phase A3).

Implements YAML config loading with `${ENV_VAR}` / `${ENV_VAR:-default}`
interpolation and deterministic fail-fast validation (DEV_SPEC §2.2: validation
and config checks are deterministic modules, never LLM-driven).

Public API:
    Settings            - typed config tree (pydantic)
    load_settings(path) - load + resolve env + validate; returns Settings
    validate_settings(s) - raise ConfigError if required keys are missing
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field

from fiat_agent.schemas.common import FiatModel

# `${VAR}` or `${VAR:-default}`
_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


class ConfigError(ValueError):
    """Raised when settings fail fail-fast validation.

    A subclass of ValueError so callers can catch it broadly, while still
    being distinguishable from generic value errors.
    """


def _resolve_env(value: Any) -> Any:
    """Recursively resolve `${VAR}` / `${VAR:-default}` in string scalars."""
    if isinstance(value, str):

        def _sub(match: re.Match[str]) -> str:
            name, default = match.group(1), match.group(2)
            return os.environ.get(name, default if default is not None else "")

        return _ENV_PATTERN.sub(_sub, value)
    if isinstance(value, dict):
        return {k: _resolve_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# Config sub-models (typed access + JSON-serializable for later audit/export)
# ---------------------------------------------------------------------------


class AppConfig(FiatModel):
    name: str = "fiat-agent"
    environment: str = "dev"


class DatabaseConfig(FiatModel):
    # Required for fail-fast (see validate_settings).
    url: str | None = None


class RedisConfig(FiatModel):
    url: str = "redis://localhost:6379/0"


class ModelProviderConfig(FiatModel):
    api_key_env: str = ""


class ModelsConfig(FiatModel):
    # Required for fail-fast.
    default: str | None = None
    providers: dict[str, ModelProviderConfig] = Field(default_factory=dict)


class ModelPolicyConfig(FiatModel):
    model: str = ""


class McpServerConfig(FiatModel):
    name: str = ""
    transport: str = "stdio"
    cwd: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)


class SessionConfig(FiatModel):
    max_context_tokens: int = 80000
    compact_threshold_ratio: float = 0.75
    jsonl_export_enabled: bool = True


class ToolsConfig(FiatModel):
    default_timeout_seconds: int = 30
    production_write_requires_approval: bool = True


class EventStreamConfig(FiatModel):
    transport: str = "sse"


class Settings(FiatModel):
    app: AppConfig = Field(default_factory=AppConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    model_policies: dict[str, ModelPolicyConfig] = Field(default_factory=dict)
    mcp_servers: dict[str, McpServerConfig] = Field(default_factory=dict)
    session: SessionConfig = Field(default_factory=SessionConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    event_stream: EventStreamConfig = Field(default_factory=EventStreamConfig)


DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "settings.yaml"
)


def load_settings(path: str | None = None) -> Settings:
    """Load YAML config, resolve env references, and validate.

    Args:
        path: Explicit path to a settings YAML. Defaults to
            `<repo>/config/settings.yaml`.

    Returns:
        A validated `Settings` instance.

    Raises:
        ConfigError: if the file is missing or required keys are absent.
    """
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        raise ConfigError(f"配置文件不存在: {cfg_path}")
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    raw = _resolve_env(raw)
    settings = Settings.model_validate(raw)
    validate_settings(settings)
    return settings


def validate_settings(settings: Settings) -> None:
    """Deterministic fail-fast check of required config keys.

    Raises:
        ConfigError: listing every missing required key (database.url,
        models.default, mcp_servers.rag) so the operator gets a readable,
        actionable error instead of a partial stack trace.
    """
    missing: list[str] = []
    if not settings.database.url:
        missing.append("database.url")
    if not settings.models.default:
        missing.append("models.default")
    rag = settings.mcp_servers.get("rag")
    if rag is None or not rag.name:
        missing.append("mcp_servers.rag")
    if missing:
        raise ConfigError(
            "配置缺失必要字段，无法启动 (fail-fast): " + ", ".join(missing)
        )
