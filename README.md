# fiat-agent

法币业务内部使用的定制 Agent 系统。独立业务 Agent 项目（非 Claude Code 插件、非 Pi Agent 插件）。
参考 Pi Agent 架构，使用 `MODULAR-RAG-MCP-SERVER` 作为 RAG MCP Server。

## 阶段进度

当前已完成 **阶段 A–K 全部任务**（工程骨架 → 会话记忆 → 模型网关 → RAG/MCP → 工具网关 → 编排器 → 业务技能 → 审批流 → 审计/可视化 → 事件流 → 本文档）。

| 阶段 | 内容 | 状态 |
|---|---|---|
| A 工程骨架与配置基座 | 项目初始化、配置加载、CLI/API 骨架 | ✅ |
| B 用户/角色/权限/审计基座 | RBAC、确定性 `can_execute`、审计服务、FastAPI 路由 | ✅ |
| C 会话记忆 | 只追加事件存储、分支、路径遍历、压缩 | ✅ |
| D 模型网关 | 多 Provider 路由、Function Calling、用量审计 | ✅ |
| E RAG / MCP 接入 | MCP stdio 客户端、`query_knowledge_hub` 适配、结果解析、权限过滤 | ✅ |
| F 工具网关 | 工具注册表、执行闸门、审计、业务/ES/DB/Lark/测试环境工具 | ✅ |
| G 编排器 | LangGraph ReAct 循环（classify→plan→approval→tool→final） | ✅ |
| H 业务技能 | 5 个 Domain Skill 加载与注入（rag_qa/告警诊断/测试环境/返现对账/物流校验） | ✅ |
| I 应用层 | API Session/Message 服务、RAG 代理、Web Console 骨架 | ✅ |
| J 审批与可视化 | 审批队列 API、审计查询 API、Web 审计页 | ✅ |
| K 事件流与追踪 | 进程内事件总线、SSE 流（断线续传）、Agent Trace | ✅ |

## 目录结构

```text
fiat-agent/
  apps/            # 入口适配器
    api/           # FastAPI 应用 + 路由（agent/rag/approvals/audit/auth/users/events）
    cli/           # CLI 入口（once / chat / server）
    web_console/   # Next.js 前端（审计页、会话页等）
  fiat_agent/      # 核心包
    orchestrator/  # LangGraph 编排器与节点
    models/        # 模型网关与 Provider
    context/       # 上下文构建、压缩、记忆
    sessions/      # 会话记忆只追加存储
    tools/         # 工具定义与注册
    tool_gateway/  # 工具执行闸门（鉴权 + 审计）
    mcp_clients/   # RAG MCP 客户端与工具同步
    rag/           # 引用解析、上下文合并
    workflows/     # 业务工作流封装
    skills/        # 5 个 Domain Skill 包（含 SKILL.md）
    users/ auth/ approvals/ audit/ events/  # 用户/权限/审批/审计/事件
    config.py      # 配置加载（${VAR:-default} 解析）
  config/          # settings.yaml / model_policies.yaml / tool_policies.yaml / prompts/
  migrations/      # Alembic 迁移
  tests/           # unit / integration / e2e / fixtures
  docs/            # 架构、权限模型、会话记忆、工具契约
  .github/skills/  # 开发期 agent skills（auto-coder 等）
  pyproject.toml
```

## 快速开始

### 1. 环境准备

要求 **Python >= 3.11**（已验证 3.13 可用）。建议使用隔离虚拟环境：

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[test]"          # 含测试依赖
# 如需 PostgreSQL 扩展点： pip install -e ".[postgres]"
```

运行时依赖（见 `pyproject.toml`）：pydantic、PyYAML、SQLAlchemy、Alembic、aiosqlite、
FastAPI、httpx、openai、mcp、langgraph、openpyxl。

### 2. 配置

复制示例配置（或直接编辑 `config/` 下 YAML）：

- `config/settings.yaml` — 数据库连接、模型、MCP Server、会话/工具参数。
  - `database.url`：`sqlite+aiosqlite:///./data/fiat_agent.db`（默认，零运维）。
    设置 `FIAT_DB_URL=postgresql+asyncpg://...` 可切换 PostgreSQL，无需改代码。
  - `mcp_servers.rag.cwd`：指向 `MODULAR-RAG-MCP-SERVER` 根目录（RAG 接入必需）。
  - 所有密钥均通过 **环境变量名** 引用（如 `FIAT_MODEL_GPT_KEY`），绝不内联明文。
- `config/model_policies.yaml` — Provider 路由（complex/medium/simple → gpt/deepseek/local）与降级链。
- `config/tool_policies.yaml` — 工具权限策略（角色、环境、风险等级、是否需要审批）。

### 3. 运行 API 服务

```bash
# 一步启动（内部用 uvicorn 跑 apps.api.main:app）
python -m apps.cli.main server --host 127.0.0.1 --port 8000

# 或直接使用 uvicorn
uvicorn apps.api.main:app --reload --port 8000
```

健康检查：

```bash
curl http://127.0.0.1:8000/health
```

主要 API（前缀 `/api`）：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查 |
| GET | `/api/users/me` | 当前用户（id/roles/environment） |
| POST | `/api/auth/check` | 校验某工具对某角色/环境是否可执行（确定性） |
| POST | `/api/agent/sessions` | 创建任务会话 |
| GET | `/api/agent/sessions` | 列出会话 |
| POST | `/api/agent/sessions/{id}/messages` | 发送一条消息并运行编排器 |
| GET | `/api/agent/sessions/{id}/events` | 读取会话事件流（按 seq 排序） |
| GET | `/api/events/{session_id}` | SSE 实时事件流（支持断线续传 `Last-Event-ID`） |
| POST | `/api/rag/query` | RAG 检索（代理 `query_knowledge_hub`） |
| GET | `/api/rag/collections` | 列出知识库集合 |
| GET | `/api/rag/documents/{doc_id}/summary` | 文档摘要 |
| GET | `/api/rag/mcp/status` | RAG MCP Server 健康状态 |
| GET | `/api/approvals` | 审批队列 |
| POST | `/api/approvals/{id}/approve` | 批准 |
| POST | `/api/approvals/{id}/reject` | 拒绝 |
| GET | `/api/audit` | 审计事件查询（按用户/工具/风险/类型/时间过滤） |

### 4. 运行 CLI

```bash
# 单次问答（非交互）
python -m apps.cli.main once --message "帮我查一下知识库里关于退款流程的说明"

# 交互式多轮对话（输入 /exit 退出）
python -m apps.cli.main chat

# 启动服务（同 server 模式）
python -m apps.cli.main server
```

### 5. MCP RAG 接入

RAG 通过 MCP stdio 接入外部 `MODULAR-RAG-MCP-SERVER`：

1. 在 `config/settings.yaml` 的 `mcp_servers.rag` 中设置 `cwd`（Server 根目录）、`command`、`args`。
2. 该 Server 暴露三个工具：`query_knowledge_hub` / `list_collections` / `get_document_summary`。
3. 在 Agent 内部，策略名是 **`rag_query`**（`tool_policies.yaml` 中的 key），由
   `apps/api/agent_service.py::_rag_query_handler` 启动 `RagMcpClient` 调用真实 MCP 工具，
   并把结果归一化为 `{"status", "answer", "citations"}`。
4. 若 Server 未配置或不可用，`rag_query` 返回 `status: "unavailable"` / `"error"`，
   不会抛出 500，Agent 仍能给出连贯的兜底回答。

验证 RAG 连通性：

```bash
curl http://127.0.0.1:8000/api/rag/mcp/status
```

## 测试

测试分层（见 `pyproject.toml` 的 `markers`）：`unit`（单模块）、`integration`（模块协作）、`e2e`（完整链路）。
从仓库根目录运行（已配置 `pythonpath = ["."]`）：

```bash
# 全部
pytest -q

# 按层
pytest -q -m unit
pytest -q -m integration
pytest -q -m e2e

# 单文件
pytest -q tests/integration/test_event_stream.py
```

e2e 测试使用 **脚本化假模型 + 内存数据库 + 假工具处理器**，不依赖真实 LLM / MCP Server / 外部 DB。

## 设计原则

1. **Agent 与业务执行隔离**：生产写操作必须经受控后端 API、审批流、审计。
2. **确定性规则优先**：权限、审批、金额计算、状态机、字段校验、审计不走 LLM（§2.2）。
3. **RAG 通过 MCP 接入**：只实现 MCP Client / 适配 / 权限过滤 / 结果解析 / 上下文合并 / 审计。
4. **可复现与可观测**：会话只追加、事件总线、SSE 流、Agent Trace、审计 Trail 共同保证可回放与可定位。

## 常见问题（FAQ）

**Q1. 运行报错 `ModuleNotFoundError`？**
确认已在项目根目录且激活了安装好 `[test]` extra 的 venv，`pythonpath` 已含 `.`（根目录）。

**Q2. RAG 查询返回 `status: unavailable`？**
RAG MCP Server 未配置或不可达。检查 `config/settings.yaml` 的 `mcp_servers.rag.cwd` 是否指向
正确的 `MODULAR-RAG-MCP-SERVER` 目录，并确认该 Server 自带的虚拟环境/依赖已就绪。

**Q3. 工具调用被拒绝（`allowed=False`）？**
通常由 `config/tool_policies.yaml` 中的角色/环境/风险策略拦截。先用
`POST /api/auth/check` 检查具体原因（会返回 `reason` 与 `approval_required`）。
例如 `cashback_submit` 在 MVP 中对任何角色都禁止自动提交（`allowed_roles: []`）。

**Q4. 高风险的工具调用停在 `approval_pending`？**
L4/L5 风险或 `approval_required: true` 的工具需人工审批。编排器在 `approval` 节点终止，
返回 `pending_tools`，由审批队列 API 处理后再次提交执行。

**Q5. 想从 SQLite 切到 PostgreSQL？**
设置环境变量 `FIAT_DB_URL=postgresql+asyncpg://user:pass@host/db`，并安装 `pip install ".[postgres]"`。
引擎工厂按 URL scheme 自动选择驱动，无需改代码。

**Q6. 测试不连真实模型/DB 怎么做到的？**
`apps/api/agent_service.py` 的 `get_agent_service` 是 FastAPI 依赖，e2e 测试通过
`app.dependency_overrides` 注入全封闭（hermetic）实例；CLI 的 `_SERVICE_FACTORY` 也可被测试覆盖。

## 文档

- [docs/architecture.md](docs/architecture.md) — 系统架构与 Agent 循环
- [docs/session-memory-design.md](docs/session-memory-design.md) — 会话记忆设计
- [docs/permission-model.md](docs/permission-model.md) — 权限模型
- [docs/tool-contracts.md](docs/tool-contracts.md) — 工具契约与网关
