"""测试环境自动化 workflow (phase H4, DEV_SPEC §H4 / §6).

Implements the DEV-only test-data automation workflow:

1. **仅测试环境可执行** — if the actor is not in the ``DEV`` environment the
   workflow refuses deterministically (no model call, no tool call). This is
   backed by three layers: the workflow gate, the ``test_env`` policy in
   ``config/tool_policies.yaml`` (dev-only), and :class:`TestEnvTool.validate`.
2. **流程可编排** — the action sequence (``create_account`` -> ``recharge`` ->
   ``kyc``) is planned (model-derived or explicit) and executed **in order**
   through the audited :class:`ToolGateway`; each step is a ``test_env`` call
   that stamps the resource with a ``TEST_`` marker. A step failure stops the
   pipeline (no partial downstream mutations).

The workflow never touches production and every generated resource is test data
(``is_test=True``), matching the skill's "只读/测试数据" constraint.

Contract with the ``test_env`` handler: it receives
``{"environment": "dev", "action": <action>, "payload": {...}}`` and returns a
:class:`~fiat_agent.tool_gateway.test_env_tools.TestEnvResult` (or a dict shaped
like one) carrying ``resource_id`` / ``detail`` / ``is_test``.
"""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Optional

from fiat_agent.audit.service import AuditService
from fiat_agent.context.builder import ContextBuilder
from fiat_agent.models.base import ChatMessage, ChatRequest
from fiat_agent.models.gateway import ModelGateway
from fiat_agent.schemas.common import ActorContext, Environment, FiatModel, TaskType
from fiat_agent.skills.loader import DomainSkill, load_skill
from fiat_agent.tool_gateway.gateway import ToolGateway
from fiat_agent.tools.function_calling import ToolResultStatus
from fiat_agent.tools.registry import ToolRegistry

# Policy key / registered handler name for the test-env automation tool.
TEST_TOOL = "test_env"

# Actions this workflow knows how to orchestrate (matches the skill + tool).
KNOWN_ACTIONS = ("create_account", "recharge", "kyc")

# Default pipeline order when the planner returns nothing usable.
_DEFAULT_PIPELINE = list(KNOWN_ACTIONS)


class TestAutomationResult(FiatModel):
    """Structured outcome of the test-env automation workflow.

    ``is_test`` is always ``True`` (every resource is test data); ``environment``
    records where it actually ran (``dev`` on success, the rejected env on refusal).
    """

    __test__ = False  # not a pytest test class

    request: str = ""
    steps: list[dict[str, Any]] = []
    is_test: bool = True
    environment: str = ""
    error: Optional[str] = None


def _parse_plan(content: Optional[str]) -> Optional[list[str]]:
    """Extract an ``actions`` list from a model reply, tolerating code fences."""
    if not content:
        return None
    text = content.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    actions = data.get("actions") if isinstance(data, dict) else None
    if not isinstance(actions, list):
        return None
    return [a for a in actions if a in KNOWN_ACTIONS] or None


class TestAutomationWorkflow:
    """End-to-end test-environment automation workflow."""

    def __init__(
        self,
        registry: ToolRegistry,
        gateway: ToolGateway,
        model_gateway: ModelGateway,
        audit_service: AuditService,
        builder: Optional[ContextBuilder] = None,
        skill: Optional[DomainSkill] = None,
        *,
        test_tool: str = TEST_TOOL,
    ) -> None:
        self._registry = registry
        self._gateway = gateway
        self._model = model_gateway
        self._audit = audit_service
        self._builder = builder or ContextBuilder()
        self._skill = skill or load_skill(TaskType.TEST_ENV_AUTOMATION)
        self._test_tool = test_tool

    async def run(
        self,
        request: str,
        actor: ActorContext,
        *,
        actions: Optional[list[str]] = None,
        session_id: Optional[str] = None,
        event_emitter: Optional[Callable[[str, dict], Awaitable[None]]] = None,
    ) -> TestAutomationResult:
        """Run the test-env pipeline described by ``request`` for ``actor``.

        Args:
            request: the natural-language ask (e.g. "建一个测试账号并充值 KYC").
            actor: the acting principal (its ``environment`` gates execution).
            actions: explicit action sequence; when ``None`` the model plans it.
            session_id: optional session id for traceability / events.
            event_emitter: optional ``(type, payload)`` sink for the event bus (K).
        """
        env = actor.environment
        env_str = env.value if isinstance(env, Environment) else str(env)

        # 1) Environment gate: only DEV may run test automation.
        if env_str != "dev":
            return TestAutomationResult(
                request=request,
                steps=[],
                is_test=True,
                environment=env_str,
                error="test-env automation only runs in DEV environment",
            )

        # 2) Plan the action sequence (model, or explicit override).
        seq = actions if actions is not None else await self._plan_actions(request, actor)

        # 3) Execute each action in order; stop on the first failure.
        steps: list[dict[str, Any]] = []
        for action in seq:
            res = await self._gateway.execute_tool(
                actor,
                self._test_tool,
                {"environment": "dev", "action": action, "payload": {}},
            )
            if res.status != ToolResultStatus.SUCCESS:
                steps.append(
                    {
                        "action": action,
                        "resource_id": None,
                        "status": "failed",
                        "detail": res.error or "tool failed",
                    }
                )
                break
            raw = res.raw or {}
            rid = getattr(raw, "resource_id", None)
            if rid is None and isinstance(raw, dict):
                rid = raw.get("resource_id")
            detail = getattr(raw, "detail", None)
            if detail is None and isinstance(raw, dict):
                detail = raw.get("detail", {})
            steps.append(
                {
                    "action": action,
                    "resource_id": rid,
                    "status": "ok",
                    "detail": detail,
                }
            )

        if event_emitter is not None:
            await event_emitter(
                "test_automation",
                {
                    "request": request,
                    "session_id": session_id,
                    "environment": "dev",
                    "steps": len(steps),
                    "failed": any(s["status"] == "failed" for s in steps),
                },
            )

        return TestAutomationResult(
            request=request,
            steps=steps,
            is_test=True,
            environment="dev",
        )

    async def _plan_actions(self, request: str, actor: ActorContext) -> list[str]:
        """Ask the model which actions to run; fall back to the default pipeline."""
        built = self._builder.build(
            actor,
            self._registry,
            task_type=TaskType.TEST_ENV_AUTOMATION,
            skill=self._skill,
        )
        messages = [
            ChatMessage(role="system", content=built.system_prompt),
            ChatMessage(
                role="user",
                content=(
                    f"{request}\n\n请只输出要执行的动作序列，"
                    'JSON 格式：{"actions": ["create_account", "recharge", "kyc"]}。'
                ),
            ),
        ]
        response = await self._model.function_call(
            ChatRequest(messages=messages),
            task_type=TaskType.TEST_ENV_AUTOMATION.value,
        )
        planned = _parse_plan(response.content)
        return planned or list(_DEFAULT_PIPELINE)


async def run_test_automation(
    request: str,
    *,
    actor: ActorContext,
    registry: ToolRegistry,
    gateway: ToolGateway,
    model_gateway: ModelGateway,
    audit_service: AuditService,
    **kwargs: Any,
) -> TestAutomationResult:
    """Convenience entry point mirroring :meth:`TestAutomationWorkflow.run`."""
    return await TestAutomationWorkflow(
        registry=registry,
        gateway=gateway,
        model_gateway=model_gateway,
        audit_service=audit_service,
        **kwargs,
    ).run(request, actor)
