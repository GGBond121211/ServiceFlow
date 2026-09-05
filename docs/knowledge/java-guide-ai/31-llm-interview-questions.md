# 31｜大模型基础面试题总结

来源：[JavaGuide 原文](https://javaguide.cn/ai/interview-questions/llm-interview-questions.html)（约 1365 字）

读取日期：2026-09-02。侧边栏位置：「面试题」第 2 篇。

这是**题库页，不含答案**。原文的组织逻辑是沿一次调用链路追问：Token 化 → 上下文组装 → 采样生成 → 流式返回 → 限流/重试 → 结构化解析 → 日志。答案在 04–07 四篇专题笔记里。

## LLM 运行机制（答案见 [04](04-llm-operation.md)、[29](29-ai-core-concepts.md)）

- Token 是什么？为什么中文、英文、代码消耗的 Token 不一样？
- 上下文窗口是什么？窗口越大，效果一定越好吗？
- 什么是 Lost in the Middle？长上下文场景下怎么缓解？
- Temperature、Top-P、Top-K 分别控制什么？生产环境怎么设置更稳？
- **为什么 Temperature 设置为 0，模型输出仍然可能不完全一致？**
- 大模型为什么会产生幻觉？常见缓解方案有哪些？
- Token 预算怎么估算？输入、输出、历史消息、RAG 证据如何取舍？
- 长上下文窗口会不会取代 RAG？二者分别适合什么场景？

## API 调用工程（答案见 [05](05-llm-api-engineering.md)、[26](26-llm-gateway.md)）

- 大模型 API 调用的完整链路是什么？
- Streaming 为什么能改善用户体验？**它能减少总耗时和 Token 成本吗？**（不能——只改善 TTFT 和感知）
- SSE、WebSocket、HTTP Chunked 在流式输出场景下怎么选？
- 哪些错误可以重试？哪些不能？
- 为什么大模型调用必须做幂等？
- **大模型限流为什么不能只按 QPS 做？**（还要按用户、租户、模型、供应商、并发和输入/输出 Token）
- 模型网关通常要承担哪些能力？
- AI 应用的调用日志里至少要记录哪些字段？

## 结构化输出与工具调用（答案见 [06](06-structured-output.md)、[14](14-mcp.md)、[13](13-agent-skills.md)）

- 为什么只写"请返回 JSON"不可靠？
- JSON Mode 和 Structured Outputs 有什么区别？
- JSON Schema 在大模型应用里解决什么问题？
- Function Calling 的完整链路是什么？
- Function Calling 和 MCP 有什么区别？
- MCP Tool 和普通 HTTP API 有什么关系？
- **Agent Skill 和 Function Calling 是一回事吗？**（不是，见 29 的概念分层）
- 结构化输出失败后怎么处理？
- 工具调用为什么必须做安全治理？
- 面试里怎么一句话概括结构化输出？

## AI 应用评测（答案见 [07](07-ai-evaluation.md)）

- 为什么不能只靠公开 benchmark 评估 AI 应用质量？
- Golden Set 应该怎么构建？冷启动阶段没有生产日志怎么办？
- LLM-as-Judge 有哪些主要偏差？怎么缓解？
- **RAG 评测为什么必须分检索和生成两段？**
- **Agent 评测为什么比普通问答和 RAG 更复杂？**
- 离线评测、Trace 回放、线上灰度分别解决什么问题？
- CI 里的 AI 评测如何平衡速度和覆盖度？
- 如果 LLM-as-Judge 和人工评测结果不一致，应该怎么处理？

## 综合场景题（原文 5 条）

- 客服机器人历史会话持续增长时，如何分配 Token 预算并保留关键业务状态？
- 流式响应中途断开后，服务端如何处理重试、续传和重复计费？
- 上游模型触发 RPM 或 TPM 限制时，模型网关如何排队、降级或切换模型？
- **模型生成退款工具的调用参数后，业务系统还需要执行哪些校验？**
- 更换模型或修改 Prompt 后，如何用离线评测、Trace 回放和线上灰度验证效果？

## 对 009 的落点

综合场景题第 4 条**几乎就是 ServiceFlow 的原题**："模型生成退款工具的调用参数后，业务系统还需要执行哪些校验？"009 的现成答案是一条可指向源码的链路：

```
intent.py 解析出结构化意图（Pydantic 校验形状）
  → policies.py 判定业务合法性（7 天期限、500 元阈值、状态转换）
  → case_service.py 执行副作用（唯一的写入边界）
  → read_final_state 回读数据库确认终态
```

关键论点：`agent/tools.py` 只是受限门面，模型给的字段**不能覆盖**服务端重新读取的订单状态和金额判定；高额退款走 `interrupt()` 暂停 + 同 `thread_id` 的 `Command(resume)` 恢复，审批结果同样落库后回读。

评测那一组的"Agent 评测为什么比问答和 RAG 更复杂"也能用 009 的真实数据回答：009 同时断言意图、政策路由、工具选择和数据库终态四层，而 `docs/PORTFOLIO.md` 里保留的 `clarify_exchange_order_001` 正是"终态碰巧一致但政策路由错误"的案例——**这就是为什么最终状态指标不能取代政策和工具指标**。

需要如实承认的空白：Streaming/SSE、限流、模型网关、Trace 回放、线上灰度这几组，009 **没有实现也没有真实经历**。009 只有 `infrastructure/timing.py` 的 Server-Timing 分阶段埋点，那是延迟观测，不是网关或灰度。

## 关键词

调用链路题库、Temperature=0 不可重复、Streaming 不省成本、限流多维度、Function Calling vs MCP vs Skill、Golden Set、LLM-as-Judge 偏差、检索/生成分段评测、退款参数二次校验。
