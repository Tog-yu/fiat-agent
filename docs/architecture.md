# 架构设计（fiat-agent）

本文描述 fiat-agent 的整体架构、分层、Agent 编排循环，以及横切的关注点（事件流、追踪、审计、RAG）。

## 1. 分层总览

```text
┌─────────────────────────────────────────────────────────────────┐
│  Adapters (apps/)                                                │
│   cli/         → once | chat | server                            │
│   api/         → FastAPI 路由（agent/rag/approvals/audit/...）    │
│   web_console/ → Next.js 前端                                     │
└───────────────┬─────────────────────────────────────────────────┘
                │  AgentService / RagService / 审批 / 审计 依赖
┌───────────────▼─────────────────────────────────────────────────┐
│  Core (fiat_agent/)                                              │
│                                                                  │
│   orchestrator/   LangGraph ReAct 循环                            │
│      ├─ nodes: classify / build_context / plan / approval / tool / final │
│      └─ graph.AgentGraph.arun()                                  │
│                                                                  │
│   models/        ModelGateway + Provider（OpenAI 兼容 / Anthropic）│
│   tools/         ToolDefinition + ToolRegistry                   │
│   tool_gateway/   ToolGateway（鉴权闸门 + 审计 + 归一化）            │
│   mcp_clients/    RagMcpClient（stdio）+ 工具同步                  │
│   rag/           引用解析、上下文合并                              │
│   skills/        5 个 Domain Skill 包（SKILL.md）                 │
│   sessions/      只追加会话事件存储                                │
│   users/ auth/ approvals/ audit/ events/                         │
└───────────────┬─────────────────────────────────────────────────┘
                │  依赖
┌───────────────▼─────────────────────────────────────────────────┐
│  Foundation                                                     │
│   config/ (settings / model_policies / tool_policies)           │
│   db.py   SQLAlchemy 2.0 async 引擎工厂（SQLite / PostgreSQL）    │
│   schemas/  FiatModel 共享基（extra=ignore）                      │
└─────────────────────────────────────────────────────────────────┘
```

设计要点：

- **入口与核心解耦**：CLI 与 API 都通过 `apps/api/agent_service.py` 的 `AgentService` 触达运行时，
  因此 `python -m apps.cli.main --help` 不需要 FastAPI；测试可覆盖 `get_agent_service` 依赖注入封闭实例。
- **确定性边界在内层**：权限、审批、金额、状态机、校验、审计全部在 `auth/`、`tool_gateway/`、`approvals/`，
  不依赖 LLM（DEV_SPEC §2.2）。
- **存储可替换**：引擎工厂按 `database.url` 的 scheme 自动选 SQLite/PostgreSQL；会话存储与审计存储均异步、可测试。

## 2. Agent 编排循环（LangGraph）

`fiat_agent/orchestrator/graph.py` 用 `langgraph.StateGraph` 串起 G1–G7 节点，构成一个 ReAct 循环：

```text
START → classify → build_context → model
model ──(有 tool_calls)──▶ plan → approval ──(ok)──▶ tool → model
model ──(无 tool_calls)──▶ final → END
approval ──(PENDING)──▶ END        # 终止，等待人工审批，不执行
```

| 节点 | 阶段 | 职责 |
|---|---|---|
| `classify_node` (G2) | 分类 | 从最近一条用户消息推断 `task_type` |
| `build_context_node` (G3) | 上下文 | 组装**权限过滤后**的 system prompt 与工具 schema |
| `model` (D) | 推理 | 调用 `ModelGateway.function_call`，追加 assistant 轮 |
| `plan_node` (G4) | 规划 | 从模型 tool_calls 反推结构化 plan，确定性校验（不走 LLM 门控） |
| `approval_node` (G6) | 审批 | 检查候选工具风险，拦截高危调用等待人工审批 |
| `tool_node` (G5) | 执行 | 经 `ToolGateway`（鉴权+审计）派发，结果回灌模型 |
| `final_node` (G7) | 收尾 | 渲染固定格式最终回答 |

状态：`GraphState` 继承 `AgentState`，`messages` / `tool_results` 用 append reducer 累积历史；
`plan` / `plan_status` / `pending_approvals` / `final_answer` 为节点写回通道。

**重要实现约束**（曾踩坑）：

1. 用 pydantic state schema 时，节点收到的 state 是模型实例（属性访问）。
2. 有循环的图必须 `compile(checkpointer=MemorySaver())`，`ainvoke` 需带 `thread_id`。
3. 切勿返回 state schema 之外的 key（否则 Bad state update）。

**可观测回调**：`AgentGraph` 接受 `session_writer`（写会话事件）、`event_emitter`（发事件总线）、
`trace_sink`（写 Agent Trace）三类回调，使图本身不耦合具体存储（对应阶段 C / K）。

## 3. 模型网关

`fiat_agent/models/gateway.py::ModelGateway` 是薄编排层：

- 根据 `task_type` / `complexity` 由 `config/model_policies.yaml` 的 `select_provider` 选 Provider。
- 路由层级：`complex → gpt`、`medium → deepseek`、`simple → local`（local 默认 `enabled: false`）。
- 各层有 `fallback` 降级链（如 `simple` 失败降级 `medium` → `complex`）。
- 每次调用通过 `audit_sink` 上报 `TokenUsage` 到 `AuditService`（不持有任何 DB/session 知识）。

所有密钥通过 `api_key_env` 环境变量名引用，绝不内联。

## 4. RAG / MCP 接入

`fiat_agent/mcp_clients/rag_mcp_client.py::RagMcpClient` 管理单个 MCP stdio 连接的生命周期：

- `start()` 以 `StdioServerParameters`（command/args/cwd，继承父进程 env）拉起 Server 子进程；
- `initialize()` 完成 JSON-RPC 握手；上下文管理器保证 `close()` 清理子进程；
- 暴露 `query_knowledge_hub` / `list_collections` / `get_document_summary` 三个封装；
- `call_tool` 在 Server 返回 `isError` 时抛 `ToolExecutionError`，防止错误检索静默进入受信上下文。

**传输契约**：MCP stdio 只从 stdout 读 JSON-RPC，stderr 走独立日志流，Server 日志不会污染协议流。

在 Agent 内，策略 key 为 **`rag_query`**（`apps/api/agent_service.py::_rag_query_handler`），
启动 `RagMcpClient`、调用 `query_knowledge_hub`、用 `parse_mcp_contents` 解析，归一化为
`{"status","answer","citations"}`。解析后的内容经 `rag/` 模块做引用解析与上下文合并后才进入 prompt。

## 5. 横切关注点

### 5.1 事件总线与 SSE 流（阶段 K）

- `fiat_agent/events/bus.py` — 进程内异步 pub/sub：`subscribe`（全局）/ `subscribe_topic`
  （按 topic 或 kind 匹配，去重）。`publish` 对每个订阅者故障隔离（单订阅者异常不影响其他）。
- `fiat_agent/events/stream.py` — `EventStreamManager` 维护有界环形缓冲（默认 2000），给每个事件分配
  单调 `seq`，按 session 分发给订阅队列；`stream()` 先 `replay` 再 `live`，因订阅注册早于快照故**无缺口**。
- `apps/api/routes/events.py` — `GET /api/events/{session_id}` 返回 SSE，每帧带 `id: <seq>`；
  通过 `Last-Event-ID`（或 `?cursor=`）实现**断线续传**。

### 5.2 Agent Trace（阶段 K3）

`AuditService.record_trace(session_id, actor_id, round, step, node, status, detail)` 在每次节点调用时
记录一行 `type="agent_trace"`，按 `round`/`step` 索引，便于失败定位（哪一轮、哪个节点、成功/失败）。
由 `graph.py` 的 `_run_traced` 非侵入式包装写入，不改变既有图行为。

### 5.3 审计 Trail（阶段 B5/J6）

`AuditService` 记录 tool_call / policy decision / approval outcome，写入前经
`logging.redact_sensitive` 脱敏，保证密钥不进入审计。通过 `GET /api/audit` 按多维条件查询。

## 6. 业务技能（阶段 H）

`fiat_agent/skills/loader.py::SkillLoader` 以文件系统发现方式加载 `fiat_agent/skills/<package>/SKILL.md`：
YAML frontmatter（`task_type`/`name`/`tools`/`output_schema`/`version`）+ Markdown body（domain system prompt）。
5 个技能包：`rag_qa` / `alert_diagnosis` / `test_env_automation` / `cashback_reconcile` / `logistics_validation`，
各自 prompt/tools/output_schema 不同。`ContextBuilder` 把匹配技能的 domain prompt 增量注入 system prompt。

## 7. 数据模型（SQLite 默认 / PostgreSQL 扩展）

会话相关表（`fiat_agent/sessions/store.py`）：`task_sessions`、`task_session_events`（树形、只追加、
`seq` 单调、连 `parent_event_id`）、`task_artifacts`、`tool_calls`、`session_branches`。
审计表（`fiat_agent/audit/repository.py`）：`audit_logs`。详见 [session-memory-design.md](session-memory-design.md)。
