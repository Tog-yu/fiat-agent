# fiat-agent 面试官项目知识库

## 事实优先级

1. 当前源码、配置、测试与 lock/package 文件。
2. README 与 `docs/` 对当前装配的说明。
3. `DEV_SPEC.md` 的设计意图和任务历史。

不要把规格目标、注释中的后续阶段或外部 RAG Server 的内部能力误判为本仓库已实现事实。

## 1. 项目定位与架构

- 面向法币业务内部场景的独立 Agent 系统。
- 五类 `TaskType`：`rag_qa`、`alert_diagnosis`、`test_env_automation`、`cashback_reconcile`、`logistics_validation`。
- 入口：FastAPI、CLI、Lark Bot、Next.js Web Console、fiat MCP Adapter。
- 核心链路：入口 → ActorContext → LangGraph → Context/Model Gateway → Tool Gateway → Workflow → Session/Audit/Event。
- 核心原则：LLM 不负责权限、审批状态、金额、状态机、字段校验、生产提交与审计。

高频追问：为什么 Prompt 不是权限边界？为什么生产副作用不能由 Agent 直接执行？

## 2. LangGraph ReAct 编排

实际图：

```text
classify → build_context → model
model(tool_calls) → plan → approval → tool → model
model(no tool_calls) → final → END
approval(PENDING) → END
```

- `GraphState.messages`、`tool_results` 使用 append reducer。
- 分类为有序关键词匹配，未知返回 `None`。
- plan 由工具调用确定性派生并校验；不可用工具可裁剪为 `DEGRADED`。
- approval pending 时图终止，不执行工具。
- graph compile 当前使用 `MemorySaver`，而项目另有 SQLAlchemy `CheckpointStore`；不能混为“已完全持久化接入”。
- 每节点可经 `_run_traced` 写 `round/step/node/status/detail`。

## 3. Model Gateway 与 Function Calling

- 统一契约：`ChatMessage`、`ChatRequest`、`ChatResponse`、`FunctionCall`、`TokenUsage`、`BaseChatModel`。
- 模型路由：task_type/complexity → tier → provider；禁用时按 fallback 链查找。
- 当前真正构造的是 OpenAI-compatible provider；Anthropic 分支明确 `NotImplementedError`，local 默认 disabled。
- OpenAI-compatible provider 通过 `base_url/model/api_key_env` 支持不同兼容端点。
- Tool schema 可从 ToolDefinition、Pydantic、MCP item 或 dict 归一化为 OpenAI/Anthropic 格式。
- Tool result 回灌只使用安全摘要，`raw` 不进入模型上下文。

## 4. Tool Gateway 与安全查询

- `ToolRegistry` 拒绝重名，防止业务工具与 MCP 工具覆盖。
- 唯一执行入口 `ToolGateway.execute_tool`：鉴权 → 审批 → handler → 归一化 → tool record/audit。
- handler 异常变成结构化 ERROR，不向 Agent 泄漏原始堆栈。
- 结果摘要限制 500 字符。
- ES/DB 工具只允许固定模板和参数绑定，禁止任意 DSL/SQL。
- 当前真实装配：`rag_query`、`cashback_parse`、`logistics_validate`。
- 当前默认 stub：`es_query`、`db_query`、`lark_notify`、`test_env`、`cashback_reconcile` 等。
- `cashback_submit` 在策略中无人可执行，并有 denied action。

## 5. 权限、审批与审计

- `ToolPolicy`：risk、allowed roles/environments/scopes、collection scopes、approval flag、denied actions。
- `can_execute`：无策略拒绝 → 角色/环境拒绝 → denied action → allowed；L4/L5 强制审批。
- 需审批工具仍可见，执行时由网关阻断。
- Approval 保存参数快照；决定后不可重复修改。
- L5 要求两个不同 approver。
- Audit 记录 tool_call、policy、approval、model_usage、agent_trace，并对 metadata 脱敏。

警惕：当前 `can_execute` 的 `allows_role_env` 首次检查使用 actor.roles[0]，虽然随后错误原因检查所有角色；这是可讨论的实现细节与潜在改进点。

## 6. 会话、分支与记忆

- 核心表：task_sessions、task_session_events、task_artifacts、tool_calls、session_branches；另有 graph_checkpoints。
- append-only：无编辑历史 API；追加后更新 `active_event_id`。
- `seq` 给稳定全序，`parent_event_id` 给树形路径。
- rollback 只移动 active pointer；新消息从旧事件派生分支；不会回滚外部副作用。
- compaction 是确定性摘要并追加新事件，原事件保留。
- 短期记忆来自 active path + latest checkpoint。
- 长期记忆默认 `NullLongTermProvider`，真实后端是扩展点。
- JSONL 导出 active branch 的 root→tip。

## 7. MCP RAG

- 本仓库不实现 Hybrid Search/Rerank，只消费外部 `MODULAR-RAG-MCP-SERVER`。
- `RagMcpClient`：stdio 子进程、initialize、tools/list/tools/call、close。
- 三个工具：`query_knowledge_hub`、`list_collections`、`get_document_summary`。
- MCP `isError` 转 `ToolExecutionError`，防止错误结果污染上下文。
- Content parser 分离 text、image、metadata；图片不拼进纯文本。
- `Citation` 保留 collection/doc_id/chunk_id/source/snippet/score。
- `RagService` 失败返回 `disabled/unavailable`，不抛 500。
- RAG QA 没有 citations 时确定性拒答。

## 8. Domain Skill 与业务 Workflow

- `SkillLoader` 读取 `fiat_agent/skills/<package>/SKILL.md`，frontmatter 定义 task_type、tools、output_schema，正文注入 system prompt。
- RAG QA：先检索、有引用才回答。
- 告警诊断：设计上聚合 ES/DB/RAG/Lark；外部 handler 的真实接入状态要单独说明。
- test env：只允许 dev、有限 action、资源 `TEST_` 标记。
- 返现：CSV/XLSX 解析、Decimal 金额、去重、问题分类、dry-run 计划。
- 物流：字段校验、运单号格式、可选卡号 Luhn、确定性状态机。
- ProductionSubmitGuard 默认关闭，审批通过后仍只返回 fake，除非显式启用并提供 submit handler。

## 9. Events、API 与适配器

- Event Bus 支持全局、topic、kind 订阅；对同一 handler 去重；订阅者异常隔离。
- EventStreamManager 使用长度 2000 的环形缓冲和单调 seq。
- stream 先注册 queue 再 snapshot，保证 replay 与 live 无缺口。
- SSE 使用 seq 作为 event id，可通过 Last-Event-ID/cursor 续传。
- FastAPI 依赖可覆盖，E2E 能注入 hermetic AgentService。
- Lark sender 默认 no-op；MCP Adapter 的外部工具名映射到内部策略 key 后仍走 Tool Gateway。
- Web Console 页面覆盖 sessions/chat、tool trace、citations、approvals、audit；实际依赖版本以 package.json 为准。

## 10. 测试与工程事实

- pytest markers：unit / integration / e2e。
- E2E 使用 scripted model、内存或临时 DB、fake tool handler，避免真实 LLM/MCP/生产系统。
- 当前仓库规模需动态统计；不要死记过时数字：

```bash
rg --files tests -g 'test_*.py' | wc -l
rg -n '^\s*(async )?def test_' tests | wc -l
rg -n '^### \[x\]' DEV_SPEC.md | wc -l
```

- “测试全绿”必须来自本次实际运行 `pytest -q`，不能由文件数量推断。
- 当前常见扩展点：多 Agent、真实长期记忆、真实生产提交、PostgreSQL 主线、Anthropic provider、部分外部 backend、Agent 回放。

## 常见露馅信号

| 简历声称 | 验证问题 | 露馅信号 |
|---|---|---|
| “主导 Hybrid Search/RRF” | 代码在哪个仓库？本仓库做了什么？ | 把外部 RAG Server 的实现算成本仓库代码 |
| “多模型全量可插拔” | Anthropic/local 当前能否实例化？ | 不知道 NotImplemented/disabled |
| “完整接入 ES/DB/Lark” | production wiring 在哪？ | 不知道 unavailable handler |
| “可恢复长期记忆” | NullLongTermProvider 是什么？ | 把接口预留说成已接后端 |
| “生产返现自动提交” | policy 与 submit guard 怎么限制？ | 不知道 allowed_roles 空、fake submit |
| “会话回退撤销操作” | rollback 修改什么？ | 误以为回滚外部副作用 |
| “测试 100% 全绿” | 最近一次命令和环境是什么？ | 只有测试文件数量，没有运行证据 |
