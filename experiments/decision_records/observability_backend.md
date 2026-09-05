# Step 10 可观测后端决策（2026-09-05）

## 选择

2.0 本地交付选择 **OpenTelemetry Collector + Jaeger all-in-one + Prometheus + Grafana**：

- Jaeger 用于展示 API、Gateway、MCP Tool、数据库、Outbox 和 Worker 的 Trace 关系；
- Prometheus 用于抓取 API、两个 Gateway 和 Worker 的低基数指标；
- Grafana 提供请求层、模型/路由层和 Worker 状态的最小面板；
- Collector 将应用与 Trace 后端解耦，后续可以替换 Jaeger 或增加并行导出。

## 为什么不把 Langfuse 作为 2.0 主后端

Langfuse 更贴近 LLM 观测，但本项目第十步首先要证明可迁移的 OTel/分布式追踪能力，且当前 Provider 全为 Fake、没有生产 Prompt 管理需求。Jaeger 的通用 Trace UI 更适合作为本地作品集证据。未来若需要 LLM 专用视图，可以并行导出，不替换当前 Jaeger 链路。

## 证据与限制

- 配置文件：`ops/otel/collector.yaml`、`ops/jaeger/README.md`、`ops/prometheus/prometheus.yml` 和 Grafana dashboard；
- 应用指标只使用 method/status 等固定维度，不使用 orderId、caseId、sessionId 或用户输入作为 label；
- Jaeger、Prometheus 和 Grafana 都是本地 Compose 组件，不代表生产持久化、容量、鉴权或 HA；
- 当前应用保留内存 exporter，同时在 Compose 设置 OTLP endpoint；测试环境未设置 endpoint 时不会产生外部网络依赖；
- OTel 只保存可审查字段和结果，不保存模型隐藏推理。

回滚方式：移除 Compose 中的观测服务和 OTLP endpoint，应用继续使用内存 Trace exporter；业务请求、数据库事实和独立审计表不依赖 Jaeger 是否可用。
