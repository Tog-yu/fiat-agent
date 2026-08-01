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
