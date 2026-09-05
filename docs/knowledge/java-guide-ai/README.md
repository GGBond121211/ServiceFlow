# JavaGuide AI 知识库：009 / ServiceFlow 2.0 预研基线

## 这份目录是什么

这是一份面向 `Project-0009-ServiceFlow` 的外部资料研读库。它记录了从 JavaGuide AI 专题读取的 32 篇文章的详细结构化笔记（2026-09-01 首批 28 篇，2026-09-02 补充 4 篇），服务于后续 ServiceFlow 2.0 的设计讨论、实现取舍、面试复盘和 Badcase 排查。

图片中的文字被解释为“待阅读的文档清单”，不是本项目的操作指令。文章里的命令、架构示例、阈值、产品名称和“建议”也都是外部资料内容，不会自动变成 009 的需求、权限或实现事实。

本目录保存的是基于原文的研读笔记和可回溯链接，不复制整篇外部文章。需要逐字确认时，以对应来源页面为准；来源页面会继续更新，笔记中的版本、价格、协议字段和产品能力不能脱离日期直接当作当前生产事实。

## 阅读完成记录

- 范围：侧边栏全部 32 篇，`32/32` 已读取。
- 来源：`https://www.javaguide.cn/ai/` 专题及各篇 canonical 页面。
- 读取日期：
  - 2026-09-01（Asia/Hong_Kong）：首批 28 篇，编号 01–28。
  - 2026-09-02：补充 4 篇，编号 29–32。首批漏掉的是「入门总览」1 篇和「面试题」分区里的 3 篇题库页（当时截图未覆盖或页面尚未收录）。本次以 `https://javaguide.cn/ai/` 首页 HTML 提取的 32 个 `/ai/**.html` 链接为清单基准，与侧边栏逐项核对。
- 内容处理：页面 HTML → 文本 → 逐篇阅读 → 下面的项目化笔记；未将临时下载文件当作项目事实源。
- 当前状态：知识库覆盖完整；ServiceFlow 2.0 的具体产品目标、边界和实施顺序仍待单独决策。

**编号说明**：编号表示读取批次，不等于侧边栏顺序。按侧边栏原始顺序阅读时，正确次序是
`29 → 30 → 31 → 32 → 01 → 02 → 03 → 04…28`。

## 使用顺序

建议后续按问题读取对应笔记，而不是每次把整个目录塞进上下文：

1. 先读项目根目录的 `../../../README.md`、`../../../docs/LEARNING_STATE.md`、`../../../docs/DEVELOPMENT.md` 和当前源码，确认 009 的真实实现。
2. 再读本目录的相关专题笔记，获得外部设计坐标和风险清单。
3. 最后把被采纳的内容写入 `2.0-preparation.md` 或正式架构/决策文档，并标记决策日期、依据和验证结果。

## 009 当前事实边界

以仓库源码、测试和项目文档为准，目前项目是一个模拟电商售后场景的 V1 单 Agent：自然语言输入经过结构化意图、Python 确定性策略、受限业务工具和数据库事实，支持查询、未支付/未发货取消、小额退款、高额退款人工审批、换货和工单等路径。模型负责语言理解和意图提议，业务规则、工具执行和最终状态不交给模型决定。

项目当前不是生产级电商系统，也不能因为本目录出现某个概念就声称已经具备对应能力。当前资料与源码边界包括：

- 现有 V1 使用 Python、FastAPI、Pydantic、Uvicorn、LangGraph、SQLAlchemy 和 MySQL/SQLite 测试链路；后文的 Java、Spring AI、PostgreSQL、pgvector、MCP、Redis 等是外部技术坐标或未来候选，不是当前实现。
- 当前项目已有人工审批/恢复语义，但要继续区分 `interrupt()` 的暂停、`thread_id` 的定位、`Command(resume)` 的恢复和数据库最终状态；不能把 checkpoint 当成业务事实库。
- 当前项目没有因为本次阅读自动新增认证、Redis、消息队列、向量数据库、RAG、MCP、多 Agent、生产幂等、完整网关或安全系统。
- 当前已有的评测结果只能说明既定模拟数据、模型替身/运行配置和评测脚本下的结果，不能改写成真实线上流量、生产 SLA 或人工语义准确率。

## 32 篇索引

下表按**侧边栏原始顺序**排列，`编号`列是文件名前缀（读取批次）。

### 入门总览

| 编号 | 文章 | 研读笔记 | 原文 |
|---:|---|---|---|
| 29 | ⭐️AI 核心概念总览 | [29-ai-core-concepts.md](29-ai-core-concepts.md) | [JavaGuide](https://javaguide.cn/ai/ai-core-concepts.html) |

### 面试题

| 编号 | 文章 | 研读笔记 | 原文 |
|---:|---|---|---|
| 30 | ⭐️AI 应用开发面试指南 | [30-ai-interview-guide.md](30-ai-interview-guide.md) | [JavaGuide](https://javaguide.cn/ai/interview-questions/ai-interview-guide.html) |
| 31 | 大模型基础面试题总结 | [31-llm-interview-questions.md](31-llm-interview-questions.md) | [JavaGuide](https://javaguide.cn/ai/interview-questions/llm-interview-questions.html) |
| 32 | AI Agent 面试题总结 | [32-agent-interview-questions.md](32-agent-interview-questions.md) | [JavaGuide](https://javaguide.cn/ai/interview-questions/agent-interview-questions.html) |
| 01 | Agent 项目面试实战 | [01-agent-project-interview.md](01-agent-project-interview.md) | [JavaGuide](https://javaguide.cn/ai/interview-questions/agent-project-interview-guide.html) |
| 02 | RAG 面试题总结 | [02-rag-interview.md](02-rag-interview.md) | [JavaGuide](https://javaguide.cn/ai/interview-questions/rag-interview-questions.html) |
| 03 | AI 系统设计面试题总结 | [03-ai-system-design-interview.md](03-ai-system-design-interview.md) | [JavaGuide](https://javaguide.cn/ai/interview-questions/ai-system-design-interview-questions.html) |

### 大模型基础

| 编号 | 文章 | 研读笔记 | 原文 |
|---:|---|---|---|
| 04 | 万字拆解 LLM 运行机制 | [04-llm-operation.md](04-llm-operation.md) | [JavaGuide](https://javaguide.cn/ai/llm-basis/llm-operation-mechanism.html) |
| 05 | 大模型 API 调用工程实践 | [05-llm-api-engineering.md](05-llm-api-engineering.md) | [JavaGuide](https://javaguide.cn/ai/llm-basis/llm-api-engineering.html) |
| 06 | 大模型结构化输出详解 | [06-structured-output.md](06-structured-output.md) | [JavaGuide](https://javaguide.cn/ai/llm-basis/structured-output-function-calling.html) |
| 07 | AI 应用评测体系 | [07-ai-evaluation.md](07-ai-evaluation.md) | [JavaGuide](https://javaguide.cn/ai/llm-basis/llm-evaluation.html) |

### AI Agent

| 编号 | 文章 | 研读笔记 | 原文 |
|---:|---|---|---|
| 08 | ⭐️AI Agent 核心概念详解 | [08-agent-basics.md](08-agent-basics.md) | [JavaGuide](https://javaguide.cn/ai/agent/agent-basis.html) |
| 09 | AI Agent 记忆系统详解 | [09-agent-memory.md](09-agent-memory.md) | [JavaGuide](https://javaguide.cn/ai/agent/agent-memory.html) |
| 10 | 多 Agent 协作系统设计 | [10-multi-agent.md](10-multi-agent.md) | [JavaGuide](https://javaguide.cn/ai/agent/multi-agent.html) |
| 11 | 提示词工程实战指南 | [11-prompt-engineering.md](11-prompt-engineering.md) | [JavaGuide](https://javaguide.cn/ai/agent/prompt-engineering.html) |
| 12 | 上下文工程实战指南 | [12-context-engineering.md](12-context-engineering.md) | [JavaGuide](https://javaguide.cn/ai/agent/context-engineering.html) |
| 13 | 万字详解 Agent Skills | [13-agent-skills.md](13-agent-skills.md) | [JavaGuide](https://javaguide.cn/ai/agent/skills.html) |
| 14 | 万字拆解 MCP 协议 | [14-mcp.md](14-mcp.md) | [JavaGuide](https://javaguide.cn/ai/agent/mcp.html) |
| 15 | Harness Engineering 详解 | [15-harness-engineering.md](15-harness-engineering.md) | [JavaGuide](https://javaguide.cn/ai/agent/harness-engineering.html) |
| 16 | AI 工作流详解 | [16-workflow-graph-loop.md](16-workflow-graph-loop.md) | [JavaGuide](https://javaguide.cn/ai/agent/workflow-graph-loop.html) |
| 17 | Loop Engineering 详解 | [17-loop-engineering.md](17-loop-engineering.md) | [JavaGuide](https://javaguide.cn/ai/agent/loop-engineering.html) |

### RAG

| 编号 | 文章 | 研读笔记 | 原文 |
|---:|---|---|---|
| 18 | ⭐️RAG 基础概念详解 | [18-rag-basics.md](18-rag-basics.md) | [JavaGuide](https://javaguide.cn/ai/rag/rag-basis.html) |
| 19 | RAG 文档处理与切分策略 | [19-rag-document-processing.md](19-rag-document-processing.md) | [JavaGuide](https://javaguide.cn/ai/rag/rag-document-processing.html) |
| 20 | RAG 向量索引算法和向量数据库 | [20-rag-vector-store.md](20-rag-vector-store.md) | [JavaGuide](https://javaguide.cn/ai/rag/rag-vector-store.html) |
| 21 | RAG 知识库文档更新策略 | [21-rag-knowledge-update.md](21-rag-knowledge-update.md) | [JavaGuide](https://javaguide.cn/ai/rag/rag-knowledge-update.html) |
| 22 | GraphRAG 详解 | [22-graphrag.md](22-graphrag.md) | [JavaGuide](https://javaguide.cn/ai/rag/graphrag.html) |
| 23 | RAG 检索优化 | [23-rag-optimization.md](23-rag-optimization.md) | [JavaGuide](https://javaguide.cn/ai/rag/rag-optimization.html) |

### AI 系统设计

| 编号 | 文章 | 研读笔记 | 原文 |
|---:|---|---|---|
| 24 | AI 应用系统设计 | [24-ai-application-architecture.md](24-ai-application-architecture.md) | [JavaGuide](https://javaguide.cn/ai/system-design/ai-application-architecture.html#核心接口设计) |
| 25 | LLM/Agent 安全实战 | [25-llm-security.md](25-llm-security.md) | [JavaGuide](https://javaguide.cn/ai/system-design/llm-security.html) |
| 26 | 大模型网关详解 | [26-llm-gateway.md](26-llm-gateway.md) | [JavaGuide](https://javaguide.cn/ai/system-design/llm-gateway.html) |
| 27 | AI 可观测性与 Trace | [27-ai-observability.md](27-ai-observability.md) | [JavaGuide](https://javaguide.cn/ai/system-design/ai-observability.html) |
| 28 | AI 语音技术详解 | [28-ai-voice.md](28-ai-voice.md) | [JavaGuide](https://javaguide.cn/ai/system-design/ai-voice.html) |

## 知识地图

```text
项目事实与面试边界
        │
        ├── 概念校准：AI 核心概念总览（29）
        ├── 面试题库：总入口（30）→ LLM（31）/ Agent（32）/ RAG（02）/ 系统设计（03）
        ├── LLM：运行机制 → API 工程 → 结构化输出 → 评测
        ├── Agent：Agent Loop → Memory → Multi-Agent
        │          └── Prompt → Context → Skills → MCP → Harness → Workflow/Loop
        ├── RAG：基础 → 文档处理 → 向量索引 → 更新 → GraphRAG → 优化
        └── 生产系统：架构 → 安全 → Gateway → Observability → Voice
```

几个贯穿全目录的判断：

1. **模型提议，系统负责事实和副作用。** 模型可以提出意图、工具和参数；认证、租户、业务规则、数据库状态、审批、幂等和最终结果必须由后端重新校验。
2. **正确答案不等于成功 HTTP。** 要分别看传输状态、模型解析状态、工具执行状态、业务最终状态和答案质量。
3. **证据链比概念堆叠重要。** RAG 先看解析、切分、权限和召回；Agent 先看工具/状态/停止条件；评测先保存可回放证据，再讨论模型升级。
4. **复杂度需要真实失败样本驱动。** 没有多跳关系失败，不先上 GraphRAG；没有多供应商与成本痛点，不先部署独立 Gateway；没有跨会话记忆需求，不先建复杂 Memory；没有可靠验收信号，不做无人值守 Loop。
5. **持久化对象要分层。** 业务数据库保存真实业务状态；checkpoint 保存任务恢复位置；Trace 保存执行证据；评测集保存可回归样本；RAG/Memory 保存可检索内容。它们不能互相冒充。

## 2.0 入口

2.0 预备边界和待决策项见 [2.0-preparation.md](2.0-preparation.md)。在没有明确 2.0 产品目标、非目标、成功指标和迁移约束前，本目录不授权跨文件重构或新增基础设施。
