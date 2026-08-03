# 法币定制 Agent Developer Specification (DEV_SPEC)

## 目录

1. 项目概述
2. 设计原则
3. 技术选型
4. 系统架构
5. 目录结构
6. 模块说明
7. 数据流说明
8. 配置设计
9. 测试方案
10. 项目排期
11. 分阶段任务清单
12. 交付里程碑
13. 后续扩展

## 1. 项目概述

`fiat-agent` 是面向法币业务内部使用的定制 Agent 系统。

它不是 Claude Code 插件，也不是 Pi Agent 的业务插件，而是一个独立业务 Agent 项目。Pi Agent 用作架构参考，已有 `MODULAR-RAG-MCP-SERVER` 用作 RAG MCP Server。

核心目标：

1. 支持法币业务 RAG 问答。
2. 支持告警日志诊断和 Lark 通知。
3. 支持测试环境自动化助手。
4. 支持返现记录导入、对账和 dry-run。
5. 支持卡片物流状态导入、校验和 dry-run。
6. 支持用户管理、权限控制、审批、审计。
7. 支持会话回退、分支、压缩和长短期记忆。

## 2. 设计原则

### 2.1 Agent 与业务执行隔离

LLM 负责理解意图、规划、调用工具和生成解释。生产写操作必须由受控后端 API、审批流和审计系统执行。

禁止：

1. LLM 直接执行生产 SQL。
2. LLM 直接修改生产数据。
3. LLM 自主绕过审批。
4. Prompt 作为唯一权限边界。

### 2.2 确定性规则优先

以下能力必须由确定性模块实现：

1. 权限判断。
2. 审批状态流转。
3. 返现金额计算。
4. 物流状态机。
5. 表格字段校验。
6. 生产任务提交。
7. 审计日志写入。

### 2.3 参考 Pi Agent，但不照搬

参考 Pi Agent 的结构：

1. 单入口。
2. Agent Loop。
3. Context 组装。
4. Compaction。
5. Model Provider 抽象。
6. Tool Loop。
7. Append-only Session。
8. Event Stream。

法币 Agent 的实现：

1. `LangGraph` 承载 Agent Loop 和 workflow graph。
2. `PostgreSQL` 承载业务级 session event store（**可选扩展点**：当前默认 SQLite，见 §13 约定）。
3. `MODULAR-RAG-MCP-SERVER` 承载 RAG。
4. `Tool Gateway` 承载所有外部系统访问。
5. `Auth / Approval / Audit` 承载安全边界。

### 2.4 RAG 通过 MCP 接入

RAG 不在 `fiat-agent` 中重复实现。已有项目：

```text
/Users/tog/Desktop/project/MODULAR-RAG-MCP-SERVER
```

通过 MCP Server 暴露：

1. `query_knowledge_hub`
2. `list_collections`
3. `get_document_summary`

`fiat-agent` 只实现 MCP Client、工具适配、权限过滤、结果解析、上下文合并和审计记录。

## 3. 技术选型

版本核对日期：2026-08-02。

版本原则：

1. 新项目默认使用当前最新稳定版。
2. 不使用 beta、rc、preview 作为生产基线。
3. 最新主版本发布过近、或会破坏现有 `MODULAR-RAG-MCP-SERVER` 集成时，固定在最新兼容稳定线，并写明原因。
4. `pyproject.toml`、`uv.lock`、`package.json`、`package-lock.json` 必须与本节保持一致；上线构建使用 lockfile 固定 transitive dependencies。

### 3.1 后端主栈

| 组件 | 目标版本 | 是否使用目前最新版本 | 判断 |
|---|---:|---|---|
| Python | `3.14.6` | 是 | `3.15` 仍是 pre-release，不能作为生产基线；`3.14` 是当前 bugfix 稳定线，并且核心依赖已声明或发布 Python 3.14 兼容包。 |
| FastAPI | `0.141.1` | 是 | 当前稳定版，支持 Python 3.14；API 服务直接采用 `fastapi==0.141.1`。 |
| Uvicorn | `0.52.1` | 是 | 当前稳定版，作为 FastAPI 的 ASGI server；生产入口显式依赖 `uvicorn[standard]`。 |
| LangGraph | `1.2.10` | 是 | 当前稳定版，适合作为 Agent Loop 和 workflow graph 的核心。 |
| LangChain | `1.3.14` | 是 | 当前稳定版，用于 provider/tool/schema 生态集成；业务逻辑不绑定 LangChain agent runtime。 |
| MCP Python SDK | `mcp==1.28.1` | 否 | `mcp` 最新为 `2.0.0`，但 2026-07-28 刚发布且是 breaking major；现有 `MODULAR-RAG-MCP-SERVER` 使用 `mcp.server.lowlevel.Server` 和 v1 风格 API。MVP 固定最新 v1 线，待 RAG Server 完成 v2 迁移后再升级。 |
| Pydantic | `2.13.4` | 是 | 当前稳定版，支持 Python 3.14；全局 schema、settings 校验和工具输入输出统一使用 Pydantic v2。 |
| Pydantic Settings | `2.14.2` | 是 | 当前稳定版，用于 YAML/env settings 载入和 fail-fast 校验。 |
| SQLAlchemy | `2.0.51` | 是 | 当前稳定版，保留 SQLAlchemy 2.0 async ORM/Core 模式。 |
| Alembic | `1.18.5` | 是 | 当前稳定版，与 SQLAlchemy 2.0 线配套。 |
| PostgreSQL | `18.4` | 可选（扩展点） | `19` 仍是 beta；业务 session event store 的扩展目标，当前主线用 SQLite，启用前需先确认（见 §13 约定）。 |
| asyncpg | `0.31.0` | 可选（扩展点） | PostgreSQL async driver，配合 `postgresql+asyncpg://` URL；置于可选依赖 `[postgres]`。 |
| Redis Server | `8.8.0` | 是 | 当前 GA 稳定线；`8.10-rc*` 不用于生产基线。 |
| redis-py | `8.1.0` | 是 | 当前稳定 Python client；新代码显式设置 `legacy_responses=False`，减少 RESP2/RESP3 差异。 |
| Celery | `5.6.3` | 是 | MVP 默认后台任务框架，部署和心智成本低，适合通知、审计异步写、轻量任务。 |
| Temporal Python SDK | `temporalio==1.31.0` | 是，但不进入 MVP 默认依赖 | 适合长流程、人工审批等待和可恢复 workflow；需要额外 Temporal Server 运维，第二阶段或长任务复杂度上来后启用。 |

MVP 后端依赖基线：

```toml
requires-python = "==3.14.*"

dependencies = [
  "fastapi==0.141.1",
  "uvicorn[standard]==0.52.1",
  "langgraph==1.2.10",
  "langchain==1.3.14",
  "mcp==1.28.1",
  "pydantic==2.13.4",
  "pydantic-settings==2.14.2",
  "SQLAlchemy==2.0.51",
  "alembic==1.18.5",
  "asyncpg==0.31.0",
  "redis==8.1.0",
  "celery==5.6.3",
]
```

非 MVP 可选依赖：

```toml
workflow = [
  "temporalio==1.31.0",
]
```

### 3.2 前端

| 组件 | 目标版本 | 是否使用目前最新版本 | 判断 |
|---|---:|---|---|
| Node.js | `24.18.1` LTS | 否 | 当前最新 release 是 `26.5.1`，但不是 LTS，不适合作为生产基线；Next.js 16 要求 Node `>=20.9.0`，Node 24 LTS 更稳。 |
| Next.js | `16.2.12` | 是 | 当前稳定版；用于 Web Console 的 App Router、server actions/API client 和前端构建。 |
| React | `19.2.8` | 是 | 当前稳定版，满足 Next.js 16 peer dependency。 |
| React DOM | `19.2.8` | 是 | 与 React 主版本完全对齐。 |
| TypeScript | `7.0.2` | 是 | 当前 stable/latest tag；Web Console 统一开启 strict mode。 |

MVP 前端依赖基线：

```json
{
  "engines": {
    "node": "24.18.1"
  },
  "dependencies": {
    "next": "16.2.12",
    "react": "19.2.8",
    "react-dom": "19.2.8"
  },
  "devDependencies": {
    "typescript": "7.0.2"
  }
}
```

实时事件优先使用 `SSE`。只有需要双向低延迟协作编辑、终端类交互或多路复用时，再增加 `WebSocket`。

第一阶段前端可以延后，优先做 CLI、FastAPI 和 Lark Bot。

### 3.3 RAG

| 组件 | 目标版本 | 是否使用目前最新版本 | 判断 |
|---|---:|---|---|
| `MODULAR-RAG-MCP-SERVER` | 使用现有项目 lockfile / `pyproject.toml` | 不在本项目强行升级 | RAG Server 是独立项目；`fiat-agent` 只通过 MCP 工具协议接入，避免在本项目里重复锁定其内部实现。 |
| MCP transport | `stdio` | 是 | 本地开发、子进程集成测试和 Claude Code 适配最简单稳定。 |
| ChromaDB | `1.5.9` | 是，仅用于本项目测试 fixture 或本地模拟 | 生产 RAG 存储由 `MODULAR-RAG-MCP-SERVER` 管理；`fiat-agent` 不直接访问 ChromaDB。 |
| BM25 + Dense Retrieval + RRF + Rerank | 算法契约，无独立版本 | 不适用 | 算法实现归属 RAG Server；本项目只消费 `query_knowledge_hub`、`list_collections`、`get_document_summary` 的 MCP 返回。 |

### 3.4 模型接入

| 组件 | 目标版本 | 是否使用目前最新版本 | 判断 |
|---|---:|---|---|
| OpenAI Python SDK | `openai==2.52.0` | 是 | 当前稳定版，支持 Python 3.14；默认走 `Responses API`，保留 OpenAI-compatible base URL 能力。 |
| Anthropic Python SDK | `anthropic==0.120.2` | 是 | 当前稳定版；作为可选 provider 插件接入。 |
| Google Gemini SDK | `google-genai==2.16.0` | 是 | 当前稳定版；作为可选 provider 插件接入。 |
| 内部私有模型 SDK | 按内部制品仓库版本固定 | 不适用 | 内部 SDK 不跟公共包源；接入时必须在 `model_policies.yaml` 写明 provider、版本、owner、回滚方式。 |
| 本地模型 | 可选，不进入 MVP 默认依赖 | 不适用 | 仅做开发/降级实验；不得影响生产 provider 路由。 |

模型 ID 不是框架版本。`gpt-*`、`claude-*`、`gemini-*` 等模型名由 `config/model_policies.yaml` 管理，每次升级必须单独评估准确率、成本、延迟和合规要求。

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
PostgreSQL append-only events / parent_event_id / checkpoint / compaction（可选扩展点，当前主线用 SQLite）
        ↓
Approval / Audit / Event Bus
审批 / 审计 / SSE / WebSocket / Lark 通知
```

## 5. 目录结构

```text
fiat-agent/
  apps/
    api/
      main.py
      routes/
      dependencies.py
    cli/
      main.py
    lark_bot/
      app.py
      handlers.py
    web_console/
      package.json
      src/
  fiat_agent/
    orchestrator/
      graph.py
      state.py
      nodes/
      supervisor.py
    models/
      base.py
      gateway.py
      providers/
      policies.py
    context/
      builder.py
      compaction.py
      prompts.py
    sessions/
      store.py
      branches.py
      checkpoints.py
      jsonl_exporter.py
    events/
      bus.py
      types.py
      stream.py
    tools/
      registry.py
      schemas.py
      function_calling.py
    tool_gateway/
      gateway.py
      db_tools.py
      es_tools.py
      lark_tools.py
      test_env_tools.py
      cashback_tools.py
      logistics_tools.py
    mcp_clients/
      rag_mcp_client.py
      tool_registry.py
      content_parser.py
    rag/
      context_merge.py
      citations.py
    workflows/
      alert_diagnosis.py
      test_automation.py
      cashback_reconcile.py
      logistics_validation.py
    users/
      models.py
      service.py
      repository.py
    auth/
      policy.py
      rbac.py
      scopes.py
    approvals/
      service.py
      policies.py
    audit/
      service.py
      repository.py
    skills/
      rag_qa/
      alert_diagnosis/
      test_automation/
      cashback_reconcile/
      logistics_validation/
    schemas/
      common.py
      agent.py
      tools.py
      workflows.py
  migrations/
  config/
    settings.yaml
    model_policies.yaml
    tool_policies.yaml
    prompts/
  tests/
    unit/
    integration/
    e2e/
    fixtures/
  docs/
    architecture.md
    permission-model.md
    session-memory-design.md
    tool-contracts.md
    workflow-design.md
  pyproject.toml
  README.md
```

## 6. 模块说明

### 6.1 Entry Adapters

| 模块 | 职责 | 关键点 |
|---|---|---|
| `apps/api` | FastAPI 主服务 | REST API、SSE、鉴权依赖 |
| `apps/cli` | `fiat-agent` 命令 | chat、once、server 模式 |
| `apps/lark_bot` | Lark Bot 入口 | 告警通知、审批卡片、问答 |
| `apps/web_console` | React Web Console | 会话、任务、审批、审计 |
| `adapters/pi_extension` | Pi 可选入口 | 调用 fiat-agent API |
| `adapters/claude_code_mcp` | Claude Code 可选入口 | 将 fiat-agent 暴露为 MCP Server |

### 6.2 Agent Orchestrator

| 模块 | 职责 | 关键点 |
|---|---|---|
| `graph.py` | 构建 LangGraph | 节点、边、条件路由 |
| `state.py` | AgentState 定义 | task、messages、memory、tool results |
| `supervisor.py` | 任务分类和调度 | 单 agent / 多 agent 选择 |
| `nodes/*` | Graph 节点 | plan、tool、approval、final |

### 6.3 Model Gateway

| 模块 | 职责 | 关键点 |
|---|---|---|
| `base.py` | 统一模型接口 | chat、stream、function_call |
| `gateway.py` | 模型路由 | 按任务类型选择模型 |
| `providers/*` | Provider 实现 | OpenAI、Anthropic、私有模型 |
| `policies.py` | 模型策略 | token 预算、fallback、成本统计 |

### 6.4 Function Calling / Tool Calling

| 模块 | 职责 | 关键点 |
|---|---|---|
| `tools/registry.py` | 工具注册中心 | 业务工具 + MCP 工具 |
| `tools/schemas.py` | 工具 schema | Pydantic 输入输出 |
| `tools/function_calling.py` | Function Call 适配 | 模型工具描述、结果回灌 |
| `tool_gateway/gateway.py` | 工具执行入口 | 权限、dry-run、审批、审计 |

### 6.5 MCP RAG Client

| 模块 | 职责 | 关键点 |
|---|---|---|
| `rag_mcp_client.py` | MCP Client | stdio、initialize、tools/list、tools/call |
| `tool_registry.py` | MCP 工具同步 | 转换为 `mcp_rag.*` 工具 |
| `content_parser.py` | MCP 内容解析 | TextContent、ImageContent、citations |
| `rag/context_merge.py` | 合并上下文 | RAG 结果进入 Agent Context |
| `rag/citations.py` | 引用整理 | source、chunk、collection |

### 6.6 Session Memory Store

| 模块 | 职责 | 关键点 |
|---|---|---|
| `sessions/store.py` | 会话事件存储 | PostgreSQL append-only |
| `sessions/branches.py` | 回退和分支 | parent_event_id、active_event_id |
| `sessions/checkpoints.py` | LangGraph checkpoint | 长任务恢复 |
| `sessions/jsonl_exporter.py` | JSONL 导出 | 调试、回放、评测 |
| `context/compaction.py` | 压缩摘要 | compaction_summary event |

### 6.7 User / Auth / Approval / Audit

| 模块 | 职责 | 关键点 |
|---|---|---|
| `users/*` | 用户管理 | User、Role、UserRole |
| `auth/policy.py` | 权限判断 | can_execute |
| `auth/rbac.py` | RBAC | 角色、权限、工具策略 |
| `auth/scopes.py` | 数据范围 | collection、业务域、环境 |
| `approvals/*` | 审批流 | waiting、approved、rejected |
| `audit/*` | 审计 | 工具、审批、生产操作记录 |

### 6.8 Workflows

| 模块 | 职责 | 关键点 |
|---|---|---|
| `alert_diagnosis.py` | 告警诊断 | ES、DB、RAG、Lark |
| `test_automation.py` | 测试环境助手 | 账号、充值、KYC |
| `cashback_reconcile.py` | 返现对账 | 表格解析、金额校验、dry-run |
| `logistics_validation.py` | 物流校验 | 状态机、地址、单号校验 |

## 7. 数据流说明

### 7.1 一轮 Agent Loop

```text
接收用户输入
  ↓
加载用户身份和权限上下文
  ↓
创建或恢复 task_session
  ↓
Context Builder 组装上下文
  ↓
检查 token 预算，必要时 compaction
  ↓
Model Gateway 调用 LLM
  ↓
LLM 产生自然语言或 function call
  ↓
Tool Gateway 校验权限并执行工具
  ↓
工具结果回灌给 LLM
  ↓
生成最终答复或进入审批等待
  ↓
写 session event、tool call、audit log
  ↓
Event Bus 推送给 CLI / Web / Lark
```

### 7.2 MCP RAG 查询流

```text
Agent 判断需要业务知识
  ↓
Tool Gateway 选择 mcp_rag.query_knowledge_hub
  ↓
权限过滤 collection
  ↓
RagMcpClient tools/call
  ↓
MODULAR-RAG-MCP-SERVER 执行 hybrid search + rerank
  ↓
返回 MCP TextContent / ImageContent
  ↓
content_parser 解析文本、图片、引用
  ↓
context_merge 注入当前上下文
  ↓
tool_calls 和 audit_logs 记录查询
```

### 7.3 会话回退流

```text
用户选择历史 event
  ↓
SessionStore 校验 event 归属
  ↓
创建 branch
  ↓
更新 active_event_id
  ↓
后续消息挂到新的 parent_event_id
```

## 8. 配置设计

```yaml
app:
  name: fiat-agent
  environment: dev

database:
  # 当前默认 SQLite（低成本）；PostgreSQL 为可选扩展点，设 FIAT_DB_URL 切换。
  url: ${FIAT_DB_URL:-sqlite+aiosqlite:///./data/fiat_agent.db}

redis:
  url: redis://localhost:6379/0

models:
  default: gpt-4.1-mini
  providers:
    openai:
      api_key_env: OPENAI_API_KEY
    anthropic:
      api_key_env: ANTHROPIC_API_KEY

model_policies:
  rag_qa:
    model: gpt-4.1-mini
  alert_diagnosis:
    model: gpt-4.1
  table_parse:
    model: gpt-4.1

mcp_servers:
  rag:
    name: modular-rag-mcp-server
    transport: stdio
    cwd: /Users/tog/Desktop/project/MODULAR-RAG-MCP-SERVER
    command: python
    args:
      - -m
      - src.mcp_server.server

session:
  max_context_tokens: 80000
  compact_threshold_ratio: 0.75
  jsonl_export_enabled: true

tools:
  default_timeout_seconds: 30
  production_write_requires_approval: true

event_stream:
  transport: sse
```

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

## 10. 项目排期

### 阶段总览

1. 阶段 A：工程骨架与配置基座。
2. 阶段 B：数据库、用户、权限和审计基础。
3. 阶段 C：Session Memory、回退、压缩和 JSONL 导出。
4. 阶段 D：Model Gateway 与 Function Calling。
5. 阶段 E：MCP RAG Client 接入。
6. 阶段 F：Tool Gateway 与业务工具契约。
7. 阶段 G：LangGraph Agent Orchestrator。
8. 阶段 H：业务 Workflows。
9. 阶段 I：Entry Adapters。
10. 阶段 J：React Web Console。
11. 阶段 K：Observability、Evaluation 和 E2E 收口。

### 进度跟踪表

| 阶段 | 任务数 | 状态 |
|---|---:|---|
| 阶段 A | 5 | [x] |
| 阶段 B | 7 | [x] |
| 阶段 C | 7 | [x] |
| 阶段 D | 6 | [x] |
| 阶段 E | 6 | [x] |
| 阶段 F | 7 | [~] |
| 阶段 G | 8 | [ ] |
| 阶段 H | 8 | [ ] |
| 阶段 I | 5 | [ ] |
| 阶段 J | 6 | [ ] |
| 阶段 K | 6 | [ ] |
| 总计 | 71 | [ ] |

## 11. 分阶段任务清单

## 阶段 A：工程骨架与配置基座

### [x] A1：初始化项目结构

- **目标**：创建 `fiat-agent` Python 项目骨架。
- **修改文件**：
  - `pyproject.toml`
  - `README.md`
  - `.gitignore`
  - `fiat_agent/**/__init__.py`
  - `apps/api/main.py`
  - `apps/cli/main.py`
- **实现类/函数**：无，仅骨架和最小启动入口。
- **验收标准**：
  - 目录结构与第 5 节一致。
  - `python -m compileall fiat_agent apps` 通过。
  - `python -m apps.cli.main --help` 可运行。
- **测试方法**：`pytest -q tests/unit/test_smoke_imports.py`。

### [x] A2：测试基座

- **目标**：建立 pytest、fixtures、markers。
- **修改文件**：
  - `pyproject.toml`
  - `tests/unit/test_smoke_imports.py`
  - `tests/conftest.py`
- **验收标准**：
  - `pytest -q` 可运行。
  - 单元测试、集成测试、E2E markers 可用。
- **测试方法**：`pytest -q tests/unit/test_smoke_imports.py`。

### [x] A3：Settings 配置加载

- **目标**：实现 YAML 配置加载和 fail-fast 校验。
- **修改文件**：
  - `fiat_agent/schemas/common.py`
  - `fiat_agent/config.py`
  - `config/settings.yaml`
  - `tests/unit/test_config_loading.py`
- **实现类/函数**：
  - `Settings`
  - `load_settings(path: str | None) -> Settings`
  - `validate_settings(settings: Settings) -> None`
- **验收标准**：
  - 缺少 `database.url`、`models.default`、`mcp_servers.rag` 时抛出可读错误。
  - 环境变量引用可解析。
- **测试方法**：`pytest -q tests/unit/test_config_loading.py`。

### [x] A4：日志和错误模型

- **目标**：统一结构化日志和业务错误类型。
- **修改文件**：
  - `fiat_agent/errors.py`
  - `fiat_agent/logging.py`
  - `tests/unit/test_errors.py`
- **实现类/函数**：
  - `FiatAgentError`
  - `PermissionDeniedError`
  - `ToolExecutionError`
  - `ApprovalRequiredError`
  - `get_logger()`
- **验收标准**：
  - 错误包含 code、message、metadata。
  - 日志不输出敏感字段。
- **测试方法**：`pytest -q tests/unit/test_errors.py`。

### [x] A5：基础数据契约

- **目标**：定义全局通用 schema。
- **修改文件**：
  - `fiat_agent/schemas/common.py`
  - `fiat_agent/schemas/agent.py`
  - `tests/unit/test_common_schemas.py`
- **实现类/函数**：
  - `Environment`
  - `RiskLevel`
  - `TaskType`
  - `ActorContext`
  - `ToolResult`
- **验收标准**：
  - schema 可 JSON 序列化。
  - 枚举值稳定。
- **测试方法**：`pytest -q tests/unit/test_common_schemas.py`。

## 阶段 B：数据库、用户、权限和审计基础

### [x] B1：数据库连接与 migration

- **目标**：接入数据库（Alembic migration + SQLAlchemy 2.0 async）。当前默认 SQLite（低成本）；PostgreSQL 为可选扩展点，按 §13 约定实现前需确认。
- **修改文件**：
  - `fiat_agent/db.py`
  - `migrations/env.py`
  - `tests/integration/test_db_connection.py`
- **实现类/函数**：
  - `get_async_engine(settings)`
  - `get_session()`
- **验收标准**：
  - migration 可创建空库表结构。
  - 测试使用临时数据库或测试 schema。
- **测试方法**：`pytest -q tests/integration/test_db_connection.py`。

### [x] B2：用户与角色模型

- **目标**：实现用户、角色、用户角色关系。
- **修改文件**：
  - `fiat_agent/users/models.py`
  - `fiat_agent/users/repository.py`
  - `tests/unit/test_user_models.py`
- **实现类/函数**：
  - `User`
  - `Role`
  - `UserRole`
  - `UserRepository`
- **验收标准**：
  - 用户可启用/禁用。
  - 一个用户可绑定多个角色。
- **测试方法**：`pytest -q tests/unit/test_user_models.py`。

### [x] B3：权限与数据范围模型

- **目标**：实现工具权限、业务域、环境、collection 范围。
- **修改文件**：
  - `fiat_agent/auth/rbac.py`
  - `fiat_agent/auth/scopes.py`
  - `config/tool_policies.yaml`
  - `tests/unit/test_rbac_policy.py`
- **实现类/函数**：
  - `Permission`
  - `ToolPolicy`
  - `DataScope`
  - `EnvironmentScope`
- **验收标准**：
  - `ops` 可调用返现 dry-run，但不能提交生产执行。
  - `oncall` 可查 ES/DB 只读和 RAG。
  - collection 范围可按角色过滤。
- **测试方法**：`pytest -q tests/unit/test_rbac_policy.py`。

### [x] B4：权限校验服务

- **目标**：实现确定性 `can_execute`。
- **修改文件**：
  - `fiat_agent/auth/policy.py`
  - `tests/unit/test_auth_policy.py`
- **实现类/函数**：
  - `can_execute(actor, tool_name, environment, resource, action) -> PolicyDecision`
  - `filter_tools(actor, tools, environment) -> list[ToolDefinition]`
- **验收标准**：
  - 拒绝结果包含原因。
  - 权限校验不依赖 LLM。
  - 高风险工具返回 approval_required。
- **测试方法**：`pytest -q tests/unit/test_auth_policy.py`。

### [x] B5：审计服务

- **目标**：实现审计日志写入。
- **修改文件**：
  - `fiat_agent/audit/service.py`
  - `fiat_agent/audit/repository.py`
  - `tests/unit/test_audit_service.py`
- **实现类/函数**：
  - `AuditService.record_event()`
  - `AuditService.record_tool_call()`
  - `AuditService.record_policy_decision()`
- **验收标准**：
  - 工具调用、权限拒绝、审批结果均可审计。
  - 敏感字段可脱敏。
- **测试方法**：`pytest -q tests/unit/test_audit_service.py`。

### [x] B6：审批模型

- **目标**：实现审批单和审批策略。
- **修改文件**：
  - `fiat_agent/approvals/service.py`
  - `fiat_agent/approvals/policies.py`
  - `tests/unit/test_approval_service.py`
- **实现类/函数**：
  - `Approval`
  - `ApprovalService.request()`
  - `ApprovalService.approve()`
  - `ApprovalService.reject()`
- **验收标准**：
  - 一个审批只能审批一次。
  - 审批通过后参数摘要不可变。
  - L5 支持双人审批策略占位。
- **测试方法**：`pytest -q tests/unit/test_approval_service.py`。

### [x] B7：用户和权限 API

- **目标**：暴露用户、角色、权限查询 API。
- **修改文件**：
  - `apps/api/routes/users.py`
  - `apps/api/routes/auth.py`
  - `tests/integration/test_user_auth_api.py`
- **验收标准**：
  - `GET /api/users/me` 返回当前用户和角色。
  - `POST /api/auth/check` 返回权限决策。
- **测试方法**：`pytest -q tests/integration/test_user_auth_api.py`。

## 阶段 C：Session Memory、回退、压缩和 JSONL 导出

### [x] C1：Session 表结构

- **目标**：实现 session 相关表。
- **修改文件**：
  - `fiat_agent/sessions/store.py`
  - `migrations/*_create_sessions.py`
  - `tests/unit/test_session_models.py`
- **实现表**：
  - `task_sessions`
  - `task_session_events`
  - `task_artifacts`
  - `tool_calls`
  - `session_branches`
- **验收标准**：
  - 事件表支持 `parent_event_id`。
  - session 支持 `active_event_id`。
- **测试方法**：`pytest -q tests/unit/test_session_models.py`。

### [x] C2：Append-only Session Store

- **目标**：实现只追加会话写入。
- **修改文件**：
  - `fiat_agent/sessions/store.py`
  - `tests/integration/test_session_store.py`
- **实现类/函数**：
  - `create_session()`
  - `append_event()`
  - `get_event_path(active_event_id)`
  - `list_session_events()`
- **验收标准**：
  - 不允许更新历史 event content。
  - 路径回溯顺序稳定。
- **测试方法**：`pytest -q tests/integration/test_session_store.py`。

### [x] C3：回退和分支

- **目标**：实现 Pi-style 会话树。
- **修改文件**：
  - `fiat_agent/sessions/branches.py`
  - `tests/integration/test_session_branching.py`
- **实现类/函数**：
  - `rollback_to_event(session_id, event_id)`
  - `create_branch(session_id, base_event_id)`
  - `get_active_branch(session_id)`
- **验收标准**：
  - 回退不删除历史。
  - 回退后新消息形成新分支。
  - 生产操作不会因会话回退自动撤销。
- **测试方法**：`pytest -q tests/integration/test_session_branching.py`。

### [x] C4：LangGraph checkpoint

- **目标**：实现 graph 状态恢复。
- **修改文件**：
  - `fiat_agent/sessions/checkpoints.py`
  - `tests/integration/test_graph_checkpoint.py`
- **实现类/函数**：
  - `CheckpointStore`
  - `save_checkpoint()`
  - `load_checkpoint()`
- **验收标准**：
  - 中断任务可从 checkpoint 恢复。
  - checkpoint 与 session_id 绑定。
- **测试方法**：`pytest -q tests/integration/test_graph_checkpoint.py`。

### [x] C5：Context Compaction

- **目标**：实现上下文压缩节点。
- **修改文件**：
  - `fiat_agent/context/compaction.py`
  - `config/prompts/compaction.txt`
  - `tests/unit/test_compaction.py`
- **实现类/函数**：
  - `should_compact(context, token_budget) -> bool`
  - `compact_events(events) -> CompactionSummary`
  - `append_compaction_event()`
- **验收标准**：
  - 摘要包含用户目标、工具结果、引用、审批状态、风险状态、下一步。
  - 原始事件不删除。
- **测试方法**：`pytest -q tests/unit/test_compaction.py`。

### [x] C6：短期记忆和长期记忆注入

- **目标**：实现 Memory Resolver。
- **修改文件**：
  - `fiat_agent/context/builder.py`
  - `fiat_agent/context/memory.py`
  - `tests/unit/test_memory_resolver.py`
- **实现类/函数**：
  - `load_short_term_memory(session_id)`
  - `load_long_term_memory(actor, task_type)`
  - `build_memory_context()`
- **验收标准**：
  - 短期记忆来自 session path 和 checkpoint。
  - 长期记忆通过 RAG、用户权限、历史任务按需注入。
- **测试方法**：`pytest -q tests/unit/test_memory_resolver.py`。

### [x] C7：JSONL 导出

- **目标**：支持导出会话为 JSONL。
- **修改文件**：
  - `fiat_agent/sessions/jsonl_exporter.py`
  - `tests/unit/test_jsonl_exporter.py`
- **实现类/函数**：
  - `export_session_jsonl(session_id) -> Iterator[str]`
- **验收标准**：
  - 导出顺序与 active branch 一致。
  - 每行是合法 JSON。
  - 包含 message、tool_call、compaction、approval 事件。
- **测试方法**：`pytest -q tests/unit/test_jsonl_exporter.py`。

## 阶段 D：Model Gateway 与 Function Calling

### [x] D1：模型接口

- **目标**：定义统一 LLM 接口。
- **修改文件**：
  - `fiat_agent/models/base.py`
  - `tests/unit/test_model_base.py`
- **实现类/函数**：
  - `BaseChatModel`
  - `ChatRequest`
  - `ChatResponse`
  - `FunctionCall`
- **验收标准**：
  - 支持普通文本、流式输出、function call。
  - response 包含 token usage。
- **测试方法**：`pytest -q tests/unit/test_model_base.py`。

### [x] D2：Provider 实现

- **目标**：接入 OpenAI-compatible provider。
- **修改文件**：
  - `fiat_agent/models/providers/openai.py`
  - `tests/unit/test_openai_provider.py`
- **验收标准**：
  - 单元测试 mock HTTP。
  - 不泄露 API key。
- **测试方法**：`pytest -q tests/unit/test_openai_provider.py`。

### [x] D3：模型路由策略

- **目标**：按任务类型选择模型。
- **修改文件**：
  - `fiat_agent/models/gateway.py`
  - `fiat_agent/models/policies.py`
  - `config/model_policies.yaml`
  - `tests/unit/test_model_routing.py`
- **验收标准**：
  - `rag_qa` 可走轻量模型。
  - `alert_diagnosis` 可走强推理模型。
  - fallback 可配置。
- **测试方法**：`pytest -q tests/unit/test_model_routing.py`。

### [x] D4：Function Call schema 生成

- **目标**：把工具定义转换成模型可用 function schema。
- **修改文件**：
  - `fiat_agent/tools/function_calling.py`
  - `tests/unit/test_function_schema.py`
- **实现类/函数**：
  - `to_openai_tool_schema(tool_definition)`
  - `to_anthropic_tool_schema(tool_definition)`
- **验收标准**：
  - Pydantic schema 可转换。
  - MCP tools/list schema 可转换。
- **测试方法**：`pytest -q tests/unit/test_function_schema.py`。

### [x] D5：Function Call 结果回灌

- **目标**：实现工具结果转换为模型消息。
- **修改文件**：
  - `fiat_agent/tools/function_calling.py`
  - `tests/unit/test_function_result_messages.py`
- **验收标准**：
  - 工具成功、失败、审批等待都有标准消息。
  - 不把敏感原始结果直接暴露给模型。
- **测试方法**：`pytest -q tests/unit/test_function_result_messages.py`。

### [x] D6：成本和 token 统计

- **目标**：记录模型调用 usage。
- **修改文件**：
  - `fiat_agent/models/gateway.py`
  - `fiat_agent/audit/service.py`
  - `tests/unit/test_model_usage_audit.py`
- **验收标准**：
  - 每次模型调用写 session event。
  - usage 可按任务统计。
- **测试方法**：`pytest -q tests/unit/test_model_usage_audit.py`。

## 阶段 E：MCP RAG Client 接入

### [x] E1：MCP Client 基础协议

- **目标**：实现 stdio MCP Client。
- **修改文件**：
  - `fiat_agent/mcp_clients/rag_mcp_client.py`
  - `tests/integration/test_rag_mcp_initialize.py`
- **实现类/函数**：
  - `RagMcpClient.start()`
  - `RagMcpClient.initialize()`
  - `RagMcpClient.close()`
- **验收标准**：
  - 可启动 `/Users/tog/Desktop/project/MODULAR-RAG-MCP-SERVER`。
  - stdout 只处理 JSON-RPC，stderr 作为日志。
- **测试方法**：`pytest -q tests/integration/test_rag_mcp_initialize.py`。

### [x] E2：tools/list 同步

- **目标**：获取 RAG MCP 工具 schema。
- **修改文件**：
  - `fiat_agent/mcp_clients/tool_registry.py`
  - `tests/integration/test_rag_mcp_tools_list.py`
- **验收标准**：
  - 能发现 `query_knowledge_hub`、`list_collections`、`get_document_summary`。
  - schema 可转换成内部 ToolDefinition。
- **测试方法**：`pytest -q tests/integration/test_rag_mcp_tools_list.py`。

### [x] E3：query_knowledge_hub 调用

- **目标**：封装知识库查询。
- **修改文件**：
  - `fiat_agent/mcp_clients/rag_mcp_client.py`
  - `tests/integration/test_rag_mcp_query.py`
- **实现类/函数**：
  - `query_knowledge_hub(query, top_k, collection)`
- **验收标准**：
  - 返回 TextContent 可解析。
  - MCP isError 时不进入可信上下文。
- **测试方法**：`pytest -q tests/integration/test_rag_mcp_query.py`。

### [x] E4：MCP Content Parser

- **目标**：解析 TextContent、ImageContent 和引用。
- **修改文件**：
  - `fiat_agent/mcp_clients/content_parser.py`
  - `tests/unit/test_mcp_content_parser.py`
- **验收标准**：
  - 文本、图片、metadata 分离。
  - 图片内容不直接塞入普通文本上下文。
- **测试方法**：`pytest -q tests/unit/test_mcp_content_parser.py`。

### [x] E5：RAG Context Merge

- **目标**：把 RAG 检索结果合并进 Agent Context。
- **修改文件**：
  - `fiat_agent/rag/context_merge.py`
  - `fiat_agent/rag/citations.py`
  - `tests/unit/test_rag_context_merge.py`
- **验收标准**：
  - 回答必须保留来源引用。
  - collection、doc_id、chunk_id 可追踪。
- **测试方法**：`pytest -q tests/unit/test_rag_context_merge.py`。

### [x] E6：MCP RAG 健康检查和降级

- **目标**：MCP Server 异常时优雅降级。
- **修改文件**：
  - `fiat_agent/mcp_clients/rag_mcp_client.py`
  - `apps/api/routes/rag.py`
  - `tests/integration/test_rag_mcp_health.py`
- **验收标准**：
  - `GET /api/rag/mcp/status` 返回状态。
  - 启动失败时禁用 RAG 工具。
- **测试方法**：`pytest -q tests/integration/test_rag_mcp_health.py`。

## 阶段 F：Tool Gateway 与业务工具契约

### [x] F1：工具定义模型

- **目标**：定义 ToolDefinition。
- **修改文件**：
  - `fiat_agent/tools/schemas.py`
  - `tests/unit/test_tool_definition.py`
- **验收标准**：
  - 工具包含 name、description、input_schema、risk_level、approval_required。
- **测试方法**：`pytest -q tests/unit/test_tool_definition.py`。

### [x] F2：工具注册中心

- **目标**：统一注册业务工具和 MCP 工具。
- **修改文件**：
  - `fiat_agent/tools/registry.py`
  - `tests/unit/test_tool_registry.py`
- **验收标准**：
  - 工具名唯一。
  - 可按角色和环境过滤。
- **测试方法**：`pytest -q tests/unit/test_tool_registry.py`。

### [x] F3：Tool Gateway 执行入口

- **目标**：实现工具调用总入口。
- **修改文件**：
  - `fiat_agent/tool_gateway/gateway.py`
  - `tests/unit/test_tool_gateway.py`
- **实现类/函数**：
  - `execute_tool(actor, tool_name, arguments, context)`
- **验收标准**：
  - 执行前调用 `can_execute`。
  - 执行后写 tool_calls 和 audit_logs。
  - 失败有统一错误结构。
- **测试方法**：`pytest -q tests/unit/test_tool_gateway.py`。

### [x] F4：ES 只读工具契约

- **目标**：实现告警日志查询工具壳。
- **修改文件**：
  - `fiat_agent/tool_gateway/es_tools.py`
  - `tests/unit/test_es_tools.py`
- **验收标准**：
  - 只允许白名单 index 和 query template。
  - 不允许任意 ES DSL。
- **测试方法**：`pytest -q tests/unit/test_es_tools.py`。

### [x] F5：DB 只读工具契约

- **目标**：实现数据库只读查询工具壳。
- **修改文件**：
  - `fiat_agent/tool_gateway/db_tools.py`
  - `tests/unit/test_db_tools.py`
- **验收标准**：
  - 只允许固定查询函数。
  - 不接受任意 SQL。
  - 敏感字段脱敏。
- **测试方法**：`pytest -q tests/unit/test_db_tools.py`。

### [ ] F6：Lark 工具契约

- **目标**：实现 Lark 消息和审批卡片工具。
- **修改文件**：
  - `fiat_agent/tool_gateway/lark_tools.py`
  - `tests/unit/test_lark_tools.py`
- **验收标准**：
  - 可发送告警摘要。
  - 可创建审批卡片。
  - mock SDK 测试通过。
- **测试方法**：`pytest -q tests/unit/test_lark_tools.py`。

### [ ] F7：测试环境工具契约

- **目标**：实现测试账号、充值、KYC 工具壳。
- **修改文件**：
  - `fiat_agent/tool_gateway/test_env_tools.py`
  - `tests/unit/test_test_env_tools.py`
- **验收标准**：
  - 仅测试环境可执行。
  - 所有测试数据带标识。
- **测试方法**：`pytest -q tests/unit/test_test_env_tools.py`。

## 阶段 G：LangGraph Agent Orchestrator

### [ ] G1：AgentState 定义

- **目标**：定义 LangGraph 状态对象。
- **修改文件**：
  - `fiat_agent/orchestrator/state.py`
  - `tests/unit/test_agent_state.py`
- **验收标准**：
  - 包含 actor、session、messages、task_type、tool_results、approval_state。
- **测试方法**：`pytest -q tests/unit/test_agent_state.py`。

### [ ] G2：任务分类节点

- **目标**：识别任务类型。
- **修改文件**：
  - `fiat_agent/orchestrator/nodes/classify.py`
  - `tests/unit/test_task_classifier.py`
- **验收标准**：
  - 能识别 rag_qa、alert_diagnosis、test_env_automation、cashback_reconcile、logistics_validation。
- **测试方法**：`pytest -q tests/unit/test_task_classifier.py`。

### [ ] G3：Context Builder 节点

- **目标**：组装系统提示词、权限、skill、memory、tool schema。
- **修改文件**：
  - `fiat_agent/context/builder.py`
  - `fiat_agent/orchestrator/nodes/build_context.py`
  - `tests/unit/test_context_builder.py`
- **验收标准**：
  - 只暴露权限允许的工具。
  - RAG 结果带引用进入上下文。
- **测试方法**：`pytest -q tests/unit/test_context_builder.py`。

### [ ] G4：Planning 节点

- **目标**：生成结构化执行计划。
- **修改文件**：
  - `fiat_agent/orchestrator/nodes/plan.py`
  - `tests/unit/test_planning_node.py`
- **验收标准**：
  - 输出包含 steps、required_tools、risk_level、need_approval。
  - 结构不合法时要求模型重试或降级。
- **测试方法**：`pytest -q tests/unit/test_planning_node.py`。

### [ ] G5：Tool 节点

- **目标**：执行 function call / tool call。
- **修改文件**：
  - `fiat_agent/orchestrator/nodes/tool.py`
  - `tests/integration/test_tool_node.py`
- **验收标准**：
  - 工具结果回灌给模型。
  - 权限拒绝不会执行工具。
- **测试方法**：`pytest -q tests/integration/test_tool_node.py`。

### [ ] G6：Approval 节点

- **目标**：高风险任务进入等待审批。
- **修改文件**：
  - `fiat_agent/orchestrator/nodes/approval.py`
  - `tests/unit/test_approval_node.py`
- **验收标准**：
  - L4/L5 工具不自动执行。
  - approval_requested 事件写入 session。
- **测试方法**：`pytest -q tests/unit/test_approval_node.py`。

### [ ] G7：Final Answer 节点

- **目标**：生成最终报告。
- **修改文件**：
  - `fiat_agent/orchestrator/nodes/final.py`
  - `tests/unit/test_final_answer_node.py`
- **验收标准**：
  - 告警、RAG、dry-run 输出格式固定。
  - 引用来源保留。
- **测试方法**：`pytest -q tests/unit/test_final_answer_node.py`。

### [ ] G8：Graph 编排

- **目标**：串联完整 LangGraph。
- **修改文件**：
  - `fiat_agent/orchestrator/graph.py`
  - `tests/integration/test_agent_graph.py`
- **验收标准**：
  - RAG 问答端到端通过。
  - 工具调用、session 写入、event stream 均触发。
- **测试方法**：`pytest -q tests/integration/test_agent_graph.py`。

## 阶段 H：业务 Workflows

### [ ] H1：Domain Skill 加载

- **目标**：实现业务技能包加载。
- **修改文件**：
  - `fiat_agent/skills/loader.py`
  - `fiat_agent/skills/*/SKILL.md`
  - `tests/unit/test_domain_skill_loader.py`
- **验收标准**：
  - 不同 task_type 加载不同 prompt、工具和输出 schema。
- **测试方法**：`pytest -q tests/unit/test_domain_skill_loader.py`。

### [ ] H2：RAG 问答 workflow

- **目标**：实现法币知识问答。
- **修改文件**：
  - `fiat_agent/workflows/rag_qa.py`
  - `tests/e2e/test_rag_qa_workflow.py`
- **验收标准**：
  - 自动调用 MCP RAG。
  - 回答带来源。
  - 无依据时拒答。
- **测试方法**：`pytest -q tests/e2e/test_rag_qa_workflow.py`。

### [ ] H3：告警诊断 workflow

- **目标**：实现告警日志排查。
- **修改文件**：
  - `fiat_agent/workflows/alert_diagnosis.py`
  - `tests/e2e/test_alert_diagnosis_workflow.py`
- **验收标准**：
  - 并行查询 ES、DB、RAG。
  - 输出影响范围、可能原因、置信度、下一步。
  - 可发送 Lark 通知。
- **测试方法**：`pytest -q tests/e2e/test_alert_diagnosis_workflow.py`。

### [ ] H4：测试账号 workflow

- **目标**：实现测试环境自动化。
- **修改文件**：
  - `fiat_agent/workflows/test_automation.py`
  - `tests/e2e/test_test_automation_workflow.py`
- **验收标准**：
  - 创建测试账号、充值、KYC 流程可编排。
  - 仅测试环境可执行。
- **测试方法**：`pytest -q tests/e2e/test_test_automation_workflow.py`。

### [ ] H5：返现表格解析

- **目标**：解析 Excel/CSV 返现文件。
- **修改文件**：
  - `fiat_agent/tool_gateway/cashback_tools.py`
  - `tests/unit/test_cashback_parse.py`
- **验收标准**：
  - 字段映射可配置。
  - 重复记录和金额格式异常可识别。
- **测试方法**：`pytest -q tests/unit/test_cashback_parse.py`。

### [ ] H6：返现对账 dry-run

- **目标**：生成返现对账报告和变更计划。
- **修改文件**：
  - `fiat_agent/workflows/cashback_reconcile.py`
  - `tests/e2e/test_cashback_reconcile_workflow.py`
- **验收标准**：
  - 总额校验、记录校验、状态校验通过。
  - 只生成 dry-run，不生产写入。
- **测试方法**：`pytest -q tests/e2e/test_cashback_reconcile_workflow.py`。

### [ ] H7：物流表格解析和状态机

- **目标**：实现物流字段校验和状态流转校验。
- **修改文件**：
  - `fiat_agent/tool_gateway/logistics_tools.py`
  - `fiat_agent/workflows/logistics_validation.py`
  - `tests/unit/test_logistics_state_machine.py`
- **验收标准**：
  - 非法状态流转被拒绝。
  - 地址、单号、卡号异常可识别。
- **测试方法**：`pytest -q tests/unit/test_logistics_state_machine.py`。

### [ ] H8：审批后执行占位

- **目标**：为第二阶段生产提交预留接口。
- **修改文件**：
  - `fiat_agent/workflows/cashback_reconcile.py`
  - `fiat_agent/workflows/logistics_validation.py`
  - `tests/unit/test_production_submit_guard.py`
- **验收标准**：
  - 未审批不能调用 submit。
  - MVP 中 submit 默认禁用或 fake。
- **测试方法**：`pytest -q tests/unit/test_production_submit_guard.py`。

## 阶段 I：Entry Adapters

### [ ] I1：FastAPI Agent API

- **目标**：实现会话和消息 API。
- **修改文件**：
  - `apps/api/routes/agent.py`
  - `tests/integration/test_agent_api.py`
- **验收标准**：
  - `POST /api/agent/sessions`
  - `POST /api/agent/sessions/:id/messages`
  - `GET /api/agent/sessions/:id/events`
- **测试方法**：`pytest -q tests/integration/test_agent_api.py`。

### [ ] I2：RAG 代理 API

- **目标**：暴露 RAG MCP 代理接口。
- **修改文件**：
  - `apps/api/routes/rag.py`
  - `tests/integration/test_rag_api.py`
- **验收标准**：
  - `POST /api/rag/query`
  - `GET /api/rag/collections`
  - `GET /api/rag/documents/:id/summary`
- **测试方法**：`pytest -q tests/integration/test_rag_api.py`。

### [ ] I3：CLI

- **目标**：实现 `fiat-agent` 命令。
- **修改文件**：
  - `apps/cli/main.py`
  - `tests/e2e/test_cli.py`
- **模式**：
  - `chat`
  - `once`
  - `server`
- **验收标准**：
  - 一次性问答可输出结果。
  - chat 模式可多轮。
- **测试方法**：`pytest -q tests/e2e/test_cli.py`。

### [ ] I4：Lark Bot

- **目标**：接入 Lark 消息和审批回调。
- **修改文件**：
  - `apps/lark_bot/app.py`
  - `apps/lark_bot/handlers.py`
  - `tests/integration/test_lark_bot.py`
- **验收标准**：
  - 可接收问答消息。
  - 可处理审批卡片回调。
- **测试方法**：`pytest -q tests/integration/test_lark_bot.py`。

### [ ] I5：Fiat MCP Adapter

- **目标**：可选，把 fiat-agent 暴露为 MCP Server 供 Claude Code 调用。
- **修改文件**：
  - `adapters/claude_code_mcp/server.py`
  - `tests/integration/test_fiat_mcp_adapter.py`
- **验收标准**：
  - 暴露 `fiat.rag_search`、`fiat.alert_diagnose` 等工具。
  - 仍然经过 fiat-agent 权限和审计。
- **测试方法**：`pytest -q tests/integration/test_fiat_mcp_adapter.py`。

## 阶段 J：React Web Console

### [ ] J1：Web Console 骨架

- **目标**：建立 React / Next.js 项目。
- **修改文件**：
  - `apps/web_console/package.json`
  - `apps/web_console/src/app/page.tsx`
  - `apps/web_console/src/lib/api.ts`
- **验收标准**：
  - 可启动页面。
  - 可读取 `/api/users/me`。
- **测试方法**：`npm run check` 或前端项目本地检查命令。

### [ ] J2：会话列表和聊天页

- **目标**：展示会话列表、消息流、输入框。
- **修改文件**：
  - `apps/web_console/src/app/sessions/page.tsx`
  - `apps/web_console/src/components/chat/*`
- **验收标准**：
  - 可创建会话。
  - 可发送消息。
  - 可展示流式响应。
- **测试方法**：前端组件测试或 Playwright 冒烟。

### [ ] J3：工具调用轨迹页

- **目标**：展示 function call 和 tool result。
- **修改文件**：
  - `apps/web_console/src/components/tool-calls/*`
- **验收标准**：
  - 展示工具名、参数摘要、状态、耗时、风险等级。
  - 失败和审批等待状态清晰。
- **测试方法**：组件测试。

### [ ] J4：RAG 引用展示

- **目标**：展示 MCP RAG 来源和引用。
- **修改文件**：
  - `apps/web_console/src/components/citations/*`
- **验收标准**：
  - 展示 collection、source、chunk、score。
  - 图片引用不挤压正文。
- **测试方法**：组件测试。

### [ ] J5：审批和 dry-run 页面

- **目标**：展示审批单和 dry-run 变更计划。
- **修改文件**：
  - `apps/web_console/src/app/approvals/page.tsx`
  - `apps/web_console/src/components/approvals/*`
- **验收标准**：
  - 可查看待审批任务。
  - 可 approve / reject。
  - 参数摘要不可被页面篡改。
- **测试方法**：Playwright 冒烟。

### [ ] J6：审计查询页面

- **目标**：展示审计日志和工具统计。
- **修改文件**：
  - `apps/web_console/src/app/audit/page.tsx`
  - `apps/web_console/src/components/audit/*`
- **验收标准**：
  - 可按用户、工具、风险等级、时间筛选。
  - 可查看单个任务审计链路。
- **测试方法**：Playwright 冒烟。

## 阶段 K：Observability、Evaluation 和 E2E 收口

### [ ] K1：Event Bus

- **目标**：实现事件广播。
- **修改文件**：
  - `fiat_agent/events/bus.py`
  - `fiat_agent/events/types.py`
  - `tests/unit/test_event_bus.py`
- **验收标准**：
  - session event、tool event、approval event 都可广播。
- **测试方法**：`pytest -q tests/unit/test_event_bus.py`。

### [ ] K2：SSE / WebSocket

- **目标**：对前端输出实时事件。
- **修改文件**：
  - `fiat_agent/events/stream.py`
  - `apps/api/routes/events.py`
  - `tests/integration/test_event_stream.py`
- **验收标准**：
  - 前端可订阅 session 事件。
  - 断线重连可按 cursor 续传。
- **测试方法**：`pytest -q tests/integration/test_event_stream.py`。

### [ ] K3：Agent Trace

- **目标**：记录 agent 执行链路。
- **修改文件**：
  - `fiat_agent/audit/service.py`
  - `fiat_agent/orchestrator/graph.py`
  - `tests/integration/test_agent_trace.py`
- **验收标准**：
  - 每轮包含 plan、model_call、tool_call、final。
  - 可定位失败节点。
- **测试方法**：`pytest -q tests/integration/test_agent_trace.py`。

### [ ] K4：Agent Eval 数据集

- **目标**：建立最小评测集。
- **修改文件**：
  - `tests/fixtures/agent_eval_cases.json`
  - `tests/e2e/test_agent_eval.py`
- **验收标准**：
  - 覆盖 RAG、告警、权限拒绝、审批等待。
  - 输出稳定结构。
- **测试方法**：`pytest -q tests/e2e/test_agent_eval.py`。

### [ ] K5：端到端验收

- **目标**：跑通 MVP 主链路。
- **修改文件**：
  - `tests/e2e/test_mvp_flows.py`
- **验收标准**：
  - RAG 问答通过。
  - 告警诊断通过。
  - 测试账号助手通过 fake backend。
  - 权限拒绝和审批等待通过。
- **测试方法**：`pytest -q tests/e2e/test_mvp_flows.py`。

### [ ] K6：README 和部署文档

- **目标**：形成可复现项目。
- **修改文件**：
  - `README.md`
  - `docs/architecture.md`
  - `docs/session-memory-design.md`
  - `docs/permission-model.md`
  - `docs/tool-contracts.md`
- **验收标准**：
  - 新用户能按 README 跑通 API、CLI、MCP RAG 接入。
  - 文档包含配置、测试、常见问题。
- **测试方法**：按 README 手动走一遍。

## 12. 交付里程碑

### M1：基础可运行

完成阶段 A、B。

交付：

1. 项目可启动。
2. 配置可加载。
3. 用户、权限、审计基础可用。

### M2：会话和模型闭环

完成阶段 C、D。

交付：

1. Session Store 可用。
2. 回退、分支、压缩可用。
3. Model Gateway 和 Function Calling 可用。

### M3：RAG 和工具闭环

完成阶段 E、F。

交付：

1. 接入 `MODULAR-RAG-MCP-SERVER`。
2. RAG 工具可通过 MCP 调用。
3. Tool Gateway 权限、审计可用。

### M4：Agent MVP

完成阶段 G、H。

交付：

1. LangGraph Agent Loop 可运行。
2. RAG 问答、告警诊断、测试账号助手可用。
3. 返现和物流 dry-run 初版可用。

### M5：多入口

完成阶段 I。

交付：

1. FastAPI 可用。
2. CLI 可用。
3. Lark Bot 可用。
4. MCP Adapter 可选可用。

### M6：产品化和验收

完成阶段 J、K。

交付：

1. React Web Console 可用。
2. 事件流可用。
3. 审批和审计页面可用。
4. E2E 测试和 README 完成。

## 13. 后续扩展

> **扩展点处理约定（全局适用）**
> - 所有「待扩展的点」（如 PostgreSQL、Pi Extension、多 Agent 并行、生产执行能力、Agent 回放评测等）统一标记为**可选**。
> - 实现顺序排在主线功能（A–K 阶段）全部完成**之后**，即**最后实现**。
> - 任何扩展点动手实现**之前必须先与用户确认（实现之前先询问）**，不得自行推进。

### 13.1 多 Agent 并行诊断（可选扩展点）

在告警诊断中拆分：

1. Log Agent。
2. DB Agent。
3. RAG Agent。
4. Release Agent。
5. Supervisor Agent。

### 13.2 生产执行能力（可选扩展点）

返现和物流从 dry-run 演进到受控生产提交：

1. L4/L5 审批。
2. 双人审批。
3. 参数签名。
4. 执行幂等。
5. 失败补偿。

### 13.3 Agent 回放和评测（可选扩展点）

基于 JSONL 导出：

1. 回放工具调用链。
2. 构造 eval case。
3. 对比不同模型策略。
4. 回归测试 prompt 和 tool schema。

### 13.4 Pi Extension（可选扩展点）

实现 `.pi/extensions/fiat-agent.ts`：

1. 注册法币工具。
2. 调用 fiat-agent API。
3. 展示 dry-run。
4. 高风险操作前确认。

Pi Extension 只是可选入口，不承载核心业务逻辑。
