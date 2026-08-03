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
