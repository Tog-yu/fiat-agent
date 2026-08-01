## 6. 模块说明

### 6.1 Entry Adapters

| 模块 | 职责 | 关键点 |
|---|---|---|
| `apps/api` | FastAPI 主服务 | REST API、SSE、鉴权依赖 |
| `apps/cli` | `fiat-agent` 命令 | chat、once、server 模式 |
| `apps/lark_bot` | Lark Bot 入口 | 告警通知、审批卡片、问答 |
| `apps/web_console` | React Web Console | 会话、任务、审批、审计 |
| `adapters/pi_extension` | Pi 可选入口 | 调用 fiat-agent API |
| `adapters/claude_code_mcp` | Claude Code 可选入口 | 将 fiat-agent 暴露为 MCP Server |

### 6.2 Agent Orchestrator

| 模块 | 职责 | 关键点 |
|---|---|---|
| `graph.py` | 构建 LangGraph | 节点、边、条件路由 |
| `state.py` | AgentState 定义 | task、messages、memory、tool results |
| `supervisor.py` | 任务分类和调度 | 单 agent / 多 agent 选择 |
| `nodes/*` | Graph 节点 | plan、tool、approval、final |

### 6.3 Model Gateway

| 模块 | 职责 | 关键点 |
|---|---|---|
| `base.py` | 统一模型接口 | chat、stream、function_call |
| `gateway.py` | 模型路由 | 按任务类型选择模型 |
| `providers/*` | Provider 实现 | OpenAI、Anthropic、私有模型 |
| `policies.py` | 模型策略 | token 预算、fallback、成本统计 |

### 6.4 Function Calling / Tool Calling

| 模块 | 职责 | 关键点 |
|---|---|---|
| `tools/registry.py` | 工具注册中心 | 业务工具 + MCP 工具 |
| `tools/schemas.py` | 工具 schema | Pydantic 输入输出 |
| `tools/function_calling.py` | Function Call 适配 | 模型工具描述、结果回灌 |
| `tool_gateway/gateway.py` | 工具执行入口 | 权限、dry-run、审批、审计 |

### 6.5 MCP RAG Client

| 模块 | 职责 | 关键点 |
|---|---|---|
| `rag_mcp_client.py` | MCP Client | stdio、initialize、tools/list、tools/call |
| `tool_registry.py` | MCP 工具同步 | 转换为 `mcp_rag.*` 工具 |
| `content_parser.py` | MCP 内容解析 | TextContent、ImageContent、citations |
| `rag/context_merge.py` | 合并上下文 | RAG 结果进入 Agent Context |
| `rag/citations.py` | 引用整理 | source、chunk、collection |

### 6.6 Session Memory Store

| 模块 | 职责 | 关键点 |
|---|---|---|
| `sessions/store.py` | 会话事件存储 | PostgreSQL append-only |
| `sessions/branches.py` | 回退和分支 | parent_event_id、active_event_id |
| `sessions/checkpoints.py` | LangGraph checkpoint | 长任务恢复 |
| `sessions/jsonl_exporter.py` | JSONL 导出 | 调试、回放、评测 |
| `context/compaction.py` | 压缩摘要 | compaction_summary event |

### 6.7 User / Auth / Approval / Audit

| 模块 | 职责 | 关键点 |
|---|---|---|
| `users/*` | 用户管理 | User、Role、UserRole |
| `auth/policy.py` | 权限判断 | can_execute |
| `auth/rbac.py` | RBAC | 角色、权限、工具策略 |
| `auth/scopes.py` | 数据范围 | collection、业务域、环境 |
| `approvals/*` | 审批流 | waiting、approved、rejected |
| `audit/*` | 审计 | 工具、审批、生产操作记录 |

### 6.8 Workflows

| 模块 | 职责 | 关键点 |
|---|---|---|
| `alert_diagnosis.py` | 告警诊断 | ES、DB、RAG、Lark |
| `test_automation.py` | 测试环境助手 | 账号、充值、KYC |
| `cashback_reconcile.py` | 返现对账 | 表格解析、金额校验、dry-run |
| `logistics_validation.py` | 物流校验 | 状态机、地址、单号校验 |
