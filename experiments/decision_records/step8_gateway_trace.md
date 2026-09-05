# Step 8 / 8.1：LLM Gateway、降级、限流与统一 Trace

## 当前选择

- 业务层继续依赖 `StructuredModel` / `NativeToolModel`，由 Gateway 实现协议；Compose 中 API 通过 OpenAI-compatible HTTP 访问双 Gateway + Nginx。
- `deepseek-v4-flash` 是默认主模型和当前首选设计；`gpt-5.6-luna` 是通过 JSON、中文售后和 Native Tool Calling 小规模 smoke 的候选备用，不是质量或成本冠军结论。
- 五类 Route Profile 当前版本为 `step8.1-v1`。普通首轮先走 `operation-plan`；模型若提出退款或补偿工具，必须由只含主模型的 `high-risk-review` 重新生成计划，只有复核结果才进入确定性 ToolExecutor。能力不足或不可用时转人工，模型不能绕过确认和审批。
- 仅 429、5xx、timeout、连接失败和非法/不可解析响应允许有界重试或换模型。其他 4xx 归为 `bad_request`，认证、权限、Policy、安全、确认、审批、幂等和业务校验错误禁止 fallback。
- Redis Lua 令牌桶按真实 route/tenant 限流，并带最大并发 lease；当前队列上限明确为 0，并发满或 Redis 不可用立即 backpressure。lease 释放失败会告警并靠 TTL 恢复，不丢弃已经付费取得的成功响应。
- Gateway HTTP 要求 Bearer 服务密钥和 `x-serviceflow-tenant-id`；Compose 宿主机端口只绑定 `127.0.0.1:8010`。内部 Trace/Metrics 端点同样鉴权。
- Streaming 本轮明确延期：`stream=true` 返回 422，不静默伪装支持。原因是当前 Tool Calling 与结构化输出必须拿到完整响应并校验后才能执行；SSE 用户体验与 TTFT 实测留 Step 10。

## 数据与依据

原始结果：`experiments/results/step8-gateway-trace-2026-09-05.json`、`step8-frontier-model-capability-smoke-2026-09-05.json` 和 `step8-1-hardening-2026-09-05.json`。

- Step 8 新增窄测 25 项；发布前最终全量回归为 271 passed / 1 skipped / 230.26 秒。
- Frontier `/v1/models` 返回 18 个模型 ID，但不返回 ◆ 价格。两模型共 4 次真实能力调用：DeepSeek 输入/输出 507/652 tokens，Luna 704/115 tokens；两者 JSON、中文 next_action、`get_order` Native Tool Calling 均通过。
- 双 Gateway 健康检查四次交替命中 a/b/a/b；停 a 后完整 API 只读查询仍成功。修正 Nginx timeout 后，代理约 2594.11ms 切到 b。
- MySQL 观察到 4 条 `gateway_model_call` 全量审计记录。价格未核实时 `estimated_cost=null`，不拿美元价格冒充 Frontier ◆。
- Step 8.1 新增/加强 11 项测试，最终窄验收 31 passed / 21.63 秒；最终全量为 282 passed / 1 skipped / 274.79 秒，Ruff 与 Compose 配置通过且无测试 warning。
- Step 8.1 Compose 实况：API、两个 Gateway、Nginx、Worker、MySQL、Redis、Qdrant 全部运行；四次健康请求命中 a/b/a/b；未鉴权 Metrics 返回 401，鉴权后返回 `{"routes":{}}`；本轮没有模型调用。
- 用户登录后的 Frontier 控制台显示两模型均为 1M 上下文。每百万 Token 的输入/输出/缓存 ◆ 单价：DeepSeek 12/36/0.3996，Luna 1.5/12/0.18。该数据证明 Luna 当前标价更低，不证明任务质量更好。

## Trace、日志与审计边界

- 使用 OpenTelemetry SDK 和 W3C Trace Context；Step 8.1 测试不再只手工嵌套 Span，而是真实调用 API、ModelGateway、Fake 模型 Provider、MCP ToolExecutor、SQLite、Outbox 与 Worker，并断言同 traceId 及 Worker 父 Span。
- GenAI 属性锁定 `1.37.0-experimental`，请求模型与实际响应模型分开；RAG 分别记录 recall、rerank、最终入 Prompt 的文档 ID。
- JSON 应用日志只记 trace/span、route、model、provider、错误类和 attempt；不记 Prompt 原文、工具参数明文、隐藏推理和密钥。
- `event_log` 继续作为独立全量审计表，不由 Trace 采样决定。Gateway 模型审计现保存 tenant/request/session/goal/case/operation/run/trace 字段；采样率为 0 的测试仍能按 operationId 读到审计记录。
- Gateway 运行时 Metrics 按低基数 Route 聚合请求、attempt、成功/失败、fallback、429、解析失败、Token、成本、平均/P95 延迟、TTFT 和模型分布，并可直接把分布送入路由漂移计算。当前是每副本内存聚合，不是 Prometheus 后端。
- 当前实现是父子一致的可配置头部采样；按结果保留错误/高成本请求需要 Collector 尾部采样，留到 Step 10 与 Jaeger/Collector 一起完成，不能把本地内存 exporter 写成生产 Trace 后端。

## 代价、失效条件与回滚

- 双本地副本增加镜像、代理、Redis 与数据库连接；仍共享 Frontier 故障域。Frontier 平台整体失败时只能进入 manual/backpressure，不能称 Provider 容灾。
- `gpt-5.6-luna` 只有小 smoke。若 Step 9 固定案例质量不达标、◆ 成本不低或上下文限制不兼容，从 fallback 链移除。
- 默认 attempts=2、deadline=20s、bucket=60、并发=8、queue=0、熔断阈值=3 都是受测起点，不是优化结论。
- 回滚：移除 `SERVICEFLOW_GATEWAY_URL` 可回到进程内 Gateway；再关闭 Gateway builder 可临时回到单模型 `OpenAICompatibleModel`。高风险业务门禁、Operation 幂等与数据库终态回读不随网关回滚。

## 真实 Bad Case

1. 停掉 gateway-a 后代理健康请求卡 15 秒；API 最终成功但切换延迟不可接受。定位到 Nginx 隐式连接超时，加入 2 秒 connect timeout 和最多两次 next-upstream，复测 2594.11ms 命中 gateway-b。
2. Redis smoke 把 acquire/release 放进两个 `asyncio.run`，连接绑定旧事件循环而失败。改为同一事件循环后获取、释放都成功；这是验证命令错误，不是限流器业务缺陷。
3. 验收审计发现 limiter 与 GatewayAuditWriter 都把租户写死为 `default`。修复为 API ContextVar → HTTP Header → Gateway record → Redis key/MySQL Event Log 显式传播，并增加 tenant-a 断言。
4. 旧 `test_otel_trace_chain` 直接创建所有 Span，只证明 OTel API 可嵌套。新测试改走真实组件链；外部模型仍使用 Fake，避免把可观测性测试变成付费且不稳定的网络测试。
5. Generic Provider 4xx 曾被归为 `invalid_response` 并允许 fallback。现把 400/404/422 等归为不降级的 `bad_request`，同时将 HTTP 状态分别映射为 400/401/403/422/429/502/503/504。
