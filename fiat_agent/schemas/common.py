"""Shared Pydantic base and common types for fiat-agent schemas.

This module is the common foundation for all data contracts in the project.
Phase A5 extends it with domain enums (`Environment`, `RiskLevel`,
`TaskType`, ...) and agent/context schemas.

`FiatModel` is the shared base: it ignores unknown keys so partial configs and
forward-compatible payloads don't break validation, and allows population by
field name/alias.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class FiatModel(BaseModel):
    """Base model for all fiat-agent schemas (consistent config)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class Environment(str, Enum):
    """Deployment environment. Stable string values for serialization/audit."""

    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


class RiskLevel(str, Enum):
    """Risk tiers L1 (lowest) .. L5 (highest). Drives approval requirements."""

    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"
    L5 = "L5"


class TaskType(str, Enum):
    """Supported business task categories (DEV_SPEC §6 / §11-A5)."""

    RAG_QA = "rag_qa"
    ALERT_DIAGNOSIS = "alert_diagnosis"
    TEST_ENV_AUTOMATION = "test_env_automation"
    CASHBACK_RECONCILE = "cashback_reconcile"
    LOGISTICS_VALIDATION = "logistics_validation"


class ActorContext(FiatModel):
    """Who is acting, in which environment, on which task type."""

    actor_id: str
    roles: list[str] = Field(default_factory=list)
    environment: Environment = Environment.DEV
    task_type: TaskType | None = None
