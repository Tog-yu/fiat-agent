# 权限模型（fiat-agent）

fiat-agent 的授权是**声明式、确定性、无 LLM** 的：所有规则来自 `config/tool_policies.yaml`，
由纯函数 `can_execute` / `filter_tools` 计算（DEV_SPEC §2.2 / B3 / B4）。本文档对应阶段 B3/B4 与审批流 J。

## 1. 核心概念

### 1.1 风险等级（RiskLevel）

`fiat_agent/schemas/common.py::RiskLevel`：L1（最低）→ L5（最高）。
- L4 / L5 视为生产级影响，**无论工具自身 `approval_required` 标志如何，都强制要求审批**（见 `auth/policy.py::_HIGH_RISK`）。

### 1.2 角色与环境

- `ActorContext`（schemas/common.py）：`actor_id`、`roles: list[str]`、`environment ∈ {dev, staging, prod}`、`task_type`。
- **白名单模型**：工具策略用 `allowed_roles` + `allowed_environments` 明确列出"谁、在哪个环境能用"，
  未列出的组合一律拒绝（默认拒绝，而非默认放行）。

### 1.3 作用域与集合（Scope / Collection）

- `allowed_scopes`：该工具允许的作用域标签（如 `rag`、`cashback_readonly`）。
- `collection_scopes`：`role → [collection_id,...]`，细化到某角色可触及的集合（如 `oncall: [cashback_readonly]`、
  `ops: [cashback_all]`）。

### 1.4 显式拒绝动作（denied_actions）

用于"工具可用但其某动作永远禁止"的场景。例如 `cashback_submit` 虽声明但 `allowed_roles: []`，
且 `denied_actions: [submit_prod]`，MVP 中任何角色都不得自动生产提交。`can_execute` 在
`action in policy.denied_actions` 时直接拒绝。

## 2. 策略数据模型

`fiat_agent/auth/rbac.py`：

```python
@dataclass
class ToolPolicy:
    tool: str
    risk_level: RiskLevel
    allowed_roles: list[str]
    allowed_environments: list[str]
    approval_required: bool
    allowed_scopes: list[str]
    collection_scopes: dict[str, list[str]]   # role -> collection ids
    denied_actions: list[str]
```

`load_tool_policies(path=None)` 读取 `config/tool_policies.yaml`，返回 `{tool: ToolPolicy}`。

## 3. 决策函数

`fiat_agent/auth/policy.py`：

```python
def can_execute(actor, tool_name, environment=None, resource=None, action=None) -> PolicyDecision:
    # PolicyDecision(allowed, reason, approval_required, risk_level)
```

计算顺序（纯函数，无副作用）：

1. 无策略定义 → 拒绝（`no policy defined for tool '...'`）。
2. `allows_role_env(role, env)` 失败 → 区分"角色不允许"与"环境不允许"，给出可读 `reason`。
3. `action in denied_actions` → 拒绝（带具体动作名）。
4. 通过 → `allowed=True`，`approval_required = policy.approval_required or risk_level in {L4,L5}`。

`filter_tools(actor, tools, environment)`：返回该角色**可见/可执行**的工具（需审批的工具仍保留——
审批门控的是"执行"，不是"可见"）。

## 4. 当前工具策略表（`config/tool_policies.yaml`）

| 工具 | 风险 | 允许角色 | 允许环境 | 需审批 | 说明 |
|---|---|---|---|---|---|
| `rag_query` | L1 | oncall, ops, viewer | dev, staging, prod | 否 | 知识库检索 |
| `cashback_parse` | L1 | oncall, ops, viewer | 全部 | 否 | 返现表格解析（只读） |
| `alert_diagnosis` | L1 | oncall, ops, viewer | 全部 | 否 | 告警诊断（只读证据） |
| `logistics_validate` | L1 | oncall, ops, viewer | 全部 | 否 | 物流表格校验（只读） |
| `es_query` | L2 | oncall, ops | 全部 | 否 | ES 只读 |
| `db_query` | L2 | oncall, ops | 全部 | 否 | DB 只读 |
| `lark_notify` | L2 | oncall, ops | 全部 | 否 | Lark 通知（非破坏） |
| `test_env` | L3 | oncall, ops | dev | 否 | 测试环境自动化（仅 DEV） |
| `cashback_reconcile` | L4 | ops, oncall | dev, staging | 是 | 返现对账 dry-run（无生产写） |
| `cashback_submit` | L5 | （无） | prod | 是 | 生产提交（MVP 禁用） |

> 风险等级 L4/L5 或 `approval_required=true` 的工具，在**执行**前必须人工审批（见下）。

## 5. 审批流（阶段 G6 / J）

- 编排器 `approval_node` 检查候选工具：`can_execute` 返回 `approval_required` 或风险 L4/L5 的工具
  进入"待审批"；**被拒绝（allowed=False）的工具不会进入审批队列**（已修复的 bug：拒绝的工具不应发出待审批）。
- 图在 `approval` 节点 PENDING 即终止（不进入 `tool` 节点），返回 `pending_tools` 给调用方。
- `fiat_agent/approvals/service.py::ApprovalService`（进程内共享单例，Web Console 与 Lark 共用一个队列）
  记录 `params_summary` 作为**冻结快照**，拒绝前端回传参数。
- API（`apps/api/routes/approvals.py`）：
  - `GET /api/approvals?status=pending` — 列出审批
  - `POST /api/approvals/{id}/approve` — 批准（可选 reason）
  - `POST /api/approvals/{id}/reject` — 拒绝（带 reason）
- 批准后，调用方以 `approved=True` 重新提交同一工具调用，由 `ToolGateway` 放行执行。

## 6. 与工具网关的衔接

权限决策不发生在工具内部，而发生在 `fiat_agent/tool_gateway/gateway.py::ToolGateway.execute_tool`：

1. 先 `can_execute` 网关（任何副作用之前）；拒绝 → `ERROR` 结果。
2. 再审批网关：需审批且未批准 → `PENDING_APPROVAL`，不执行。
3. 执行 handler；成功/失败归一化为 `ToolResult`。
4. 无论结果，写 `tool_calls` 记录 + `audit_logs` 的 `tool_call` 事件。

详见 [tool-contracts.md](tool-contracts.md)。

## 7. 常见排查

- 调用被拒：用 `POST /api/auth/check`（`apps/api/routes/auth.py`），它会返回 `allowed`/`reason`/
  `approval_required`/`risk_level`，直接定位是角色、环境、还是 `denied_actions` 拦截。
- 卡在 `approval_pending`：确认工具风险等级或 `approval_required`，去审批队列处理后再提交。
