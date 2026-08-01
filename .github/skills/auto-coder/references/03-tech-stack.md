## 3. 技术选型

### 3.1 后端主栈

```text
Python 3.11+
FastAPI
LangGraph
LangChain
MCP Python SDK
Pydantic
SQLAlchemy
Alembic
PostgreSQL
Redis
Celery 或 Temporal
```

### 3.2 前端

```text
Next.js / React
TypeScript
SSE 或 WebSocket
```

第一阶段前端可以延后，优先做 CLI、FastAPI 和 Lark Bot。

### 3.3 RAG

```text
MODULAR-RAG-MCP-SERVER
MCP stdio transport
BM25 + Dense Retrieval + RRF + Rerank
ChromaDB / BM25 Index
```

### 3.4 模型接入

```text
OpenAI SDK
Anthropic SDK
Google / Gemini SDK
内部私有模型 SDK
本地模型可选
```
