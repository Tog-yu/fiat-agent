## 9. 测试方案

### 9.1 测试分层

| 层级 | 目标 | 示例 |
|---|---|---|
| Unit | 单模块逻辑 | settings、policy、tool schema |
| Integration | 模块协作 | MCP RAG Client、Session Store、Tool Gateway |
| E2E | 完整业务链路 | RAG 问答、告警诊断、审批流 |

### 9.2 测试原则

1. LLM 调用默认 mock。
2. MCP Server 可用子进程做集成测试。
3. 生产写操作必须使用 fake backend。
4. 权限、审批、审计必须覆盖拒绝路径。
5. Agent 输出使用结构化 schema 做断言。
