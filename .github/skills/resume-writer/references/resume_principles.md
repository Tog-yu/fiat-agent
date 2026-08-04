# fiat-agent 简历编写原则

## 1. 先证明，再包装

简历中的信息分为：

- **实现事实**：可从源码、配置、测试直接证明。
- **个人贡献**：只能来自用户陈述，不能由仓库所有权自动推断。
- **结果指标**：必须有运行记录、实验方法或用户确认。
- **未来方案**：只能写“设计/规划/预留”，不能写“已上线”。

## 2. 四段式结构

- **背景**：真实团队、对象、问题和旧流程。
- **目标**：要达到的能力，尤其是安全、可靠、可追溯约束。
- **过程**：4-6 条个人贡献，每条“动词 + 实现 + 价值”。
- **结果**：业务指标优先；没有业务指标时使用可验证的工程交付指标。

## 3. 动词强度

| 用户贡献 | 推荐动词 | 避免 |
|---|---|---|
| 独立负责核心设计与实现 | 主导、设计并实现 | 夸大团队规模 |
| 负责一个完整模块 | 负责、实现、构建、优化 | 主导全项目 |
| 协作完成 | 参与设计、协同实现 | 独立完成 |
| 学习/复刻项目 | 搭建、复现、实践 | 上线、主导生产系统 |

## 4. 好 bullet 的结构

```text
设计/实现 [具体能力]，通过 [关键技术与边界]，解决 [问题]，并以 [证据] 验证。
```

示例：

> 设计统一 Tool Gateway，在 handler 执行前完成 RBAC 与审批门控，并将成功、拒绝和异常归一化审计，避免模型绕过业务安全边界。

## 5. 可量化但不虚构

可直接重算：测试文件数、测试函数数、TaskType 数、Domain Skill 数、策略工具数、API/页面数、规格任务数。

必须由用户提供或实际跑测：准确率、延迟、QPS、并发、线上用户数、业务金额、节省工时、测试通过率。

## 6. ATS 关键词

按目标岗位选择，不要全堆：

- Agent：LangGraph, ReAct, Tool Calling, MCP, Agent State, Human-in-the-loop
- Backend：FastAPI, SQLAlchemy Async, Alembic, RBAC, Audit, SSE, AsyncIO
- LLM App：Model Gateway, OpenAI-compatible API, Function Calling, RAG, Citation, Context Management
- Platform：Policy as Configuration, Provider Routing, Observability, Graceful Degradation, Dependency Injection
- Quality：pytest, Unit/Integration/E2E, Hermetic Test, Scripted Model, Regression Eval
- Frontend：Next.js, React, TypeScript, SSE, Approval Console, Audit Trace

## 7. 反模式

- “负责大模型相关工作”——没有对象和结果。
- “实现 RRF/Hybrid Search”——若只在本仓库工作，这属于外部 RAG Server。
- “支持 OpenAI/Anthropic/本地模型”——忽略实际未实现或 disabled。
- “实现生产自动提交”——忽略默认 fake guard 和禁用策略。
- “测试覆盖 100%”——没有 coverage 命令和结果。
- “系统上线后提升 X%”——没有 baseline 和证据。
