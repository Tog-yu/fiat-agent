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
