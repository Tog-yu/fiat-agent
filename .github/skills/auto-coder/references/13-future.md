## 13. 后续扩展

### 13.1 多 Agent 并行诊断

在告警诊断中拆分：

1. Log Agent。
2. DB Agent。
3. RAG Agent。
4. Release Agent。
5. Supervisor Agent。

### 13.2 生产执行能力

返现和物流从 dry-run 演进到受控生产提交：

1. L4/L5 审批。
2. 双人审批。
3. 参数签名。
4. 执行幂等。
5. 失败补偿。

### 13.3 Agent 回放和评测

基于 JSONL 导出：

1. 回放工具调用链。
2. 构造 eval case。
3. 对比不同模型策略。
4. 回归测试 prompt 和 tool schema。

### 13.4 Pi Extension

实现 `.pi/extensions/fiat-agent.ts`：

1. 注册法币工具。
2. 调用 fiat-agent API。
3. 展示 dry-run。
4. 高风险操作前确认。

Pi Extension 只是可选入口，不承载核心业务逻辑。
