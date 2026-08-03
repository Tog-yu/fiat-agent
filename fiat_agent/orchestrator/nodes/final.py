"""Final-answer node (phase G7, DEV_SPEC §G7).

Renders a final report in a fixed format per task type. RAG answers keep their
attached citations; reconciliation / logistics runs are rendered as **dry-run**
previews (never claiming a write happened). Keeping the shape fixed makes the
output auditable and model-independent for the structural parts.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from fiat_agent.orchestrator.state import AgentState
from fiat_agent.rag.context_merge import MergedRagContext
from fiat_agent.schemas.agent import ToolStatus
from fiat_agent.schemas.common import TaskType


_TASK_LABEL = {
    TaskType.RAG_QA: "知识库问答",
    TaskType.ALERT_DIAGNOSIS: "告警诊断",
    TaskType.TEST_ENV_AUTOMATION: "测试环境自动化",
    TaskType.CASHBACK_RECONCILE: "返现对账",
    TaskType.LOGISTICS_VALIDATION: "物流校验",
}


def _short(data: Any, limit: int = 300) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        text = data
    else:
        try:
            text = json.dumps(data, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(data)
    return text[:limit]


def _render_tool_results(state: AgentState) -> str:
    lines: list[str] = []
    for r in state.tool_results:
        if r.status == ToolStatus.SUCCESS:
            lines.append(f"- {r.tool_name}: {_short(r.data)}")
        else:
            lines.append(f"- {r.tool_name}: 失败 ({r.error or 'unknown'})")
    return "\n".join(lines) if lines else "(无工具结果)"


def final_node(
    state: AgentState, rag_context: Optional[MergedRagContext] = None
) -> dict:
    """Render the final answer and return a state delta ``{"final_answer": ...}``."""
    task = state.task_type
    label = _TASK_LABEL.get(task, "任务")

    if task == TaskType.RAG_QA and rag_context is not None:
        # RAG answer with citations preserved verbatim.
        body = rag_context.context
        answer = f"【{label}】\n{body}"

    elif task in (TaskType.CASHBACK_RECONCILE, TaskType.LOGISTICS_VALIDATION):
        # Dry-run preview: never claim a write occurred.
        answer = (
            f"【Dry-run 报告 · {label}】\n"
            f"{_render_tool_results(state)}\n"
            "- 状态: 仅预览，未执行任何写操作"
        )

    elif task == TaskType.ALERT_DIAGNOSIS:
        answer = f"【{label}】\n{_render_tool_results(state)}"

    else:
        answer = _render_tool_results(state)

    return {"final_answer": answer}
