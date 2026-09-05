# ServiceFlow 2.0 本地部署

本文面向 Linux、WSL2 或 macOS 上的本地演示。它证明的是可复现的 Compose/Kubernetes 交付
链，不是生产部署指南。所有订单、用户、政策和 Provider 都是模拟数据。

## Compose 最短路径

```bash
cp .env.example .env
# .env 只放本机配置；默认测试和 Compose 业务链使用 Fake Provider/Fake Model
docker compose config --quiet
docker compose build
docker compose up -d
./ops/scripts/healthcheck.sh http://127.0.0.1:8009/api/v1/health 120
docker compose ps
```

首次启动时 API/Gateway 会等待 MySQL、Redis、Qdrant 和 Gateway Proxy 的健康状态；API lifespan
会幂等创建当前演示所需的表和索引。测试数据可用 POST 请求重置：

```bash
curl -X POST http://127.0.0.1:8009/api/v1/demo/reset
```

## 服务入口

| 组件 | 地址 | 用途 |
| --- | --- | --- |
| API | `127.0.0.1:8009` | 业务 API 与 `/metrics` |
| Gateway Proxy | `127.0.0.1:8010` | 双 Gateway 的本地反向代理 |
| Jaeger | `127.0.0.1:16686` | Trace UI |
| Prometheus | `127.0.0.1:9090` | 指标查询 |
| Grafana | `127.0.0.1:3000` | ServiceFlow Overview 面板 |
| MySQL | `127.0.0.1:33069` | 本地业务事实库 |
| Qdrant | `127.0.0.1:6333` | Policy RAG 证据层 |

API、Gateway 和 Worker 的 Span 通过 OTLP 送入 Collector，再由 Collector 导出到 Jaeger；应用
仍保留内存 exporter，所以没有 Collector 的单元测试不依赖外部服务。

## 构建、日志和停止

```bash
docker compose logs --tail=100 api gateway-a gateway-b worker
curl http://127.0.0.1:8009/metrics
curl http://127.0.0.1:9090/-/ready
docker compose down
```

`down` 默认保留 MySQL/Qdrant/观测数据卷。只有明确要清空本地演示数据时才使用
`docker compose down -v`。

## 镜像与回滚

Compose 同时支持本地 build 和不可变镜像 tag：

```bash
SERVICEFLOW_IMAGE=ghcr.io/OWNER/REPO:v2.0.0 docker compose pull
SERVICEFLOW_IMAGE=ghcr.io/OWNER/REPO:v2.0.0 docker compose up -d --no-build --force-recreate
SERVICEFLOW_PREVIOUS_IMAGE=ghcr.io/OWNER/REPO:v1.0.1 ./ops/scripts/rollback.sh
```

回滚脚本会先检查上一镜像存在，再强制重建服务并轮询 API readiness；失败时不会删除数据库卷。

## CI/CD 边界

普通 `ci.yml` 默认只跑 Fake/确定性测试、lint、compile smoke、Docker build 和 Compose config。
`real-eval.yml` 只有手动触发时才读取 GitHub Secret `SERVICEFLOW_API_KEY`；不把 key 写进仓库，
也不让普通 PR 消耗真实模型额度。`release.yml` 只对 `v*.*.*` tag 发布不可变 GHCR 镜像。

## Kubernetes

本地 kind/Minikube 说明见 [`../../deploy/k8s/README.md`](../../deploy/k8s/README.md)。manifest 使用
占位 Secret、`emptyDir` MySQL 和本地镜像，不能直接当生产配置。
