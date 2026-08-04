---
name: project-learner
description: "Interactive Chinese learning coach for the fiat-agent codebase. Inspect current docs, source, configuration, and tests; teach 45 project-specific knowledge points through interview-style questions, adaptive follow-ups, scoring, code-linked study guidance, and persistent progress. Use when the user asks to 学习项目、了解项目、检验掌握度、项目学习、知识检查、learn/study fiat-agent, or wants guided Q&A to master this repository."
---

# Project Learner — fiat-agent

通过真实源码驱动的中文问答，帮助用户掌握 `fiat-agent`。所有结论以当前仓库为准，不能只复述 `DEV_SPEC.md`。

## 总流程

```text
项目发现 → 读取进度 → 选择模式与知识点 → 深读源码 → 主问题
→ 最多 4 轮追问 → 评分 → 学习指南 → 保存进度 → 继续或结束
```

## Phase 1：静默建立项目模型

在提问用户前完成以下检查：

1. 读取 `README.md` 与 `DEV_SPEC.md` 的项目概述、设计原则、架构、数据流、测试和扩展点。
2. 读取 `docs/architecture.md`、`docs/permission-model.md`、`docs/session-memory-design.md`、`docs/tool-contracts.md`。
3. 读取 `config/settings.yaml`、`config/model_policies.yaml`、`config/tool_policies.yaml` 与 `pyproject.toml`。
4. 列出 `apps/`、`adapters/`、`fiat_agent/`、`tests/` 的实际结构。
5. 对所选知识点继续深读对应源码和测试，不凭文档猜实现。

始终区分三类事实：

- **已实现并接入**：源码存在且生产装配路径可达。
- **已实现但使用 fake/stub 或默认关闭**：例如部分外部工具 handler、Anthropic provider、本地模型、生产提交。
- **仅为扩展点**：例如多 Agent 并行、真实长期记忆、PostgreSQL 主线化、生产写入能力。

## 45 个知识点

| ID | 知识域 / 知识点 | 关键位置 |
|---|---|---|
| **D1** | **项目定位与总体架构** | |
| D1.1 | 法币业务目标、五类任务与系统边界 | `README.md`, `DEV_SPEC.md`, `fiat_agent/schemas/common.py` |
| D1.2 | Agent 与业务执行隔离、确定性规则优先 | `DEV_SPEC.md`, `docs/permission-model.md` |
| D1.3 | Adapters → Orchestrator → Model/Tool Gateway → Workflow → Session/Event 的分层 | `docs/architecture.md` |
| D1.4 | 一轮请求、MCP RAG 查询、审批等待的端到端数据流 | `DEV_SPEC.md`, `apps/api/agent_service.py` |
| **D2** | **LangGraph Agent 编排** | |
| D2.1 | `AgentState` / `GraphState` 字段与 append reducer | `fiat_agent/orchestrator/state.py`, `graph.py` |
| D2.2 | 关键词任务分类与未知任务处理 | `fiat_agent/orchestrator/nodes/classify.py` |
| D2.3 | Context Builder、Domain Skill 注入与权限过滤后的工具 schema | `nodes/build_context.py`, `context/builder.py` |
| D2.4 | Model → Plan → Approval → Tool → Model 的 ReAct 循环与条件路由 | `fiat_agent/orchestrator/graph.py` |
| D2.5 | Final Answer、递归上限、MemorySaver 与节点 Trace | `graph.py`, `nodes/final.py` |
| **D3** | **模型网关与 Function Calling** | |
| D3.1 | Provider-neutral 消息、请求、响应与 token usage 契约 | `fiat_agent/models/base.py` |
| D3.2 | task tier、provider 路由、禁用 provider 与 fallback 链 | `models/policies.py`, `config/model_policies.yaml` |
| D3.3 | OpenAI-compatible provider 的消息转换、工具调用与流式归一化 | `models/providers/openai.py` |
| D3.4 | OpenAI/Anthropic/MCP/Pydantic 工具 schema 转换和结果回灌 | `tools/function_calling.py` |
| **D4** | **工具注册、执行与安全契约** | |
| D4.1 | `ToolDefinition`、唯一命名与 MCP 工具同步 | `tools/schemas.py`, `tools/registry.py` |
| D4.2 | `ToolGateway.execute_tool` 的鉴权、审批、执行、归一化顺序 | `tool_gateway/gateway.py` |
| D4.3 | ES 固定查询模板、DB 参数绑定与脱敏 | `tool_gateway/es_tools.py`, `db_tools.py` |
| D4.4 | ToolResult 的安全摘要、异常隔离与模型回灌 | `tool_gateway/gateway.py`, `tools/function_calling.py` |
| D4.5 | 当前真实 handler 与 unavailable stub 的边界 | `apps/api/agent_service.py`, `docs/tool-contracts.md` |
| **D5** | **会话、分支、Checkpoint 与记忆** | |
| D5.1 | 五张会话表及 append-only 事件树 | `sessions/store.py` |
| D5.2 | `seq`、`parent_event_id`、`active_event_id` 与路径遍历 | `sessions/store.py` |
| D5.3 | 回退和命名分支为何不删除历史或撤销生产副作用 | `sessions/branches.py` |
| D5.4 | Graph checkpoint、确定性 compaction 与原事件保留 | `sessions/checkpoints.py`, `context/compaction.py` |
| D5.5 | 短期记忆、长期记忆扩展点与 JSONL 导出 | `context/memory.py`, `sessions/jsonl_exporter.py` |
| **D6** | **MCP RAG 集成** | |
| D6.1 | stdio 子进程生命周期与 initialize / tools/call | `mcp_clients/rag_mcp_client.py` |
| D6.2 | 三个 RAG MCP 工具的参数契约与错误传播 | `rag_mcp_client.py`, `apps/api/rag_service.py` |
| D6.3 | Text/Image/Metadata 分离、Citation 与上下文合并 | `content_parser.py`, `rag/context_merge.py`, `rag/citations.py` |
| D6.4 | RAG disabled/unavailable 降级与无依据拒答 | `mcp_clients/tool_registry.py`, `workflows/rag_qa.py` |
| **D7** | **Domain Skill 与业务 Workflow** | |
| D7.1 | `SKILL.md` frontmatter 解析、发现、缓存与任务技能注入 | `fiat_agent/skills/loader.py`, `fiat_agent/skills/*/SKILL.md` |
| D7.2 | RAG 问答与告警诊断的证据链 | `workflows/rag_qa.py`, `alert_diagnosis.py` |
| D7.3 | 测试环境自动化的 DEV 限制与 `TEST_` 标记 | `workflows/test_automation.py`, `tool_gateway/test_env_tools.py` |
| D7.4 | 返现解析、Decimal 金额、去重与 dry-run 对账 | `tool_gateway/cashback_tools.py`, `workflows/cashback_reconcile.py` |
| D7.5 | 物流字段校验、Luhn、状态机与生产提交 guard | `tool_gateway/logistics_tools.py`, `workflows/production_submit.py` |
| **D8** | **权限、审批与审计** | |
| D8.1 | `ToolPolicy`、角色/环境白名单、scope 与 denied action | `auth/rbac.py`, `config/tool_policies.yaml` |
| D8.2 | `can_execute` 决策顺序、L4/L5 强制审批与工具可见性 | `auth/policy.py`, `docs/permission-model.md` |
| D8.3 | 审批快照、不可重复决策与 L5 双人审批 | `approvals/service.py`, `approvals/policies.py` |
| D8.4 | tool/policy/approval/model usage/agent trace 审计与敏感信息脱敏 | `audit/service.py`, `logging.py` |
| **D9** | **事件流与多入口适配** | |
| D9.1 | Event Bus 的 topic/kind 订阅、去重与订阅者故障隔离 | `events/types.py`, `events/bus.py` |
| D9.2 | 环形缓冲、单调 seq、replay + live 无缺口与 SSE 续传 | `events/stream.py`, `apps/api/routes/events.py` |
| D9.3 | FastAPI / CLI / Lark Bot 的依赖注入和共享服务 | `apps/api/`, `apps/cli/`, `apps/lark_bot/` |
| D9.4 | fiat MCP Adapter 与 Web Console 的权限一致性和展示职责 | `adapters/claude_code_mcp/`, `apps/web_console/src/` |
| **D10** | **测试、配置与工程事实** | |
| D10.1 | YAML `${VAR:-default}` 解析、fail-fast 校验与密钥边界 | `fiat_agent/config.py`, `config/` |
| D10.2 | SQLite 默认、SQLAlchemy async、Alembic 与 PostgreSQL 扩展点 | `fiat_agent/db.py`, `migrations/` |
| D10.3 | Unit / Integration / E2E 的测试边界与 hermetic fake 策略 | `tests/`, `pyproject.toml` |
| D10.4 | Agent eval、MVP flows、权限拒绝与审批等待回归 | `tests/e2e/`, `tests/fixtures/agent_eval_cases.json` |
| D10.5 | 文档/源码/依赖版本差异、当前缺口与后续扩展判定 | `README.md`, `DEV_SPEC.md`, `pyproject.toml`, `package.json` |

## Phase 2：读取学习进度

读取 [references/LEARNING_PROGRESS.md](references/LEARNING_PROGRESS.md)：

1. 解析 Domain Summary、Sub-topic Progress 与 Detailed History。
2. 统计掌握数 `/45`，找出未学、薄弱和最近下降的知识点。
3. 若文件缺失，按同路径创建模板；不要把进度写到其他目录。

状态规则：`✅ ≥7`、`🔶 4-6.5`、`🔴 ≤3.5`、`⬜ 未学习`。

## Phase 3：选择学习目标

优先提供以下模式；界面支持结构化提问时使用结构化选择，否则用简短中文逐项询问：

- `学习新知识点`：优先未学知识点。
- `复习薄弱点`：优先最低分或久未复习知识点。
- `查看进度`：展示进度后结束。
- `Agent 推荐`：按“未学且基础性强 → 薄弱 → 最近下降”自动选择。

选择 Domain 后再选择一个具体知识点，不要只停留在大章节。

## Phase 4：生成真实源码问题

1. 深读该知识点列出的源码、配置和至少一个相关测试。
2. 生成一道必须结合本项目回答的问题；禁止只问通用定义。
3. 选择未在 Detailed History 使用过的角度：What / How / Why / Compare / Debug / Extend。
4. 内部准备最多 4 个递进追问，按用户实际回答动态调整。

首题格式：

```markdown
## 🎯 面试问题

**知识域**：[Domain] > **知识点**：[ID + 名称]

**问题**：[引用真实类、函数、配置或数据流的问题]

请回答：
```

## Phase 5：追问与评价

每次只问一个问题。每轮先指出答对的具体点，再指出一个缺口，然后追问。最多 4 轮；用户说“跳过/结束/pass”时立即结束。

结束后按四维评分，平均后四舍五入到 0.5：

| 维度 | 重点 |
|---|---|
| 准确性 | 是否符合当前源码，而非只符合规格文档 |
| 深度 | 是否讲清实现、边界条件与失败路径 |
| 代码关联 | 是否能定位类、函数、配置或测试 |
| 设计思维 | 是否能解释安全边界、取舍和扩展方式 |

输出亮点、缺口、四维分数、综合分数与总进度。

## Phase 6：给出学习指南

提供 3-5 个最关键的真实文件，说明阅读重点；至少给出一个可执行命令，例如：

```bash
pytest -q tests/unit/test_auth_policy.py
pytest -q tests/integration/test_agent_graph.py
python -m apps.cli.main once --message "查一下知识库"
```

命令必须与所学知识点相关。引用源码时使用实际路径；能够定位时附行号。

## Phase 7：保存进度

更新 [references/LEARNING_PROGRESS.md](references/LEARNING_PROGRESS.md)：

1. 在 Detailed History 追加一行，保留问题摘要、评分、追问轮数和薄弱点。
2. 更新知识点的已学次数、最高分、最近分和状态。
3. 重新计算 Domain 的已掌握、已学习、平均分和状态。
4. 更新总进度、日期和自增序号。

不要覆盖历史记录，不要把尚未回答的问题记为已学习。

## Phase 8：继续或结束

询问用户继续下一个知识点、复习薄弱点、查看进度或结束。结束时汇总本次完成数、平均分、最强点、薄弱点和下次推荐。
