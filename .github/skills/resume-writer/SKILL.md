---
name: resume-writer
description: "Truth-first Chinese or English resume writer for the fiat-agent project. Inspect current source and tests, match verified project highlights to a target Agent/Backend/LLM Application/Platform/Full-stack role, incorporate the user's real business context and personal contribution, separate reproducible repository facts from unverified outcome metrics, and generate defensible project experience plus likely interview follow-ups. Use when the user asks to 写简历、项目经历、简历项目、resume, CV, project experience, or wants to package fiat-agent for job applications."
---

# Resume Writer — fiat-agent

使用“真实业务背景 + 可验证个人贡献 + 项目技术亮点 + 证据化结果”生成可在面试中自圆其说的项目经历。

## Phase 1：加载并核验事实

1. 读取 [references/resume_principles.md](references/resume_principles.md)。
2. 读取 [references/project_highlights.md](references/project_highlights.md)。
3. 读取 `README.md`、`docs/`、`config/`、`pyproject.toml` 和目标亮点对应源码。
4. 动态核验仓库规模，不照抄旧数字：

```bash
rg --files tests -g 'test_*.py' | wc -l
rg -n '^\s*(async )?def test_' tests | wc -l
rg -n '^### \[x\]' DEV_SPEC.md | wc -l
find fiat_agent/skills -mindepth 2 -maxdepth 2 -name SKILL.md | wc -l
```

只有本轮实际运行 `pytest -q` 后，才能写“全部测试通过”。

## Phase 2：采集用户画像

若用户已提供足够信息，直接使用；否则最多询问 5 项：

1. **目标岗位**：Agent Engineer / Backend Engineer / LLM Application Engineer / AI Platform / Full-stack AI / 测试与质量。
2. **真实业务背景**：团队、服务对象、具体问题、原有流程为何低效或不安全。
3. **个人贡献**：独立完成、主导设计、负责模块、协作部分；不要默认把全部仓库算作个人贡献。
4. **真实数据**：上线状态、用户/请求/文件规模、延迟、准确率、节省时间、测试运行结果。
5. **输出要求**：中文/英文/双语、时间、角色、篇幅、目标 JD。

如果用户暂时没有业务背景或指标，提供“通用框架版”，并把需要确认的内容标成 `[待确认]`，不得自造公司、团队、线上规模或效果数字。

## Phase 3：证据分级

将候选内容分四级：

| 级别 | 可否直接写 | 示例 |
|---|---|---|
| A 源码事实 | 可以 | LangGraph 图、Tool Gateway、append-only session、5 个 Domain Skill |
| B 可重算仓库指标 | 重算后可以 | 测试文件数、test function 数、已完成规格任务数 |
| C 用户结果指标 | 用户确认后可以 | P95 延迟、准确率、QPS、节省工时、生产用户数 |
| D 未来/未接入能力 | 禁止写成已完成 | 多 Agent、真实长期记忆、生产 submit、Anthropic provider、全部外部 backend |

必须特别纠正：

- Hybrid Search/RRF/Rerank 属于外部 RAG Server；本项目的贡献是 MCP 集成、解析、引用、权限、审计和降级。
- 当前 Anthropic provider 未实现，local 默认禁用。
- ES/DB/Lark/test_env/cashback_reconcile 等部分 handler 默认 unavailable。
- ProductionSubmitGuard 默认只返回 fake，不执行真实生产写入。
- PostgreSQL、真实长期记忆和多 Agent 是扩展点。

## Phase 4：按岗位选择亮点

从 `project_highlights.md` 选择 4-6 个，用户指定侧重优先：

| 岗位 | 优先亮点 |
|---|---|
| Agent Engineer | LangGraph ReAct → Domain Skill → Tool Gateway → MCP Adapter → Session/Trace |
| Backend Engineer | 安全网关 → 会话存储 → 审批审计 → API/事件流 → 数据库抽象 |
| LLM Application | 模型路由 → Function Calling → MCP RAG → Context/Citation → Eval |
| AI Platform | 配置驱动 → 多入口 → 可观测性 → 权限治理 → hermetic testing |
| Full-stack AI | Agent API → SSE → Web Console → 审批/审计 UI → RAG 引用 |
| 测试与质量 | 确定性模块 → 分层测试 → scripted fake → 拒绝/审批路径 → Agent Eval |

## Phase 5：生成四段式项目经历

输出结构：

```markdown
**[项目名称]** | [时间] | [角色]

**背景**：[真实业务场景、服务对象、原有痛点]

**目标**：[系统目标与安全/效率/可追溯要求]

**过程**：
- [动词 + 个人贡献 + 技术实现 + 价值/证据]
- ...（4-6 条）

**结果**：[用户真实指标 + 可重算仓库指标；无真实业务指标时明确写工程交付结果]

**技术栈**：[与目标岗位匹配的关键词]
```

写作规则：

1. 每条 bullet 以强动词开头，但动词强度不能超过用户个人贡献。
2. 使用“做了什么 → 怎么做 → 为什么有价值”的单线结构。
3. 每条中文 bullet 建议不超过 90 字；英文建议不超过两行。
4. 优先写安全边界、状态设计、失败路径与工程决策，而不是堆框架名。
5. 结果段不强制伪造 3 个性能指标；可以使用经重算的工程规模指标，并注明测试通过状态是否已验证。

## Phase 6：附加面试防守材料

在简历初稿后主动给出：

- 3-5 个最可能追问。
- 每个追问的一句话答题骨架。
- 2-3 个最容易露馅的表述及安全改写。
- 所有 `[待确认]` 指标清单。

如用户提供目标 JD，再输出一版 ATS 关键词优化版；不得为了匹配 JD 加入项目未使用的技术。

## 最终自检

- 是否区分本仓库与外部 RAG Server？
- 是否区分源码事实、仓库计数、用户结果指标和未来扩展？
- 是否明确个人贡献，而非默认“全栈独立完成”？
- 是否出现无法解释的“主导、生产化、全量接入、零故障、100%”等绝对表述？
- 是否能为每条核心 bullet 指向至少一个源码或测试证据？
