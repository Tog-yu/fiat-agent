# fiat-agent 项目复习题库

> 共 10 章 70 题。⭐ 基础，⭐⭐ 进阶，⭐⭐⭐ 深挖。参考答案必须结合当前源码核验。

## 第 1 章：项目定位、架构与设计原则（7 题）

| # | 题目 | 难度 | 考察要点 | 参考答案要点 |
|---|---|---|---|---|
| 1-01 | `fiat-agent` 要解决哪些法币业务问题？它不是什么？ | ⭐ | 项目定位 | 独立业务 Agent；支持 RAG、告警、测试环境、返现、物流、权限审批审计与会话；不是 Claude Code/Pi 插件，Pi 仅作架构参考 |
| 1-02 | 为什么要把 LLM 与业务执行隔离？ | ⭐⭐ | 安全边界 | LLM 负责理解/规划/解释；生产动作必须走受控 API、Tool Gateway、审批与审计；Prompt 不能作为权限边界 |
| 1-03 | 哪些能力必须由确定性代码实现？ | ⭐ | 确定性优先 | 权限、审批状态、金额、物流状态机、字段校验、生产提交、审计；不能交给 LLM 猜 |
| 1-04 | 从入口到最终响应，系统分成哪些主要层？ | ⭐⭐ | 分层架构 | apps/adapters → auth context → orchestrator/context → model gateway → tool gateway/MCP → workflow → sessions/approval/audit/events |
| 1-05 | 为什么本项目不重复实现 RAG 检索算法？ | ⭐⭐ | 项目边界 | 外部 `MODULAR-RAG-MCP-SERVER` 已提供 RAG；本项目只做 MCP Client、适配、权限过滤、解析、合并、审计和降级 |
| 1-06 | 当前 SQLite 与 PostgreSQL 的关系是什么？ | ⭐⭐ | 事实核验 | SQLite 是默认主线；SQLAlchemy URL scheme 支持扩展；PostgreSQL 需要 optional dependency 与配置，不应描述成默认已部署 |
| 1-07 | `DEV_SPEC.md`、README、源码冲突时应信谁？举一个版本差异例子。 | ⭐⭐⭐ | Source of truth | 运行事实以源码/lock/config 为准；规格用于意图；例如 DEV_SPEC 目标版本与当前 pyproject/package.json 版本不完全一致 |

## 第 2 章：LangGraph 编排与上下文（8 题）

| # | 题目 | 难度 | 考察要点 | 参考答案要点 |
|---|---|---|---|---|
| 2-01 | `AgentState` 保存哪些核心状态？ | ⭐ | 状态模型 | actor/session_id/messages/task_type/tool_results/approval_state/system_prompt/tool_schemas |
| 2-02 | `GraphState` 为什么给 messages 和 tool_results 配 append reducer？ | ⭐⭐ | LangGraph 状态合并 | ReAct 多轮中增量追加，避免节点 delta 覆盖历史消息和工具结果 |
| 2-03 | 任务分类是 LLM 做的吗？未知输入如何处理？ | ⭐ | 分类节点 | `classify_task` 用有序关键词规则；未知返回 None，不猜测 |
| 2-04 | Context Builder 如何避免模型看到无权调用的工具？ | ⭐⭐ | 权限过滤 | `ToolRegistry.filter` → `filter_tools` → `can_execute`；只把允许工具转为 OpenAI schema |
| 2-05 | 完整图路由是什么？ | ⭐⭐ | ReAct 流 | classify → build_context → model；有 tool_calls 则 plan→approval→tool→model；无 tool_calls 则 final；pending approval 直接 END |
| 2-06 | Planning 节点做了哪些确定性校验？ | ⭐⭐ | 计划校验 | 校验 steps 非空、工具存在；非法结构 retry；无权工具被裁剪为 degraded；风险/审批由规则计算 |
| 2-07 | 为什么审批 pending 时不能进入 tool 节点？ | ⭐⭐ | 副作用控制 | 人工决定前必须终止图；否则会绕过审批产生副作用；被拒绝的工具也不应进入审批队列 |
| 2-08 | Agent Trace 如何定位失败发生在哪一轮哪一节点？ | ⭐⭐⭐ | 可观测性 | `_run_traced` 记录 round/step/node/status/detail；工具逻辑失败也可用 status_fn 标成 error |

## 第 3 章：模型网关与 Function Calling（7 题）

| # | 题目 | 难度 | 考察要点 | 参考答案要点 |
|---|---|---|---|---|
| 3-01 | Provider-neutral 模型契约包括哪些对象？ | ⭐ | 数据契约 | ChatMessage/ChatRequest/ChatResponse/FunctionCall/TokenUsage/BaseChatModel |
| 3-02 | task type 如何映射到模型 provider？ | ⭐⭐ | 路由策略 | task_tiers → tier → provider；显式 complexity 优先；缺省用 default_tier |
| 3-03 | local provider 禁用时，simple 任务如何降级？ | ⭐⭐ | fallback | 按 `fallback.simple: [medium, complex]` 依次找 enabled provider，当前通常落到 deepseek |
| 3-04 | 当前 Anthropic provider 是否真正实现？ | ⭐ | 事实边界 | 配置类型存在，但 `build_provider` 对 anthropic 抛 NotImplementedError；local 默认 disabled |
| 3-05 | OpenAI-compatible provider 如何支持 OpenAI、DeepSeek 和中转服务？ | ⭐⭐ | 适配设计 | 复用同一 `/chat/completions` 客户端，通过 base_url/model/api_key_env 配置差异化 |
| 3-06 | 工具 schema 如何在 OpenAI、Anthropic 和 MCP 形态之间归一化？ | ⭐⭐⭐ | schema 转换 | `_normalize` 接受 ToolDefinition/Pydantic/MCP/dict，再输出 provider 所需结构 |
| 3-07 | 为什么 ToolResult.raw 不应回灌模型？token usage 又如何审计？ | ⭐⭐ | 信息边界 | 只回灌安全 content/error，避免敏感大对象；ModelGateway 通过 audit_sink 记录 usage |

## 第 4 章：工具注册、网关与安全查询（8 题）

| # | 题目 | 难度 | 考察要点 | 参考答案要点 |
|---|---|---|---|---|
| 4-01 | `ToolDefinition` 描述了什么？ | ⭐ | 工具契约 | name/description/risk/approval/input schema 等声明式信息 |
| 4-02 | 为什么 `ToolRegistry` 拒绝重复名称？ | ⭐⭐ | 命名安全 | 防止业务工具与 MCP 工具互相覆盖或劫持；重复抛异常 |
| 4-03 | `ToolGateway.execute_tool` 的执行顺序是什么？ | ⭐⭐ | 网关流程 | can_execute → approval gate → handler → normalize → tool_calls + audit；所有副作用前先鉴权 |
| 4-04 | handler 抛异常后为什么 Agent Loop 还能继续？ | ⭐ | 异常归一化 | 网关捕获异常并返回 ERROR ToolResult，不泄漏原始堆栈 |
| 4-05 | 为什么模型只看到最长 500 字符的结果摘要？ | ⭐⭐ | 上下文安全 | 控制上下文体积，减少敏感/超大原始结果进入模型；raw 留在结构化结果侧 |
| 4-06 | ES 工具为什么不接受任意 DSL？ | ⭐⭐⭐ | 注入防护 | 固定模板 + 参数校验/绑定，防止模型生成危险任意查询；DB 同理不接受任意 SQL |
| 4-07 | 当前哪些工具是真实接入，哪些是 unavailable stub？ | ⭐⭐ | 装配边界 | rag_query、cashback_parse、logistics_validate 真实；ES/DB/Lark/test_env/cashback_reconcile 等默认 stub；cashback_submit 策略禁止 |
| 4-08 | MCP Adapter 为什么仍然必须经过同一个 Tool Gateway？ | ⭐⭐ | 多入口一致性 | 外部 MCP 入口不能绕过 RBAC/审批/审计；external name 映射 internal policy key 后执行 |

## 第 5 章：会话、分支、Checkpoint 与记忆（8 题）

| # | 题目 | 难度 | 考察要点 | 参考答案要点 |
|---|---|---|---|---|
| 5-01 | 会话存储包含哪五张核心表？ | ⭐ | 数据模型 | task_sessions/task_session_events/task_artifacts/tool_calls/session_branches，另有 graph_checkpoints |
| 5-02 | append-only 是如何从 API 设计上保证的？ | ⭐⭐ | 不可变历史 | 只提供 append_event，没有编辑历史内容方法；每次追加新行并推进 active_event_id |
| 5-03 | `seq` 与 `parent_event_id` 各解决什么问题？ | ⭐⭐ | 排序与树 | seq 给全会话稳定顺序；parent_event_id 构造分支树和 root→event 路径 |
| 5-04 | rollback 为什么只是移动指针？ | ⭐⭐ | Pi 风格回退 | 保留历史，移动 active_event_id；后续 append 从目标事件派生新分支 |
| 5-05 | 会话回退会撤销已经执行的生产副作用吗？ | ⭐ | 安全边界 | 不会；会话历史和外部副作用分离，需显式补偿流程 |
| 5-06 | CheckpointStore 与 LangGraph MemorySaver 是什么关系？ | ⭐⭐⭐ | 恢复机制 | 前者是项目持久化模型/接口；当前 graph compile 使用内存 MemorySaver，需区分已定义能力和实际装配 |
| 5-07 | Compaction 为什么不删除原事件？ | ⭐⭐ | 可回放 | 只追加摘要，保留审计/回放真相；摘要含目标、工具结果、引用、审批和风险等 |
| 5-08 | 当前长期记忆是否已接入真实后端？JSONL 导出什么路径？ | ⭐⭐⭐ | 实现边界 | 默认 NullLongTermProvider 返回空；JSONL 导出 active branch root→tip，排除非活动分支 |

## 第 6 章：MCP RAG 集成（7 题）

| # | 题目 | 难度 | 考察要点 | 参考答案要点 |
|---|---|---|---|---|
| 6-01 | `RagMcpClient` 的标准生命周期是什么？ | ⭐ | MCP 生命周期 | start → initialize → call/list → close；推荐 async context manager |
| 6-02 | stdio transport 为什么要求 stdout 纯净？ | ⭐⭐ | 协议约束 | stdout 承载 JSON-RPC，日志应走 stderr，否则破坏协议帧 |
| 6-03 | 三个 RAG MCP 工具分别做什么？ | ⭐ | 工具契约 | query_knowledge_hub/list_collections/get_document_summary，参数含 query/top_k/collection/doc_id |
| 6-04 | MCP `isError` 为什么要转成 `ToolExecutionError`？ | ⭐⭐ | 信任边界 | 防止错误响应静默进入受信 RAG 上下文，交由上层降级 |
| 6-05 | TextContent、ImageContent、metadata 为什么分开？ | ⭐⭐ | 内容解析 | 图片不拼进文本上下文；文本供模型，图片独立传输，metadata 用于 Citation |
| 6-06 | Citation 如何保持 collection/doc/chunk 可追溯？ | ⭐⭐ | 引用透明 | 显式 Citation 模型，context 在答案后附 Sources；提取 source/snippet/score 等 |
| 6-07 | RAG Server 不可用时 API 与 workflow 各如何降级？ | ⭐⭐⭐ | graceful degradation | RagService 返回 disabled/unavailable 而非 500；RagQaWorkflow 给确定性失败或无依据拒答 |

## 第 7 章：Domain Skill 与业务 Workflow（8 题）

| # | 题目 | 难度 | 考察要点 | 参考答案要点 |
|---|---|---|---|---|
| 7-01 | Domain Skill 的 `SKILL.md` frontmatter 必须提供哪些核心信息？ | ⭐ | Skill 契约 | task_type/name/description/tools/output_schema/version；正文作为 domain system prompt |
| 7-02 | SkillLoader 如何发现、解析和缓存技能？ | ⭐⭐ | Loader | 遍历技能目录下 SKILL.md；YAML + body 解析；按 TaskType 缓存；未知抛 SkillNotFound |
| 7-03 | RAG QA 如何做到“无依据时拒答”？ | ⭐⭐ | 证据约束 | 必须先走 rag_query；无 citation 或查询失败时输出确定性拒答并 has_evidence=false |
| 7-04 | 告警诊断 workflow 为什么适合并发收集 ES/DB/RAG 证据？ | ⭐⭐ | 工作流 | 独立只读来源可并行降低延迟；结果按 evidence/likelihood/impact 汇总；外部 handler 当前可为 stub |
| 7-05 | test_env workflow 如何防止误伤生产？ | ⭐ | 环境约束 | 只允许 dev、有限 action、资源必须 TEST_ 前缀、失败即停 |
| 7-06 | 返现金额为什么用 Decimal 而不是 float？ | ⭐⭐ | 金融精度 | 避免二进制浮点误差；解析金额、异常分类、重复检测均为确定性代码 |
| 7-07 | 物流状态机允许哪些典型流转？为什么同状态更新可放行？ | ⭐⭐⭐ | 状态机 | created→picked_up→in_transit→out_for_delivery→delivered；exception/returned 分支；no-op 视为幂等更新 |
| 7-08 | ProductionSubmitGuard 为什么即使审批通过也默认不提交？ | ⭐⭐ | MVP 安全开关 | production_submit_enabled 默认 false，返回 fake submitted=false；真实提交是后续扩展且需 handler |

## 第 8 章：权限、审批与审计（6 题）

| # | 题目 | 难度 | 考察要点 | 参考答案要点 |
|---|---|---|---|---|
| 8-01 | ToolPolicy 如何表达角色、环境、scope 和禁止动作？ | ⭐ | 策略模型 | allowed_roles/environments/scopes/collection_scopes/denied_actions/risk/approval_required |
| 8-02 | `can_execute` 的拒绝顺序是什么？ | ⭐⭐ | 决策函数 | 无策略 → 角色/环境 → denied action → allowed；L4/L5 或显式标志触发审批 |
| 8-03 | 为什么需审批工具仍可出现在模型工具列表中？ | ⭐⭐ | 可见与执行 | 工具可见不等于可执行；执行阶段由 approval gate 阻断 |
| 8-04 | Approval 的 params_summary 为什么要复制成快照？ | ⭐⭐ | TOCTOU 防护 | 审批的是固定参数，不能让前端/调用者在批准后偷换内容 |
| 8-05 | L5 双人审批如何防止同一人批准两次？ | ⭐⭐⭐ | 双人审批 | first_approver_id 后要求第二个不同 approver；第二次才 status=approved |
| 8-06 | 审计覆盖哪些事件？敏感信息如何避免落库？ | ⭐⭐ | Audit | tool_call/policy/approval/model_usage/agent_trace；统一 `redact_sensitive` 后存储 |

## 第 9 章：事件流与多入口（6 题）

| # | 题目 | 难度 | 考察要点 | 参考答案要点 |
|---|---|---|---|---|
| 9-01 | Event Bus 的 topic 与 kind 有什么区别？ | ⭐ | 订阅模型 | kind 是粗分类；topic 可细到 session:id；两者都可匹配并去重 handler |
| 9-02 | 一个订阅者异常为什么不会影响其他订阅者？ | ⭐ | 故障隔离 | publish 对每个 handler 单独 try/except，继续广播 |
| 9-03 | EventStreamManager 如何做到 replay + live 无缺口？ | ⭐⭐⭐ | 并发时序 | 先注册队列，再取 snapshot；先发 `seq<=snapshot` 的 replay，再发 live |
| 9-04 | SSE 断线续传依赖什么标识？ | ⭐⭐ | cursor | 单调 seq 作为 SSE id；客户端用 Last-Event-ID 或 cursor 请求缺失事件 |
| 9-05 | FastAPI、CLI、Lark 与 MCP Adapter 如何复用核心服务？ | ⭐⭐ | 入口适配 | 入口只做解析/身份/展示，通过 AgentService/ToolGateway/ApprovalService 等共享核心能力 |
| 9-06 | Web Console 当前承担哪些展示职责？版本事实应从哪里读取？ | ⭐⭐ | UI 边界 | 会话/聊天、工具轨迹、RAG 引用、审批、审计；实际 Next/React/TS 版本以 package.json/lock 为准 |

## 第 10 章：测试、配置与工程边界（5 题）

| # | 题目 | 难度 | 考察要点 | 参考答案要点 |
|---|---|---|---|---|
| 10-01 | `${VAR:-default}` 配置解析有什么价值？密钥如何引用？ | ⭐ | 配置 | 支持环境覆盖和本地默认；配置只保存 api_key_env 名，不内联明文 |
| 10-02 | Unit / Integration / E2E 各自测试什么？ | ⭐ | 测试金字塔 | Unit 纯逻辑；Integration 组件协作；E2E 完整业务链，外部依赖仍可用 scripted fake 保持 hermetic |
| 10-03 | 为什么权限拒绝、审批等待和 unavailable handler 都必须有测试？ | ⭐⭐ | 失败路径 | 安全系统的关键正确性在拒绝/不执行/降级；不能只测 happy path |
| 10-04 | 如何核验测试规模，而不在简历里写过时数字？ | ⭐⭐ | 动态事实 | 用 `rg --files tests -g 'test_*.py'` 和 `rg '^\\s*(async )?def test_' tests` 实时计数；通过情况需实际运行 pytest |
| 10-05 | 列出至少四个不能包装成“已上线”的扩展点。 | ⭐⭐⭐ | 诚实边界 | 多 Agent、真实生产 submit、真实长期记忆、PostgreSQL 主线、Anthropic provider、部分外部 backend、Agent 回放等 |

## 统计

| 章节 | 题数 |
|---|---:|
| 第 1 章 | 7 |
| 第 2 章 | 8 |
| 第 3 章 | 7 |
| 第 4 章 | 8 |
| 第 5 章 | 8 |
| 第 6 章 | 7 |
| 第 7 章 | 8 |
| 第 8 章 | 6 |
| 第 9 章 | 6 |
| 第 10 章 | 5 |
| **合计** | **70** |
