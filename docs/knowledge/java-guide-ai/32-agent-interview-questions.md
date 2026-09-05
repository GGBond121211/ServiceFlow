# 32｜AI Agent 面试题总结

来源：[JavaGuide 原文](https://javaguide.cn/ai/interview-questions/agent-interview-questions.html)（约 1906 字）

读取日期：2026-09-02。侧边栏位置：「面试题」第 3 篇。

**题库页，不含答案。** 原文的组织主线是 Agent 执行链路：读取上下文 → 决定下一步动作 → 调用工具 → 观察结果 → 判断继续/结束/转人工。Memory、MCP、Skills、Harness、Workflow 都被放回这条链路里理解。答案在 08–17 各专题笔记。

这是 32 篇里**与 009 关系最直接**的一篇——ServiceFlow 就是一个 Agent 项目。

## Agent 基础（答案见 [08](08-agent-basics.md)、[10](10-multi-agent.md)、[29](29-ai-core-concepts.md)）

- AI Agent 是什么？和普通 Chatbot 有什么区别？
- `Agent = LLM + Planning + Memory + Tools` 这条公式怎么理解？
- Agent Loop 的完整流程是什么？
- Agent 和传统编程、Workflow 的核心区别是什么？
- ReAct、Plan-and-Execute、Reflection、Multi-Agent 分别适合什么场景？
- **Tools 注册时，工具 description 为什么很关键？**
- 什么时候用纯 Agent，什么时候用 Workflow 或 Agentic Workflow？
- **Multi-Agent 协作的主要问题是什么？为什么生产里不能盲目上多 Agent？**

## Agent Memory（答案见 [09](09-agent-memory.md)）

- 短期记忆和长期记忆有什么区别？
- Agent 记忆系统要解决哪些核心问题？
- 向量记忆和 Markdown 记忆分别适合什么场景？
- Auto Memory 是什么？**它为什么不能无限自动写入？**
- 哪些团队共享记忆适合走 Git 和 Code Review，哪些更适合数据库？
- 记忆压缩、记忆过期、记忆冲突应该怎么处理？
- 如何避免长期记忆污染上下文？
- 面试里怎么讲"有记忆"不是简单保存聊天记录？

## Prompt 与 Context Engineering（答案见 [11](11-prompt-engineering.md)、[12](12-context-engineering.md)）

- Prompt Engineering 和 Context Engineering 有什么区别？
- Prompt 四要素 Role、Task、Context、Format 分别解决什么问题？
- Few-Shot、CoT、任务分解、结构化输出分别适合什么场景？
- Prompt 注入攻击是什么？常见防护方式有哪些？
- **为什么 Agent 场景下只优化 Prompt 不够？**
- 静态规则、动态信息、工具结果、记忆应该如何进入上下文？
- 长任务上下文溢出时，Compaction、结构化笔记、Sub-agent 分别怎么用？

## MCP 与 Agent Skills（答案见 [14](14-mcp.md)、[13](13-agent-skills.md)）

- MCP 解决什么问题？为什么常被类比成 AI 领域的 USB-C？
- MCP Client、MCP Server、Host 分别是什么？
- MCP 的 Tools、Resources、Prompts 分别解决什么问题？
- MCP 和 Function Calling 有什么区别？
- 生产级 MCP Server 要做哪些安全治理？
- Agent Skills 和 Prompt、MCP、Function Calling 的边界是什么？
- **Skills 为什么要延迟加载？**
- Skill 路由怎么做？为什么它和 RAG 相似但目标不同？
- 写一个 SKILL.md 最容易踩哪些坑？

## Harness Engineering（答案见 [15](15-harness-engineering.md)）

- Harness Engineering 是什么？和 Prompt/Context Engineering 什么关系？
- 为什么说 `Agent = Model + Harness`？
- Harness 六层检查框架分别解决什么问题？
- **模型能力升级后，Harness 里的某些机制为什么需要重新验证？**
- 上下文污染、代码熵积累、工具调用可靠性分别怎么治理？
- Agent 工程里为什么需要评测器、验证器和任务状态管理？

## Workflow、Graph 与 Loop（答案见 [16](16-workflow-graph-loop.md)、[17](17-loop-engineering.md)）

- 为什么 AI 系统需要工作流？
- Workflow、Graph、Loop 三者是什么关系？
- **Graph Loop 和 Agent Loop 有什么区别？**
- Loop 如何防止死循环？
- **State 的更新策略怎么选？Replace、Append、Reducer 分别适合什么字段？**
- 条件边和动态路由有什么区别？
- 工具调用失败时，哪些错误适合重试？认证失败和非幂等写操作怎么处理？
- **工作流中断后怎么恢复？**
- 工作流有哪些特有的安全风险？

## 综合设计题（原文 6 条）

- 让 Agent 完成需要调用多个工具的长任务，如何拆分执行步骤？
- **哪些节点适合交给模型判断，哪些节点应该由规则或代码控制？**
- **Agent 的计划、工具结果和中间状态如何保存？中断后怎样恢复？**
- 工具包含写操作时，权限、参数校验、二次确认和审计怎么设计？
- 什么情况下需要 Multi-Agent？如何控制通信成本和状态一致性？
- 你会记录哪些 Trace，并用哪些指标评估任务完成率、工具调用和执行轨迹？

## 对 009 的落点

综合设计题的第 2、3 条是 **ServiceFlow 的核心主张原题**，009 有可指向源码的答案：

**"哪些节点交给模型，哪些由代码控制"** —— 009 的边界是一条明确的分界线：

```
模型只做：语言理解 → 结构化意图（agent/intent.py）
代码决定：业务是否合法（domain/policies.py 的阈值/期限/状态转换）
          副作用如何发生（application/case_service.py）
          终态是什么（read_final_state 回读数据库）
```

论据是"政策必须可重复测试"，所以退款期限和金额阈值**不能进 Prompt**（`backend/tests/unit/test_policies.py` 就是这条主张的可执行证明）。

**"中间状态如何保存？中断后怎样恢复"** —— 009 的现成答案：`AgentState`（TypedDict + `total=False` 局部更新）保存过程状态，`InMemorySaver` 按 `thread_id` 存 checkpoint，高额退款用 `interrupt()` 暂停、同 thread 的 `Command(resume={"approved": ...})` 恢复。关键区分：**checkpoint 只用于流程恢复，不是业务事实库**——订单/退款/审批的权威状态在 MySQL 里，恢复后仍要回读。

Workflow 那一组的 "State 更新策略" 也能直接对上：009 的 `tool_events` 是 Append 语义（`[*state.get("tool_events", []), event]`），`order_id`/`decision`/`policy_id` 是 Replace 语义。

**Multi-Agent 那两条题，009 的正确答案是"不需要"**，且有证据：100 案评测显示主要瓶颈是多轮执行时机和状态合并（两个保留失败案例都属此类），不是缺少多 Agent。这与原文"生产里不能盲目上多 Agent"和笔记 [10](10-multi-agent.md) 的判断一致。

需要如实承认的空白：Memory 那一整组（009 的 checkpoint 和对话历史**不是**跨会话长期 Memory）、MCP 那一整组（009 无 MCP 依赖）、Skills、以及 Trace 采样/传播。这些是 `2.0-preparation.md` 的候选，不是已有能力。

## 关键词

Agent 执行链路题库、工具 description、Multi-Agent 慎用、Auto Memory 边界、只优化 Prompt 不够、Skills 延迟加载、Model + Harness、Graph Loop vs Agent Loop、Replace/Append/Reducer、中断恢复、checkpoint 不是事实库、模型判断与代码控制的分界。
