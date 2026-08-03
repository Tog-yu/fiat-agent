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
