"""Authorization scopes (phase B3, DEV_SPEC B3).

Data and environment scopes used by tool policies. Enum values are stable
strings so they serialize cleanly into audit logs and config.
"""

from __future__ import annotations

from enum import Enum


class EnvironmentScope(str, Enum):
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


class DataScope(str, Enum):
    ES_READ = "es_read"
    DB_READ = "db_read"
    RAG = "rag"
    CASHBACK_DRYRUN = "cashback_dryrun"
    CASHBACK_PROD = "cashback_prod"
    LARK = "lark"
