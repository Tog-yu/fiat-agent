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
| PostgreSQL | `18.4` | 是 | `19` 仍是 beta；业务 session event store 使用 PostgreSQL 当前稳定主线。 |
| asyncpg | `0.31.0` | 是 | PostgreSQL async driver，配合 `postgresql+asyncpg://` URL。 |
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
