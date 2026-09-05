# Step 10 部署与故障排障记录（2026-09-05）

## 1. Collector readiness 故障

### 现象

第一次执行 `docker compose up -d --build` 时，应用镜像构建成功，MySQL、Redis、Qdrant、Jaeger、
双 Gateway 和 Proxy 可启动，但 Compose 报 `otel-collector is unhealthy`，因此 API、Prometheus
和 Grafana 没有继续按依赖启动。

### 定位命令与观察

```bash
docker compose ps -a
docker compose logs --tail=160 otel-collector
docker inspect project-0009-serviceflow-otel-collector-1 --format '{{json .State.Health}}'
```

Collector 日志显示 `Everything is ready. Begin running and processing data.`；Docker health 日志
显示探活命令 `wget` 不存在。替换成 `otelcol-contrib validate` 后仍失败，进一步发现该 distroless
镜像的二进制路径是 `/otelcol-contrib`，不是 PATH 中的 `otelcol-contrib`。

### 根因与修复

根因是健康检查假设了镜像内有 wget/PATH 命令，和实际镜像内容不一致，不是 OTLP receiver 或
Collector pipeline 配置错误。最终改成：

```yaml
test: ["CMD", "/otelcol-contrib", "validate", "--config=file:/etc/otelcol-contrib/collector.yaml"]
```

并让 API、Gateway、Worker 等应用在 Collector healthy 后启动。随后 Compose 完整启动成功，
Collector healthy，API/Gateway/Worker 的 OTLP export 不再出现新的启动期错误。

## 2. Gateway 副本故障切换

### 验证步骤

```bash
docker compose stop gateway-a
curl --fail http://127.0.0.1:8010/health
docker compose up -d --wait gateway-a
docker compose ps gateway-a gateway-b gateway-proxy
curl --fail http://127.0.0.1:8010/health
```

停止 `gateway-a` 后 Proxy 返回 `{"status":"ok","instance":"gateway-b"}`；恢复命令完成后
`gateway-a` 回到 healthy，Proxy 再次返回健康响应。验证只覆盖本地 Nginx upstream 故障切换，
不代表生产 HA 或跨节点容灾。

## 3. 防复发

- 运行时健康检查必须使用目标镜像真实存在的命令；Collector 配置另用显式 `validate` 检查；
- Compose 依赖使用 `service_healthy`，应用 readiness 与进程存活分开；
- CI 保留 `docker compose config --quiet`、镜像构建和配置渲染检查；
- 故障恢复后同时检查容器状态、入口 health、Prometheus target 和 Jaeger service，而不是只看单个 200；
- Collector、Jaeger、Prometheus、Grafana 和双 Gateway 仅为本地演示组件，生产环境仍需专门的鉴权、
  持久化、容量、告警和回滚方案。

## 4. Worker Smoke 中发现的 Redis 配置缺口

### 现象

Compose 全部服务健康后，第一次从 API 容器执行 Fake Outbox smoke 时，任务投递失败并尝试连接
`localhost:6379`。API 容器内的默认 Redis 地址不是 Compose 网络中的 `redis` 服务。

### 根因与修复

Worker 已配置 `SERVICEFLOW_CELERY_BROKER_URL` 和 `SERVICEFLOW_CELERY_RESULT_BACKEND`，但 API
容器没有传入这两项，Celery 因而使用了代码默认值。修复是在 Compose API environment 中补齐：

```yaml
SERVICEFLOW_CELERY_BROKER_URL: redis://redis:6379/1
SERVICEFLOW_CELERY_RESULT_BACKEND: redis://redis:6379/2
```

重建 API 后，Fake Outbox smoke 成功：`OUT-F95B36506250` 为 `sent`、`attempt=1`；Worker 日志
记录任务成功，Jaeger 可查询 `serviceflow-worker` Trace，Prometheus `serviceflow_worker_up=1`。

这说明第一次失败是部署环境配置缺口，不是业务 Outbox 或 Worker 逻辑失败；配置检查和 Worker smoke
被保留在最终验收清单中。
