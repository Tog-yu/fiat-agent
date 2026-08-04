# fiat-agent 模拟面试题库

## 方向 1：项目综述开场题池（12 题）

按 `[DICE] × 2 - 1` 选首题。

1. 请介绍 `fiat-agent` 解决的业务问题、主要分层和安全边界。
2. 从用户在 Web Console 发消息到最终答案返回，完整链路经过哪些组件？
3. 为什么本项目把 RAG 放在外部 MCP Server，而不是直接写在仓库里？
4. 这个系统与普通“LLM + 一堆工具”的 Demo 最大区别是什么？
5. 你认为项目最难的模块是什么？难点是算法、状态还是安全边界？
6. 如果模型错误地请求了一个用户无权使用的工具，系统如何处理？
7. 项目里哪些能力是确定性的，哪些可以交给 LLM？
8. 会话、审计和 Agent Trace 分别解决什么可观测问题？
9. 当前项目哪些能力已真实接入，哪些仍是 stub 或扩展点？
10. 多入口如何保证权限与审计语义一致？
11. 如果把系统改造成多租户，需要优先改哪些数据和权限边界？
12. 如果让你删掉一个“看起来过度设计”的模块，你会选什么，为什么？

### 追问灵感（必须结合用户原话重写）

- 你刚才提到“确定性”，能给出具体文件和失败路径吗？
- 你说“会话可回退”，外部副作用也会回退吗？
- 你说“多模型”，当前哪些 provider 真能跑？
- 你说“完整接入”，生产装配 handler 在哪里？
- 你说“审计”，拒绝和待审批是否也会记录？

## 方向 2：简历/项目经历深挖

### P1 — 量化指标（6 题）

1. 你写的测试数量是怎么统计的？测试文件数、test function 数和通过数分别是多少？
2. 你写的响应延迟是在真实模型、scripted model 还是纯单测环境测的？P50/P95/P99 哪个？
3. 你写的准确率或命中率由哪个数据集和断言得到？能在当前仓库复现吗？
4. 你写“71 个任务完成”，这是规格任务数还是可运行功能数？如何避免混淆？
5. 你写支持多入口或多个工具，哪些是生产 handler，哪些是 stub？
6. 你写效率提升 X%，baseline、样本和测量窗口是什么？

### P2 — 强动词（8 题）

1. 你说“主导设计 Agent 编排”，请解释 graph 的条件边和审批终止点。
2. 你说“设计权限体系”，`can_execute` 的决策顺序是什么？
3. 你说“实现会话回退”，rollback 实际修改哪一个字段？
4. 你说“设计模型路由”，local provider 不可用时如何 fallback？
5. 你说“构建工具网关”，为什么鉴权必须发生在 handler 前？
6. 你说“实现完整 RAG”，哪些实现属于外部仓库，哪些属于本仓库？
7. 你说“实现生产安全提交”，MVP 默认到底会不会写生产？
8. 你说“构建长期记忆”，默认 provider 返回什么？真实后端在哪里？

### P3 — 技术声称（10 题）

1. LangGraph 中 append reducer 的作用是什么？
2. ToolResult 的 `content` 和 `raw` 为什么要分开？
3. L4/L5 审批与 L5 双人审批分别在哪一层实现？
4. replay + live 为什么要先注册订阅队列再 snapshot？
5. MCP `isError` 为什么不能当正常文本返回？
6. `seq`、`parent_event_id`、`active_event_id` 分别是什么？
7. 物流状态机里 `exception` 和 `returned` 如何流转？
8. 为什么返现金额使用 Decimal？
9. OpenAI-compatible provider 如何支持不同厂商？
10. `ToolRegistry` 为什么不允许工具重名？

### 无简历题池（8 题）

1. 如果你要把这个项目写进简历，最想强调哪个亮点？如何证明？
2. 项目里最容易被候选人包装过度的能力是什么？
3. 如果面试官问“这不是一个 Demo 吗”，你会如何用源码事实反驳？
4. 你会如何解释外部 RAG Server 与本仓库的贡献边界？
5. 如果要生产化，当前最优先补齐的三个缺口是什么？
6. 权限、审批、审计三者为什么不能合并成一个模块？
7. 会话回退、Checkpoint、Compaction 三者的职责有何不同？
8. 选一个业务 workflow，讲清输入、确定性校验、工具和输出。

## 方向 3：技术深挖题库

### A — LangGraph 与上下文（8 题）

A1. 画出完整图路由；为什么 approval pending 直接 END？
A2. `GraphState.messages` 为什么不能普通 list 覆盖？
A3. classify 未识别任务时，后续 Context Builder 和 final 会怎样？
A4. plan 中无权工具为什么裁剪而不是直接让整个计划失败？
A5. `_derive_plan` 如何计算最高风险和 need_approval？
A6. 递归上限 25 防止什么问题？
A7. Domain Skill 当前是否真的注入 graph 的 ContextBuilder？请沿调用链确认。
A8. 如果 model 连续请求同一工具，当前图如何终止或失控？你会怎么改？

### B — 工具、安全与审批（8 题）

B1. `ToolGateway.execute_tool` 的每一步顺序和副作用是什么？
B2. 权限拒绝、待审批、handler 缺失、handler 异常分别返回什么状态？
B3. 为什么需审批工具仍要暴露给模型？
B4. `params_summary` 快照防的是什么竞态或攻击？
B5. L5 双人审批为什么要求两个不同 ID？拒绝后还能批准吗？
B6. ES/DB 工具如何避免模型注入任意查询？
B7. 当前 `can_execute` 对多角色 actor 的实现有什么可讨论之处？
B8. 为什么 MCP Adapter 必须映射到内部 tool policy key？

### C — 会话、分支与记忆（8 题）

C1. `seq` 与 parent tree 同时存在是否冗余？各自支持什么查询？
C2. rollback 到旧事件后，新 append 的 parent 是谁？
C3. 为什么 active branch JSONL 不导出其他分支？这有什么取舍？
C4. compaction summary 如何提取 user_goal、risk 和 approval status？
C5. CheckpointStore 和 MemorySaver 当前装配是否一致？
C6. 长期记忆为什么用 Protocol + Null provider？
C7. 如果 parent_event_id 出现环，路径遍历如何保护？
C8. 会话回退为什么不能自动撤销工具调用？如何设计补偿？

### D — 模型与 Function Calling（8 题）

D1. provider-neutral contract 如何降低业务层对 SDK 的耦合？
D2. simple tier 当前如何从 local 降级到 deepseek？
D3. Anthropic schema 能生成，为什么 Anthropic provider 仍不能运行？
D4. OpenAI streaming tool call delta 的合并在当前实现中完整吗？有哪些风险？
D5. API key 如何从配置名解析，为什么 response.raw 不会泄露 key？
D6. tool call arguments 为什么保存为 JSON string，到 tool node 才解析？
D7. token usage 的审计 sink 如何与 ModelGateway 解耦？
D8. 如果所有 fallback provider 都 disabled，会发生什么？

### E — MCP RAG（8 题）

E1. `RagMcpClient` 的 start/initialize/close 资源管理如何保证？
E2. stdout/stderr 混用会怎样破坏 MCP stdio？
E3. `query_knowledge_hub` 的参数如何构造？collection 何时省略？
E4. Text/Image/Metadata 为什么不能简单拼成一段字符串？
E5. Citation 缺失时 RAG QA 为什么必须拒答？
E6. RagService 为什么每次使用短生命周期 client？有什么性能取舍？
E7. RAG MCP startup 失败时 tools list 与 health status 如何返回？
E8. Hybrid Search/RRF 是哪个仓库的职责？本仓库如何保持集成可测试？

### F — 业务 Workflow（8 题）

F1. Domain Skill frontmatter 与正文分别被谁消费？
F2. RAG QA 的 no-evidence 与 query-error 两种拒答有什么区别？
F3. 告警诊断为什么适合并行证据收集？当前真实 handler 边界是什么？
F4. test_env 的环境、action 和 `TEST_` 三层约束如何配合？
F5. 返现解析如何处理金额格式、重复记录和问题分类？
F6. 物流 no-op 状态流转为什么合法？`returned` 为什么是终态？
F7. Luhn 校验在物流记录中解决什么问题？
F8. ProductionSubmitGuard 在 approved 但 disabled 时返回什么？

### G — Events 与入口（8 题）

G1. Event Bus topic/kind 匹配后如何避免同一 handler 调两次？
G2. 某个 Lark subscriber 抛异常为什么不影响 SSE？
G3. 环形缓冲满后旧 cursor 会遇到什么问题？当前如何处理？
G4. replay/live 无缺口的关键时序是什么？
G5. FastAPI dependency override 为什么对 E2E 很重要？
G6. Lark Bot 默认 sender 为什么是 no-op？
G7. MCP Adapter 的 external tool name 与 internal tool name 如何映射？
G8. Web Console 展示 tool trace 需要后端事件包含哪些字段？

### H — 测试、配置与系统设计（8 题）

H1. 三层测试各自应该 mock 什么、不 mock 什么？
H2. 如何证明“测试全绿”而不只证明“有很多测试”？
H3. 为什么权限拒绝和审批 pending 是比 happy path 更重要的回归场景？
H4. `${VAR:-default}` 解析如何支持本地与部署环境？
H5. SQLite 切 PostgreSQL 理论上为何无需改业务代码，实际还需验证什么？
H6. 如果要做多租户，session、audit、tool scopes 与 RAG collection 如何隔离？
H7. 如果要把 fake backend 换成生产 backend，最小安全上线清单是什么？
H8. 选择一个当前扩展点，给出不破坏现有边界的演进方案。
