# Jaeger 本地 Trace 后端

Compose 中的 `jaeger` 使用 all-in-one 镜像，只用于本地开发和故障注入演示。
`api`、`gateway-a/b` 和 `worker` 通过 OTLP HTTP 把 Span 发给 `otel-collector`，Collector
再通过 OTLP gRPC 导出到 Jaeger。

启动后访问：<http://127.0.0.1:16686>

当前 Trace 只记录可审查的业务字段、模型/Token/路由和工具结果，不记录模型隐藏推理。
本地存储不是生产级持久化；正式环境应替换存储、保留策略、鉴权和容量配置。
