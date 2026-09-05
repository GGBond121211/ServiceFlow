# ServiceFlow 2.0 作品集交付口径

## 30 秒

ServiceFlow 是一个模拟电商售后 Agent：模型只负责理解自然语言，Python 政策、权限、确认审批、
幂等和数据库终态负责业务正确性。2.0 在此基础上加入 MCP Tool Loop、Policy RAG、Gateway、异步
Outbox/Worker、Trace 和可复现 Compose/Kubernetes 交付。

## 3 分钟

请求从 API 进入后，通过 SQL Session/checkpoint 恢复多轮 Goal/Case；模型可以通过原生 Function
Calling 选择 MCP 查询工具，但所有工具都经过租户/资源 ACL，写操作需要确认，高金额动作需要审批。
订单和 Operation 的最终事实回读 MySQL，Policy RAG 只提供带版本的证据。Gateway 负责路由、有限
重试、fallback、熔断、限流和 Token/成本/延迟审计；UNKNOWN 不被误报成功，而进入 query/Webhook/
人工对账路径。Celery Worker 投递 Outbox，OTel Collector/Jaeger 和 Prometheus/Grafana 提供本地
排查入口。

2.0 Step 9 采用参考默认值作为 baseline，未声称模型或参数最优。V2 为 132 条、Policy RAG 为
103 条文档/28 条查询；完整质量 A/B、FPR 扩展和大规模并发实验延期到 2.1+。

## 10 分钟追问主线

| 追问 | 回答锚点 |
| --- | --- |
| 为什么模型不能直接退款？ | 模型输出意图；政策/权限/确认/审批/CaseService 才能产生副作用，终态必须回读数据库 |
| 为什么用 MCP？ | Tool/Resource/Prompt discovery 与 ToolResult 形成真实工具边界；安全门禁仍在 Executor，不在 Prompt |
| 如何避免重复扣款？ | 稳定 actionId、参数指纹、唯一约束、行锁；timeout 进入 UNKNOWN，不直接 execute 重试 |
| 如何定位慢请求？ | traceparent 串起 API→Gateway→MCP→DB→Outbox→Worker；Prometheus 观察低基数请求指标 |
| 2.0 参数是最优的吗？ | 不是。baseline 配置明确标记 `reference-only`/`measured-smoke-only`/`untested`，重型实验排到 2.1+ |
| 这是生产系统吗？ | 不是。Provider、订单、支付、物流和审批主体都是模拟；Compose 双副本和 kind 只用于本地演示 |

## Trace 展示位

最终本地验收应保存三张 Jaeger 瀑布图：

1. 正常多轮售后：API → Gateway → MCP Tool → MySQL；
2. Provider UNKNOWN：Operation → TaskEnvelope → Worker reconcile；
3. Gateway 副本故障：Nginx → fallback Gateway，并显示故障原因。

截图只在真实 Compose Trace 查询后落盘；没有生成截图前不把它们写成已交付证据。
