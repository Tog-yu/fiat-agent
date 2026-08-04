# 工具契约与网关（fiat-agent）

所有工具（业务工具与 MCP 派生工具）都经由统一的**工具注册表**与**工具网关**执行。网关是确定性
鉴权 + 审计的执行闸门（DEV_SPEC §6.4 / F）。本文档对应阶段 F（F1–F7）与 E（MCP 接入）。

## 1. 工具定义与注册表

`fiat_agent/tools/schemas.py::ToolDefinition`：工具的声明式契约（`name` / `description` / `risk_level` /
`approval_required` / 参数 schema）。

`fiat_agent/tools/registry.py::ToolRegistry`：

- `register(tool)`：注册工具，重名抛 `DuplicateToolNameError`（业务工具不得与 MCP 工具互相覆盖/被覆盖）。
- `sync_mcp_tools(client)`：从 MCP 客户端发现工具并注册（阶段 E2）。
- `filter(actor, environment)`：委托 `auth.policy.filter_tools`，返回该角色可见/可执行的工具
  （需审批的工具仍保留——门控在执行而非可见）。
- `by_name` / `names` / `tools`：查询。

Agent 内部调用 RAG 的策略 key 是 **`rag_query`**（对应 `tool_policies.yaml`），而 MCP Server 暴露的原始工具名是
`query_knowledge_hub`（由 `RagMcpClient` 包装）。二者通过 `apps/api/agent_service.py` 的 handler 映射。

## 2. 工具网关（执行闸门）

`fiat_agent/tool_gateway/gateway.py::ToolGateway` 是**唯一**的工具执行入口：

```python
async def execute_tool(actor, tool_name, arguments, context=None,
                       *, approved=False, tool_call_id=None) -> ToolResult:
```

执行顺序（任何副作用前先鉴权）：

1. **鉴权网关**：`can_execute(actor, tool_name)`。拒绝 → 返回 `ToolResult(status=ERROR, error=reason)`，**不执行**。
2. **审批网关**：`decision.approval_required and not approved` → 返回 `ToolResult(status=PENDING_APPROVAL)`，不执行。
3. **执行 handler**：找到注册 handler；不存在 → ERROR（`no handler registered for tool '...'`）。
   handler 可为 sync/async，签名 `(actor, arguments, context) -> raw`。
4. **归一化与审计**：成功/异常均归一化为 `ToolResult`（`D5`）；无论结果都写
   `ToolCallRecord` 与 `audit_logs` 的 `tool_call` 事件。

### 2.1 Handler 契约

```python
Handler = Callable[[ActorContext, dict[str, Any], Any], Any | Awaitable[Any]]
```

- 接收 `(actor, arguments, context)`，返回**原始**输出（dict/str/list/None）。
- 严禁任意 DSL/SQL：ES/DB 工具只接受**固定模板 + 参数绑定**（见 §4）。
- 返回结构建议为 dict（如 `{"status","answer","citations"}`），便于会话事件存储与模型消费一致。
- 异常被网关捕获并归一化，不会以原始堆栈泄漏到 Agent 循环。

### 2.2 ToolResult 归一化

`fiat_agent/tools/function_calling.py::ToolResult`：

- `status` ∈ {SUCCESS, ERROR, PENDING_APPROVAL}（`ToolResultStatus`）。
- 字段：`tool_call_id, name, status, content, error, raw`。
- 网关对 raw 做 `_summarize`（最长 500 字符）作为 `content`，避免超大输出灌入上下文。

## 3. 当前工具与实现状态

`build_agent_service`（`apps/api/agent_service.py`）按 `tool_policies.yaml` 注册 handler：

| 工具 | 真实 handler | MVP 状态 |
|---|---|---|
| `rag_query` | `_rag_query_handler` → `RagMcpClient.query_knowledge_hub` | ✅ 真实接入（需 RAG MCP Server） |
| `cashback_parse` | `make_cashback_parse_handler()` | ✅ 真实（只读解析 .xlsx/.csv） |
| `logistics_validate` | `make_logistics_validate_handler()` | ✅ 真实（只读校验） |
| `es_query` | `_unavailable_handler_for` | ⚠️ 后端适配 MVP 未接入，返回 `status: unavailable` |
| `db_query` | `_unavailable_handler_for` | ⚠️ 同上 |
| `lark_notify` | `_unavailable_handler_for` | ⚠️ 同上 |
| `test_env` | `_unavailable_handler_for` | ⚠️ 同上（仅 DEV，且资源须打 `TEST_` 标记） |
| `cashback_reconcile` | `_unavailable_handler_for` | ⚠️ 同上（dry-run，需审批） |
| `cashback_submit` | 无（策略禁止） | ⛔ MVP 禁用（`allowed_roles: []`） |

> "未接入"的工具不会崩溃：handler 返回确定性结构化消息，Agent 仍能给出连贯回答，且调用仍被审计。

## 4. 业务工具契约约束

- **ES / DB 工具**：绝不接受任意 DSL/SQL。只能使用**固定查询模板 + 参数绑定**；
  参数经校验后注入，杜绝注入风险（对应 DEV_SPEC 安全约束）。
- **test_env 工具**：仅 `dev` 环境可用；任何被操作资源必须带 `TEST_` 前缀标记，
  避免误伤生产/真实数据。
- **cashback_submit**：生产提交在 MVP 中完全禁用（`allowed_roles: []` + `denied_actions: [submit_prod]`）。

## 5. MCP RAG 客户端契约

`fiat_agent/mcp_clients/rag_mcp_client.py::RagMcpClient`（stdio 传输）：

- 生命周期：`start()`（拉起子进程并开 stdio 传输）→ `initialize()`（JSON-RPC 握手）→ 调用 → `close()`。
  推荐用 `async with RagMcpClient(...) as client:`。
- 封装方法：`query_knowledge_hub(query, top_k=5, collection=None)`、
  `list_collections(include_stats=True)`、`get_document_summary(doc_id, collection=None)`。
- `call_tool` 在 Server 返回 `isError` 时抛 `ToolExecutionError`，防止错误检索进入受信上下文。
- 解析：`fiat_agent/mcp_clients/content_parser.py::parse_mcp_contents` 把 MCP content items 解析为
  `text_context` + `metadata`（引用），再由 `fiat_agent/rag/` 做引用解析与上下文合并。

**传输契约**：MCP stdio 只从 stdout 读 JSON-RPC，stderr 为独立日志流，Server 日志不污染协议。

## 6. 审计与可观测

- 每次工具调用（无论成功/拒绝/待审批）都经 `ToolGateway._finish` 写 `ToolCallRecord`
  （内存日志，后续阶段持久化到 `sessions.store.ToolCall`）+ `audit_logs` 的 `tool_call` 事件。
- 审计写入前经 `logging.redact_sensitive` 脱敏，密钥不落库（见 [permission-model.md](permission-model.md)）。

## 7. 测试要点

- 每个业务工具均配 **Fake\* 处理器 + hermetic 单测**（不依赖真实后端/MCP/LLM）。
- `tests/unit/test_approval_node.py` 验证：被拒绝工具不进入 `pending_approvals`，需审批工具进入待审批队列。
- `tests/e2e/test_agent_eval.py`、`tests/e2e/test_mvp_flows.py` 用脚本化模型覆盖 rag_qa / 告警诊断 /
  测试账号(fake backend) / 权限拒绝 / 待审批 等多条链路。
