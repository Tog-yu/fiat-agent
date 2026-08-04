# 会话记忆设计（fiat-agent）

会话记忆是 Agent 的"长期上下文"层：所有对话与中间产物以**只追加（append-only）事件**的形式持久化，
支持分支、路径回放、压缩与导出。本文档对应阶段 C（C1 模型、C2 写路径、C3 压缩/分支）与阶段 K（事件流）。

## 1. 设计原则

- **历史不可变**：从不存在"修改某条历史消息"的 API，Writer 只 `append_event`，永远追加新行。
- **树形结构**：事件经 `parent_event_id` 连成树；`active_event_id` 标记当前激活分支的末端（Pi 风格）。
- **稳定排序**：每会话内 `seq` 单调自增，读取默认按 `seq` 升序。
- **可回放**：事件流可被事件总线订阅并转 SSE；Session API 与 Web Console 共享同一份真相。

## 2. 数据模型

定义在 `fiat_agent/sessions/store.py`（SQLAlchemy 2.0 ORM，挂载于 `fiat_agent.models.orm.Base`）：

| 表 | 字段要点 | 说明 |
|---|---|---|
| `task_sessions` | `id, title, task_type, environment, actor_id, status, active_event_id, created_at, updated_at` | 一个任务/会话 |
| `task_session_events` | `id, session_id, parent_event_id, event_type, seq, content(JSON), created_at` | 只追加事件；`seq` 单调；`parent_event_id` 形成树 |
| `task_artifacts` | `id, session_id, event_id, kind, name, payload(JSON)` | 派生产物（如压缩摘要） |
| `tool_calls` | `id, session_id, event_id, tool_name, arguments, result, status, risk_level, approval_id` | 工具调用记录，关联事件与审批 |
| `session_branches` | `id, session_id, base_event_id, name, active` | 会话分支（基于某事件派生新路径） |

`event_type` 取值示例：`message`（用户/助手消息）、`tool_call`、`plan`、`approval`、`compaction`、Agent Trace 等。

## 3. 写路径（SessionStore）

`fiat_agent/sessions/store.py::SessionStore` 提供只追加写路径：

- `create_session(...)` — 新建会话。
- `append_event(session, *, session_id, event_type, content, parent_event_id=None, seq=None)`：
  - 若省略 `parent_event_id`，自动链到会话当前 `active_event_id`，使连续追加默认形成单条分支；
    首条事件成为根（无父）。
  - 若省略 `seq`，由 `_next_seq`（`max(seq)+1`，带 1 初值）生成。
  - 追加后调用 `set_active_event_id` 把新事件设为激活分支末端。
- 不存在"编辑事件"的方法——保证历史不可变。

## 4. 路径遍历与分支

- `list_session_events(session, session_id)` — 按 `seq` 返回全量事件（稳定顺序）。
- `get_event_path(session, *, session_id, event_id)` — 从 `event_id` 沿 `parent_event_id`
  回溯到根，再反转得到 `root → event` 的有序路径；带环保护（guard）。
- `get_active_path(session, session_id)` — 返回以 `active_event_id` 结尾的激活分支路径。
- `session_branches` 支持在 `base_event_id` 派生命名分支：Pi 风格的多路径探索，每个分支有独立 `active` 标记。

## 5. 压缩（Compaction）

- 配置位于 `config/settings.yaml`：`session.max_context_tokens`（默认 80000）、
  `session.compact_threshold_ratio`（默认 0.75）、`session.jsonl_export_enabled`。
- `fiat_agent/context/compaction.py` 在上下文接近阈值时生成压缩摘要，作为 `task_artifacts`
  （`kind="compaction"`）附加到会话；原事件保留，压缩产物可回放。
- `fiat_agent/context/memory.py` 与 `fiat_agent/context/builder.py` 负责在每次运行时
  组装 system prompt（含权限过滤后的 domain skill prompt 与压缩上下文）。

## 6. 事件流与实时推送（阶段 K）

会话事件在写入后会进入**事件总线**，再被 SSE 流消费：

1. `fiat_agent/events/types.py` — `AgentEvent` 信封（`id/kind/timestamp/session_id/topic/payload`），
   `EventKind` ∈ {SESSION, TOOL, APPROVAL, GENERIC}；`topic` 可细化到 `"session:<id>"` 以支持会话级订阅。
2. `fiat_agent/events/bus.py` — `EventBus`：`subscribe`（全局）/ `subscribe_topic`（topic 或 kind 匹配，
   去重）；`publish` 故障隔离。进程级单例 `get_event_bus()`。
3. `fiat_agent/events/stream.py` — `EventStreamManager`：有界环形缓冲（默认 2000）给事件分配单调 `seq`，
   按 session 分发；`stream(session_id, cursor)` 先 `replay(cursor)` 再 `live`，因订阅早于快照而无缺口。
4. `apps/api/routes/events.py` — `GET /api/events/{session_id}` 返回 SSE，每帧 `id: <seq>\ndata: ...`；
   通过 `Last-Event-ID`（或 `?cursor=`）断线续传。
5. `apps/api/routes/agent.py::list_events` — `GET /api/agent/sessions/{id}/events` 返回按 `seq` 排序的事件列表。

## 7. JSONL 导出

`fiat_agent/sessions/jsonl_exporter.py` 在 `session.jsonl_export_enabled=true` 时，将会话事件导出为
JSONL，便于离线分析、审计与重放。`task_artifacts` 中的压缩摘要同样可纳入导出。

## 8. 测试要点

- `tests/` 下相关用例验证：只追加语义（无更新 API）、`seq` 单调、`parent_event_id` 路径正确、
  分支激活切换、压缩产物写入、事件流 `replay + live` 无缺口与 `cursor` 续传。
- 存储层用临时 SQLite（`AsyncSession`）+ `pythonpath=["."]` 运行，保证可重复、无外部依赖。
