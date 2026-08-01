## 4. 系统架构

```text
用户 / 运营 / 测试 / 值班 / 告警平台
        ↓
Entry Adapters
CLI / FastAPI / Lark Bot / Web Console / MCP Adapter / Pi Extension
        ↓
Auth Context Loader
用户身份 / 角色 / 环境 / 数据范围 / 工具权限
        ↓
Agent Orchestrator
LangGraph Supervisor / Task Graph / Planning / Tool Routing
        ↓
Context Builder
System Prompt / Domain Skill / Memory / MCP RAG / Tool Schema
        ↓
Model Gateway
模型路由 / Function Call / Structured Output / Fallback / 成本统计
        ↓
Tool Gateway
MCP RAG Client / ES / DB / Lark / Test API / Cashback / Logistics
        ↓
Workflow Engine
告警诊断 / 测试账号 / 返现对账 / 物流校验 / 审批等待
        ↓
Session Memory Store
PostgreSQL append-only events / parent_event_id / checkpoint / compaction
        ↓
Approval / Audit / Event Bus
审批 / 审计 / SSE / WebSocket / Lark 通知
```
