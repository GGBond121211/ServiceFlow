# 27｜AI 可观测性与 Trace

来源：[JavaGuide 原文](https://javaguide.cn/ai/system-design/ai-observability.html)

## 五类信号

Metrics 发现整体异常，Logs 记录离散事件，Trace 还原一次调用，Evaluation 判断质量，Audit 追踪身份/审批/外部副作用。接口返回 200 不代表答案、检索或工具正确；RAG、Agent 和多次重试需要执行级证据。

Session 是多轮会话，Run 是一次跨暂停/恢复的任务，Trace 是一次实际执行链，Span 是链路中的阶段，Attempt 是某一步的第几次尝试。长任务等待人工时结束当前 Trace，用 runId 串起后续新 Trace，而不是保持数小时的开放 Span。

## Span 与字段

合理根 Span 可是 `agent.run`/`invoke_workflow`，子 Span 覆盖意图、RAG query/vector/rerank、模型、tool、下游 HTTP、输出校验和子 Agent。只为外部调用、重要阶段、独立超时/重试/成本/质量或真实排障对象建 Span；普通字符串拼接不必单独记录。Span 名称要低基数，订单号和用户问题放受控属性或 Hash，不要放名称。

Trace 元数据至少覆盖服务/环境/版本、Session/Run/租户、Agent/Workflow/Prompt/知识库版本、模型/参数/输入输出/缓存 Token、TTFT/总延迟/finish/error/retry、RAG 文档 ID/版本/分数/过滤/重排、工具版本/参数摘要/权限/审批/幂等/结果和业务状态。子 Agent 完成不等于汇总使用，要记录聚合输入清单。

低基数（model、role、tool、status、environment）适合 Metrics；高基数（user/session/doc/tool call/response ID）只进 Trace；完整 Prompt/Completion/工具结果还要考虑体积、隐私和敏感数据，默认保存版本、摘要和 Hash。

## 指标、传播、采样

请求层看 QPS、成功/超时/取消/降级、P50/P95/P99、TTFT/总耗时；模型层看调用、429、Token、成本、重试/Fallback；RAG 看空召回、有效文档、重排/构建耗时、截断和引用；Agent/工具看调用/迭代、重复/无效/拒绝、业务失败、人工接管、部分成功和缺失结果。阈值按场景基线而非统一固定值。

跨线程要显式传播上下文，跨 HTTP/RPC/消息队列用 W3C Trace Context；流式异步路径尤其要用集成测试确认父子关系。头部采样便宜但不知道结果，尾部采样可保留错误/慢/高 Token/高风险 Trace 但需 Collector 暂存；生产可低比例基础采样加异常/审计独立保留。Audit 不能跟普通 Trace 采样一起丢。

线上 Badcase 回流：告警/反馈 → 定位 Trace → 人工确认与脱敏 → 数据集 → 固定版本回放 → 修复 → 灰度 → 继续观察。复现原问题要固定模型、Prompt、文档快照、工具结果、随机/超时；验证新版本则比较质量、延迟和成本。

## Spring/Java 提醒与对 009 的落点

文章以 Spring AI 2.0.0/Spring Boot 4.x 的观测配置为例，强调版本会变；框架自动埋点之外仍要补 Agent Run、RAG、重排、工作流路由、输出校验、审批恢复和业务结果。测试要覆盖同步、流式、跨线程、虚拟线程、消息队列、工具失败和敏感数据。当前 009 不是 Java/Spring AI 项目，2.0 若引入观测应先定义 request/run/attempt 和业务状态，不直接复制版本敏感配置。

## 关键词

Metrics、Logs、Trace、Evaluation、Audit、Session/Run/Trace/Span/Attempt、低/高基数、W3C Trace Context、Tail Sampling、Badcase 回流。
