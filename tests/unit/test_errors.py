"""Tests for phase A4 errors and logging (DEV_SPEC §11-A4).

Covers:
  - every error carries stable code / message / metadata
  - error subclasses keep the right code
  - to_dict() shape is serializable
  - logs never emit sensitive field values (redaction)
"""

import logging

import pytest

from fiat_agent.errors import (
    ApprovalRequiredError,
    FiatAgentError,
    PermissionDeniedError,
    ToolExecutionError,
)
from fiat_agent.logging import get_logger, log_event, redact_sensitive


@pytest.mark.unit
def test_base_error_has_code_message_metadata():
    err = FiatAgentError("boom", metadata={"task_id": "t1"})
    assert err.code == "fiat_agent_error"
    assert err.message == "boom"
    assert err.metadata == {"task_id": "t1"}
    assert isinstance(err, Exception)


@pytest.mark.unit
def test_error_subclasses_keep_codes():
    assert PermissionDeniedError("x").code == "permission_denied"
    assert ToolExecutionError("x").code == "tool_execution_error"
    assert ApprovalRequiredError("x").code == "approval_required"

    assert issubclass(PermissionDeniedError, FiatAgentError)
    assert issubclass(ToolExecutionError, FiatAgentError)
    assert issubclass(ApprovalRequiredError, FiatAgentError)


@pytest.mark.unit
def test_to_dict_shape():
    err = PermissionDeniedError("no", metadata={"tool": "db_write"})
    d = err.to_dict()
    assert d == {
        "code": "permission_denied",
        "message": "no",
        "metadata": {"tool": "db_write"},
    }
    # JSON-serializable
    import json

    assert json.loads(json.dumps(d)) == d


@pytest.mark.unit
def test_get_logger_returns_logger():
    logger = get_logger("fiat_agent.test")
    assert isinstance(logger, logging.Logger)
    # idempotent: same name returns same object
    assert get_logger("fiat_agent.test") is logger


@pytest.mark.unit
def test_redact_sensitive_recursive():
    data = {
        "user": "alice",
        "password": "hunter2",
        "nested": {"api_key": "sk-123", "ok": 1},
        "items": [{"token": "t0"}, {"safe": "v"}],
    }
    out = redact_sensitive(data)
    assert out["password"] == "***"
    assert out["nested"]["api_key"] == "***"
    assert out["nested"]["ok"] == 1
    assert out["items"][0]["token"] == "***"
    assert out["items"][1]["safe"] == "v"
    assert out["user"] == "alice"


@pytest.mark.unit
def test_log_event_redacts_sensitive(caplog):
    logger = get_logger("fiat_agent.redact_test")
    with caplog.at_level(logging.INFO, logger=logger.name):
        log_event(logger, logging.INFO, "tool_call", user="bob", password="secret", api_key="sk-9")

    assert "secret" not in caplog.text
    assert "sk-9" not in caplog.text
    assert "***" in caplog.text
    assert "bob" in caplog.text
