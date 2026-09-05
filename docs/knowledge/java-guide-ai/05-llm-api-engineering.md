# 05｜大模型 API 调用工程实践

来源：[JavaGuide 原文](https://javaguide.cn/ai/llm-basis/llm-api-engineering.html)

## 调用生命周期

文章把一次 API 调用拆成：业务鉴权与输入大小 → 上下文组装 → Token 预算 → Gateway 路由 → Provider 调用 → 文本/Delta/finish/tool/usage 解析 → 状态写入 → 观测与成本记录。核心思想是把供应商 SDK 细节收口，让业务层依赖稳定的内部请求/响应契约。

## 同步、流式和异步

同步适合短任务；流式适合聊天、长答案和需要首字反馈的交互；异步适合长文档、多工具任务、批量评测和需要排队/恢复的工作。SSE、WebSocket、chunked response 不是同一个概念：SSE 是事件格式和单向连接，WebSocket 是双向协议，实际边界要在网关和前端实现中固定。

流式处理要维护事件边界、序号、累积文本和结束原因。遇到用户取消、TTFT 超时、总超时、断流或半截 JSON，不能把已发送片段当作完整成功；重连要避免重复发送。工具调用和结构化响应最好在完整事件收齐并校验后再执行。

## 重试、幂等和限流

网络瞬断、部分 5xx、可退避的 429 可以有限重试；400、401、403、安全拒答等通常应直接失败或转业务流程；结构化解析失败可在同一 Schema 下做有限修复。指数退避应受最大次数和 deadline 限制，不能让每层客户端各自重试导致倍增。

写工具需要 `message_id/attempt_id/provider_request_id/sequence` 等记录，稳定的幂等键应由服务端按租户、用户、业务动作和 attempt group 生成。超时未知时查询状态，不能把未知当失败后直接重放。限流要同时看用户、租户、模型、供应商、并发和 Token；429 的 Retry-After、排队、Fallback 和熔断需要统一策略。

## 结构化返回与观测

JSON Mode 主要保证语法，JSON Schema 描述结构，Structured Output/Function Calling 还要结合供应商支持和服务器验证。统一网关应记录 TTFT、总延迟、输入/输出/缓存 Token、重试、429、解析失败、取消和 Provider 错误，并将这些信息关联到 request/run/attempt。

## 对 009 的落点

ServiceFlow 当前代码路径需要保留自己的 Python/LangGraph 事实边界。若 2.0 要引入统一模型调用，先为当前单一场景补“请求、attempt、错误分类、结构化解析和观测”的最小闭环，不先引入完整 Java Gateway。涉及真实写操作时，把 UNKNOWN 和幂等作为业务状态设计的一部分。

## 关键词

SSE、WebSocket、TTFT、retry matrix、deadline、idempotency、429、rate limit、stream sequence、Provider Adapter。
