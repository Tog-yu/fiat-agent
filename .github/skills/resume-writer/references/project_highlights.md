# fiat-agent 可验证项目亮点

> 使用前继续读取对应源码。每个亮点都给出“可写事实、边界、证据、量化方式、面试追问”。

## 亮点 1：LangGraph ReAct 编排与人工审批中断

**可写事实**

- 构建 `classify → build_context → model → plan → approval → tool → model → final` 条件图。
- 使用 append reducer 累积消息与工具结果。
- 审批 pending 时终止当前图运行，阻止未授权工具执行。
- 为每个节点记录 round/step/node/status Trace。

**边界**

- 当前 graph checkpointer 使用 `MemorySaver`；不能直接写成“数据库持久化 checkpoint 已完整接入”。
- 任务分类当前为确定性关键词规则，不是复杂 LLM router。

**证据**

- `fiat_agent/orchestrator/graph.py`
- `fiat_agent/orchestrator/state.py`
- `fiat_agent/orchestrator/nodes/`
- `tests/integration/test_agent_graph.py`

**量化方式**：图节点数、覆盖的任务类型、Trace 步骤、相关测试数；需动态统计。

**面试追问**：为什么 approval pending 直接 END？append reducer 解决什么问题？

## 亮点 2：确定性 Tool Gateway 安全边界

**可写事实**

- 建立统一工具注册与唯一名称约束。
- 在所有 handler 副作用前执行 RBAC 与审批门控。
- 将成功、拒绝、待审批、缺 handler、异常统一归一化。
- 记录 tool call 与 audit，模型只消费安全摘要。

**边界**

- 不要写“所有业务后端均已接入”；部分 handler 默认 unavailable。
- 审批通过后的重放/续执行需按具体调用链说明，不能泛称完整工作流引擎。

**证据**

- `fiat_agent/tools/registry.py`
- `fiat_agent/tool_gateway/gateway.py`
- `fiat_agent/auth/policy.py`
- `tests/unit/test_tool_gateway.py`

**量化方式**：策略工具数量、状态类型、拒绝/审批测试用例数。

**面试追问**：为什么需审批工具仍对模型可见？raw 为什么不回灌模型？

## 亮点 3：声明式 RBAC、审批与审计治理

**可写事实**

- 用 YAML 声明角色、环境、风险、scope、collection scope 与 denied action。
- L4/L5 强制审批；L5 支持两个不同审批人。
- 审批冻结参数快照，决定后不可重复修改。
- 审计覆盖工具、策略、审批、模型用量与 Agent Trace，并统一脱敏。

**边界**

- 当前审批 repository 默认内存实现；描述持久化能力时需核实具体装配。
- 双人审批是 L5 规则，不要泛称所有高风险工具都双签。

**证据**

- `config/tool_policies.yaml`
- `fiat_agent/auth/`
- `fiat_agent/approvals/`
- `fiat_agent/audit/`

**量化方式**：风险等级、策略工具数、审计事件类型、审批测试。

**面试追问**：参数快照防什么问题？拒绝工具为何不能进入审批队列？

## 亮点 4：Append-only 会话、分支与可回放记忆

**可写事实**

- 设计 append-only session event store，使用 `seq + parent_event_id + active_event_id` 同时支持稳定排序和树形分支。
- rollback 仅移动活动指针，不删除历史。
- 支持 checkpoint 数据模型、确定性 compaction、active branch JSONL 导出。
- 短期记忆从活动路径与 checkpoint 组装。

**边界**

- rollback 不撤销外部副作用。
- 长期记忆默认 Null provider，真实后端是扩展点。
- 项目 CheckpointStore 与 graph MemorySaver 的装配边界要如实说明。

**证据**

- `fiat_agent/sessions/`
- `fiat_agent/context/compaction.py`
- `fiat_agent/context/memory.py`
- `docs/session-memory-design.md`

**量化方式**：会话表数、事件类型、分支/导出/压缩测试数。

**面试追问**：seq 和 parent_id 是否重复？为什么不删除原事件？

## 亮点 5：配置驱动的模型路由与 Function Calling 适配

**可写事实**

- 定义 provider-neutral 模型消息、请求、响应和 token usage 契约。
- 按 task/complexity tier 选择 provider，并支持禁用与 fallback。
- 复用 OpenAI-compatible provider 适配不同兼容端点。
- 将 ToolDefinition/Pydantic/MCP schema 归一化为 provider 工具格式。
- 通过 audit sink 记录模型用量。

**边界**

- Anthropic provider 当前未实现，local 默认 disabled。
- “多 Provider 热切换”应改为“配置驱动选择与降级”，除非验证无重启动态加载。

**证据**

- `fiat_agent/models/`
- `fiat_agent/tools/function_calling.py`
- `config/model_policies.yaml`

**量化方式**：tier 数、配置 provider 数、实际 enabled/implemented provider 数。

**面试追问**：simple tier 如何 fallback？schema 能生成为何 provider 仍不能跑？

## 亮点 6：外部 MCP RAG 的可信集成与降级

**可写事实**

- 通过 MCP stdio 启动并初始化外部 RAG Server，封装三个工具。
- 对 MCP `isError` 显式失败，避免错误结果进入上下文。
- 分离文本、图片与 metadata，构造可追溯 Citation。
- API 失败返回 disabled/unavailable；RAG QA 无证据时确定性拒答。

**边界**

- Hybrid Search、BM25、RRF、Rerank 属于外部仓库，不要写成本项目内部算法实现。
- 实际检索准确率和延迟必须来自外部服务联调结果。

**证据**

- `fiat_agent/mcp_clients/`
- `fiat_agent/rag/`
- `fiat_agent/workflows/rag_qa.py`
- `apps/api/rag_service.py`

**量化方式**：MCP 工具数、Citation 字段、降级分支、RAG 集成测试数。

**面试追问**：为什么 ImageContent 不拼进文本？RAG Server 不可用时用户看到什么？

## 亮点 7：可组合 Domain Skill 与五类业务 Workflow

**可写事实**

- 用文件系统发现 `SKILL.md`，解析 task_type、tools、output_schema 与 domain prompt。
- 为五类业务任务提供差异化 Skill 与 Workflow。
- Context Builder 可把 domain prompt 与权限过滤后的工具组合进模型上下文。

**边界**

- 写“5 个 Domain Skill”前动态统计。
- 某些 workflow 设计完整，但依赖的真实外部 handler 可能仍是 stub。

**证据**

- `fiat_agent/skills/loader.py`
- `fiat_agent/skills/*/SKILL.md`
- `fiat_agent/workflows/`
- `tests/unit/test_domain_skill_loader.py`

**量化方式**：Skill 数、TaskType 数、Workflow 数、不同 output schema 数。

**面试追问**：frontmatter 与正文分别如何被消费？权限过滤发生在哪？

## 亮点 8：金融表格与物流状态机的确定性处理

**可写事实**

- 支持 CSV/XLSX 解析、字段映射和逐行错误收集。
- 返现金额采用 Decimal，识别格式异常、重复记录并生成 dry-run 计划。
- 物流校验包含运单/地址/卡号 Luhn 与显式状态机。
- ProductionSubmitGuard 在审批后仍默认 fake，保证 MVP 无生产写入。

**边界**

- 不要声称已自动修复或提交生产数据。
- 处理规模和性能需真实压测。

**证据**

- `fiat_agent/tool_gateway/cashback_tools.py`
- `fiat_agent/tool_gateway/logistics_tools.py`
- `fiat_agent/workflows/cashback_reconcile.py`
- `fiat_agent/workflows/production_submit.py`

**量化方式**：支持格式、校验规则、状态数、异常类型、测试用例。

**面试追问**：为什么用 Decimal？同状态更新为何允许？

## 亮点 9：事件总线、SSE 续传与多入口适配

**可写事实**

- 进程内 Event Bus 支持全局/topic/kind 订阅、去重和故障隔离。
- EventStreamManager 使用有界环形缓冲、单调 seq、replay + live 无缺口。
- 提供 FastAPI、CLI、Lark、MCP Adapter 与 Web Console。
- 多入口复用相同 Tool Gateway、审批与审计边界。

**边界**

- Event Bus 是进程内，不要包装成分布式消息系统。
- Lark outbound 默认 no-op，具体生产凭证/网络接入需另行确认。
- Web 技术版本从当前 `package.json` 读取。

**证据**

- `fiat_agent/events/`
- `apps/api/`, `apps/cli/`, `apps/lark_bot/`
- `adapters/claude_code_mcp/`
- `apps/web_console/src/`

**量化方式**：入口数、页面数、事件类型、buffer 长度、相关测试。

**面试追问**：为何先注册 queue 再 snapshot？进程重启后 buffer 如何？

## 亮点 10：分层、Hermetic 的测试与评测闭环

**可写事实**

- 按 unit/integration/e2e markers 分层。
- 使用 scripted model、临时/内存 DB、fake handler 和 FastAPI dependency override 隔离外部系统。
- E2E 覆盖 RAG、告警、测试环境、权限拒绝、审批等待等 MVP 流。
- 提供 Agent eval case 数据集和结构化输出断言。

**边界**

- 测试数量必须动态统计。
- “全绿”必须实际运行；“覆盖率”必须有 coverage 工具结果。
- hermetic E2E 不等于真实 LLM/MCP/生产后端压测。

**证据**

- `pyproject.toml`
- `tests/unit/`, `tests/integration/`, `tests/e2e/`
- `tests/fixtures/agent_eval_cases.json`

**量化方式**：测试文件数、函数数、eval case 数、实际 pytest 结果。

**面试追问**：什么是 hermetic E2E？为什么失败路径比 happy path 更关键？
