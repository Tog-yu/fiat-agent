# fiat-agent

法币业务内部使用的定制 Agent 系统。独立业务 Agent 项目（非 Claude Code 插件、非 Pi Agent 插件）。
参考 Pi Agent 架构，使用 `MODULAR-RAG-MCP-SERVER` 作为 RAG MCP Server。

## 阶段进度

当前已完成 **阶段 A1：工程骨架与配置基座（项目初始化）**。

| 阶段 | 状态 |
|---|---|
| A 工程骨架与配置基座 | A1 ✅ / A2–A5 ⏳ |
| B–K | 待开始 |

## 目录结构（节选自 DEV_SPEC 第 5 节）

```text
fiat-agent/
  apps/            # 入口适配器：api / cli / lark_bot / web_console
  fiat_agent/      # 核心包：orchestrator / models / context / sessions / events
                   #         tools / tool_gateway / mcp_clients / rag / workflows
                   #         users / auth / approvals / audit / skills / schemas
  config/          # settings.yaml / model_policies.yaml / tool_policies.yaml / prompts/
  migrations/      # Alembic 迁移（阶段 B 起）
  tests/           # unit / integration / e2e / fixtures
  docs/            # 架构、权限模型、会话记忆、工具契约、工作流设计
  .github/skills/  # 开发期 agent skills（已从 MODULAR-RAG-MCP-SERVER 迁移 skill-creator）
  pyproject.toml
```

## 快速开始

```bash
# 目录结构与规范一致
python -m compileall fiat_agent apps

# CLI 入口（A1 占位骨架）
python -m apps.cli.main --help

# 冒烟测试
pytest -q tests/unit/test_smoke_imports.py
```

## 设计原则（摘要，详见 DEV_SPEC）

1. Agent 与业务执行隔离：生产写操作必须经受控后端 API、审批流、审计。
2. 确定性规则优先：权限、审批、金额计算、状态机、字段校验、审计不走 LLM。
3. 参考 Pi Agent 结构但不照搬：LangGraph 承载 Agent Loop；当前以 **SQLite** 承载结构化存储（用户/角色/权限/审计/审批），**PostgreSQL 作为扩展点**后续启用，承载高并发 session event store。
4. RAG 通过 MCP 接入：只实现 MCP Client / 适配 / 权限过滤 / 结果解析 / 上下文合并 / 审计。

## 模型与 RAG

- 模型接入：OpenAI / Anthropic / Gemini / 内部私有模型 SDK（阶段 D）。
- RAG：`MODULAR-RAG-MCP-SERVER`（MCP stdio），暴露 `query_knowledge_hub` / `list_collections` / `get_document_summary`。
