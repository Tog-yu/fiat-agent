"""Task classification node (phase G2, DEV_SPEC §G2).

Maps a user request to one of the five supported :class:`TaskType` values using
**deterministic** keyword rules (no LLM — consistent with DEV_SPEC §2.2
"确定性规则优先"). The rules are ordered by specificity; the first match wins.
``classify_node`` is the LangGraph entry node: it reads the latest user message
and writes ``task_type`` onto the state.
"""

from __future__ import annotations

from fiat_agent.orchestrator.state import AgentState
from fiat_agent.schemas.common import TaskType

# (task_type, keywords) — order matters: more specific intents first.
_KEYWORD_MAP: list[tuple[TaskType, tuple[str, ...]]] = [
    (
        TaskType.CASHBACK_RECONCILE,
        ("返现", "对账", "cashback", "reconcile", "返现对账", " reconciliation"),
    ),
    (
        TaskType.LOGISTICS_VALIDATION,
        ("物流", "运单", "logistics", "卡片物流", "物流状态", "物流导入"),
    ),
    (
        TaskType.TEST_ENV_AUTOMATION,
        ("测试账号", "充值", "test account", "kyc", "测试环境", "测试数据", "开测试号"),
    ),
    (
        TaskType.ALERT_DIAGNOSIS,
        ("告警", "alert", "日志", "异常", "报错", "诊断", "排查", "监控", "告警日志"),
    ),
    (
        TaskType.RAG_QA,
        ("知识库", "文档", "是什么", "怎么", "规定", "policy", "faq", "手册", "查一下", "知识"),
    ),
]


def classify_task(text: str | None) -> TaskType | None:
    """Return the :class:`TaskType` implied by ``text``, or ``None`` if unknown."""
    if not text:
        return None
    lowered = text.lower()
    for task_type, keywords in _KEYWORD_MAP:
        if any(kw.lower() in lowered for kw in keywords):
            return task_type
    return None


def _latest_user_text(state: AgentState) -> str | None:
    for msg in reversed(state.messages):
        if msg.role == "user" and msg.content:
            return msg.content
    return None


def classify_node(state: AgentState) -> dict:
    """LangGraph node: classify the latest user turn and update the state.

    Returns a partial-state dict (``{"task_type": ...}``) ready to be merged by
    LangGraph. Unrecognized input yields ``None`` rather than guessing.
    """
    return {"task_type": classify_task(_latest_user_text(state))}
