"""Model routing policy (phase D3, DEV_SPEC D3).

Loads :file:`config/model_policies.yaml` and resolves a ``(task_type |
complexity)`` pair into a concrete
:class:`~fiat_agent.models.base.BaseChatModel`.

Provider construction is isolated in :func:`build_provider` so tests can inject
stubs and so adding a new backend (Anthropic / Gemini / private) is a one-line
branch here, not a change to every caller.

Secrets live only in environment variables (referenced by ``api_key_env``) and
are never copied into the policy or into model responses.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

from fiat_agent.models.base import BaseChatModel


class ProviderSpec(BaseModel):
    """One configured model backend."""

    type: str
    base_url: Optional[str] = None
    model: str
    api_key_env: str = ""
    enabled: bool = True


class ModelPolicies(BaseModel):
    """Full routing policy loaded from ``model_policies.yaml``."""

    providers: dict[str, ProviderSpec] = Field(default_factory=dict)
    tiers: dict[str, str] = Field(default_factory=dict)
    task_tiers: dict[str, str] = Field(default_factory=dict)
    default_tier: str = "medium"
    fallback: dict[str, list[str]] = Field(default_factory=dict)


DEFAULT_POLICY_PATH = (
    Path(__file__).resolve().parent.parent.parent / "config" / "model_policies.yaml"
)


def load_model_policies(path: str | None = None) -> ModelPolicies:
    """Load + validate the routing policy from YAML.

    Args:
        path: Explicit path; defaults to ``<repo>/config/model_policies.yaml``.
    """
    p = Path(path) if path else DEFAULT_POLICY_PATH
    if not p.exists():
        raise FileNotFoundError(f"model policy file not found: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    raw = _resolve_env(raw)
    return ModelPolicies.model_validate(raw)


def _resolve_env(value):
    """Expand ``${VAR}`` references (delegate to the shared config helper)."""
    from fiat_agent.config import _resolve_env as _re

    return _re(value)


def build_provider(spec: ProviderSpec) -> BaseChatModel:
    """Construct a :class:`BaseChatModel` from a :class:`ProviderSpec`."""
    if spec.type == "openai":
        from fiat_agent.models.providers.openai import OpenAIChatModel

        return OpenAIChatModel(
            model=spec.model,
            base_url=spec.base_url,
            api_key_env=spec.api_key_env or None,
        )
    if spec.type == "anthropic":
        raise NotImplementedError(
            f"anthropic provider for '{spec.model}' is not implemented yet; "
            f"the local tier is disabled by default in MVP (DEV_SPEC §3.1)."
        )
    raise ValueError(f"unknown provider type: {spec.type}")


def resolve_tier(
    policies: ModelPolicies,
    task_type: Optional[str],
    complexity: Optional[str] = None,
) -> str:
    """Map a request to a complexity tier.

    Explicit ``complexity`` wins; else look up ``task_type``; else the default.
    """
    if complexity:
        return complexity
    if task_type and task_type in policies.task_tiers:
        return policies.task_tiers[task_type]
    return policies.default_tier


def select_provider(
    policies: ModelPolicies,
    task_type: Optional[str] = None,
    complexity: Optional[str] = None,
) -> BaseChatModel:
    """Resolve ``(task_type | complexity)`` to an enabled provider instance.

    Follows the ``fallback`` chain when a tier's provider is missing/disabled
    (e.g. the local tier is off in MVP, so simple tasks fall back to deepseek).
    """
    tier = resolve_tier(policies, task_type, complexity)
    chain = [tier] + list(policies.fallback.get(tier, []))
    tried: list[str] = []
    for t in chain:
        provider_name = policies.tiers.get(t)
        if not provider_name:
            continue
        spec = policies.providers.get(provider_name)
        if spec is None or not spec.enabled:
            tried.append(provider_name)
            continue
        return build_provider(spec)
    raise RuntimeError(
        f"no enabled provider for tier '{tier}' (tried: {tried})"
    )
