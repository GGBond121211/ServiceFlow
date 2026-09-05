# ServiceFlow 2.0 面试讲法

## 第一层：功能

这是一个模拟电商售后 Agent。用户查询订单、物流、退换货或退款，系统通过受限工具完成查询或
创建业务请求，并把最终数据库状态返回给用户。2.0 的本地 Compose 可启动 API、双 Gateway、
Worker、MySQL、Redis、Qdrant、Collector、Jaeger、Prometheus 和 Grafana。

## 第二层：策略

- 模型只解析结构化意图；退款资格、金额、期限和状态转换留在 Python policy/domain；
- Policy RAG 只提供版本化证据，不决定退款金额；
- Native Tool Loop 的 ToolResult 会影响下一步，但 ToolExecutor 仍检查租户、资源、确认、审批、
  参数指纹和幂等；
- V1 100 案冻结基线与 V2 132 案工程集合分开。2.0 Step 9 的参数是 baseline，不是 A/B 最优结论。

## 第三层：工程落地

- MySQL 是业务事实源，SQL checkpoint 支持 API 重启恢复；
- Provider timeout 的结果未知时进入 UNKNOWN，通过 query/Webhook/人工对账推进；
- Gateway 统一 deadline、有限 retry/fallback、熔断、Redis 限流和审计；
- Outbox 与业务写入同事务，Celery Worker 负责投递；
- OTel 负责跨服务 Trace，Prometheus 只使用低基数标签，Grafana 提供最小面板；
- CI 默认 Fake，不消耗真实额度；手动 real-eval 才读取 GitHub Secret；镜像使用不可变 tag，脚本支持健康检查和回滚。

## 一个真实 Bad Case 的讲法

Step 10 的故障验收应使用实际日志和 Trace 完成“现象 → 命令 → 观察 → 根因 → 修复 → 防复发”叙述。
当前已知可讲的历史案例包括：Nginx upstream 默认重试导致故障切换超时，Redis lease 释放失败
不应覆盖模型成功响应，以及 Windows stdio 默认代码页导致中文协议解码失败。它们分别对应代理超时、
短期协调和跨进程编码边界；最终证据路径见 `experiments/decision_records/` 和 `experiments/results/`。

## 主动说明边界

- Fake Provider 不是真实支付/物流/客服 SaaS 集成；
- 本地双 Gateway、Jaeger、Prometheus、Grafana 和 kind/Minikube 不是生产 HA、合规 IAM 或真实 SLO；
- Step 9 的整体质量 A/B、FPR 统计上界、Policy 语料扩充和微调仍是 2.1+；
- 不保存模型隐藏推理，不让模型审批自己，不允许任意 SQL/Shell/网络工具。
