"""Tests for phase A3 Settings config loading (DEV_SPEC §8, §11-A3).

Covers:
  - loading the default repo config end-to-end
  - `${ENV_VAR}` / `${ENV_VAR:-default}` resolution
  - fail-fast `ConfigError` when database.url / models.default /
    mcp_servers.rag are missing
  - a valid `Settings` passes `validate_settings`
"""

import os
import textwrap

import pytest

from fiat_agent.config import (
    ConfigError,
    Settings,
    load_settings,
    validate_settings,
)


@pytest.mark.unit
def test_load_default_settings():
    settings = load_settings()
    assert isinstance(settings, Settings)
    assert settings.database.url.startswith("postgresql+asyncpg://")
    assert settings.models.default == "gpt-4.1-mini"
    assert settings.mcp_servers["rag"].name == "modular-rag-mcp-server"


@pytest.mark.unit
def test_env_var_resolution_with_default():
    os.environ.pop("FiatAgent_ENV", None)
    assert load_settings().app.environment == "dev"

    os.environ["FiatAgent_ENV"] = "prod"
    try:
        assert load_settings().app.environment == "prod"
    finally:
        os.environ.pop("FiatAgent_ENV", None)


@pytest.mark.unit
def test_env_var_reference_resolves(tmp_path):
    cfg = tmp_path / "settings.yaml"
    cfg.write_text(
        textwrap.dedent(
            """
            database:
              url: ${DB_URL}
            models:
              default: gpt-4.1-mini
            mcp_servers:
              rag:
                name: modular-rag-mcp-server
            """
        ),
        encoding="utf-8",
    )
    os.environ["DB_URL"] = "postgresql+asyncpg://x/y"
    try:
        assert load_settings(str(cfg)).database.url == "postgresql+asyncpg://x/y"
    finally:
        os.environ.pop("DB_URL", None)


@pytest.mark.unit
def test_missing_database_url_raises(tmp_path):
    cfg = tmp_path / "settings.yaml"
    cfg.write_text(
        textwrap.dedent(
            """
            models:
              default: gpt-4.1-mini
            mcp_servers:
              rag:
                name: modular-rag-mcp-server
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError) as exc:
        load_settings(str(cfg))
    assert "database.url" in str(exc.value)


@pytest.mark.unit
def test_missing_models_default_raises(tmp_path):
    cfg = tmp_path / "settings.yaml"
    cfg.write_text(
        textwrap.dedent(
            """
            database:
              url: postgresql+asyncpg://x/y
            mcp_servers:
              rag:
                name: modular-rag-mcp-server
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError) as exc:
        load_settings(str(cfg))
    assert "models.default" in str(exc.value)


@pytest.mark.unit
def test_missing_mcp_rag_raises(tmp_path):
    cfg = tmp_path / "settings.yaml"
    cfg.write_text(
        textwrap.dedent(
            """
            database:
              url: postgresql+asyncpg://x/y
            models:
              default: gpt-4.1-mini
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError) as exc:
        load_settings(str(cfg))
    assert "mcp_servers.rag" in str(exc.value)


@pytest.mark.unit
def test_validate_settings_passes():
    settings = Settings(
        database={"url": "x"},
        models={"default": "y"},
        mcp_servers={"rag": {"name": "z"}},
    )
    assert validate_settings(settings) is None


@pytest.mark.unit
def test_missing_file_raises():
    with pytest.raises(ConfigError):
        load_settings("/nonexistent/path/settings.yaml")
