# ServiceFlow 2.0 运维 Runbook

以下命令以 Linux/WSL2 为准。诊断顺序是“编排状态 → 服务日志 → 端口/依赖 → readiness → Trace/指标”，
避免只看一个 HTTP 500 就猜业务根因。

## API 起不来

```bash
docker compose ps
docker compose logs --tail=100 api
ss -tlnp | grep -E ':8009|:8010'
curl -i http://127.0.0.1:8009/api/v1/health
docker compose exec mysql mysqladmin ping -h 127.0.0.1 -userviceflow -pserviceflow --silent
docker compose exec redis redis-cli ping
curl -sS http://127.0.0.1:6333/readyz
```

`/api/v1/health` 成功表示 API lifespan 已完成当前初始化；容器 `Up` 只表示进程没有退出。

## Worker 卡住或任务积压

```bash
docker compose ps worker
docker compose logs --tail=200 worker
docker compose exec redis redis-cli -n 1 LLEN celery
docker compose exec redis redis-cli -n 1 DBSIZE
docker compose exec worker python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:9101/metrics').read().decode())"
docker compose restart worker
```

业务 TaskEnvelope 的 lease、deadline、attempt 和死信状态在 MySQL；Worker metrics 端口只证明进程
存活，不把进程存活当成任务全部成功。

## Redis 挂掉

```bash
docker compose stop redis
docker compose logs --tail=100 api gateway-a gateway-b
curl -i http://127.0.0.1:8009/api/v1/health
curl -sS http://127.0.0.1:8010/health
docker compose start redis
docker compose ps
```

Redis 只负责缓存、Gateway 限流/并发短期协调和 Celery broker；MySQL 仍是业务事实源。协调租约失败
不能覆盖已经取得的模型成功响应，恢复后用 TTL 或重启清理短期状态。

## 磁盘、内存和日志

```bash
df -h
du -sh . .git
free -m
docker system df
docker stats --no-stream
docker compose logs --tail=200 --no-log-prefix api gateway-a gateway-b worker
```

本地 Compose 使用 Docker 日志驱动的默认轮转策略，正式环境必须在 Docker daemon 或日志系统配置
max-size/max-file，并对 Jaeger/Prometheus 数据卷设置保留策略。看到 OOM 时先看 `docker stats`、
主机 `dmesg -T | grep -i -E 'oom|killed process'`，再决定是否降低并发或扩容。

## Trace 与指标联动

```bash
curl -sS http://127.0.0.1:8009/metrics
curl -sS http://127.0.0.1:9090/api/v1/query --get \
  --data-urlencode 'query=serviceflow_worker_up'
docker compose logs --no-log-prefix api | grep -o '"trace_id":"[^"]*"' | tail
```

把响应头里的 `traceparent` 或日志中的 `trace_id` 粘到 Jaeger UI 搜索；当前指标只使用 method/status
等固定标签，不把 orderId、caseId、sessionId 或用户输入放入时间序列。

## 发布失败与回滚

```bash
docker compose ps
docker compose logs --tail=200
SERVICEFLOW_PREVIOUS_IMAGE=ghcr.io/OWNER/REPO:v1.0.1 ./ops/scripts/rollback.sh
```

回滚后重新执行 healthcheck 和只读订单查询；不要在回滚过程中删除 MySQL 数据卷。

## Step 10 故障排障记录

第十步的部署与 Gateway 故障验证收敛为本文件中的可复制诊断命令；内部排障过程和逐次
postmortem 不纳入公开仓库。当前文档中的命令是可复制的诊断基线，不是生产 SLO。
