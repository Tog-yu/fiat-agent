"""Structured logging for fiat-agent (phase A4, DEV_SPEC §2 / §9).

Provides `get_logger()` and a sensitive-field redaction helper so logs never
leak secrets (passwords, api keys, tokens, ...). Redaction is deterministic
and applied before anything is emitted.
"""

from __future__ import annotations

import logging
from typing import Any

# Keys (case-insensitive) whose values must never appear in logs.
SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "api_key",
        "apikey",
        "secret",
        "token",
        "authorization",
        "auth",
        "cookie",
        "credential",
        "private_key",
    }
)

REDACTED = "***"


def redact_sensitive(value: Any) -> Any:
    """Recursively replace sensitive field values with `***`."""
    if isinstance(value, dict):
        return {
            k: (REDACTED if str(k).lower() in SENSITIVE_KEYS else redact_sensitive(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive(v) for v in value]
    return value


def get_logger(name: str = "fiat_agent") -> logging.Logger:
    """Return a configured fiat-agent logger (idempotent handler setup)."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    **fields: Any,
) -> None:
    """Emit a structured event with sensitive fields redacted."""
    safe = redact_sensitive(fields)
    logger.log(level, "%s %s", event, safe)
