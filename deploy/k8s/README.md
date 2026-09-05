# 本地 Kubernetes 验证

这些 manifest 面向 kind/Minikube 的本地演示和学习，不是云端生产集群、跨节点 HA、Service
Mesh 或多区域部署。MySQL 使用 `emptyDir`，集群删除后数据会消失；正式环境必须替换为受管
数据库、Secret 管理、持久卷、迁移工具和备份策略。

## kind 最短路径

```bash
kind create cluster --name serviceflow
docker build -t serviceflow:2.0.0 ./backend
kind load docker-image serviceflow:2.0.0 --name serviceflow
kubectl apply -k deploy/k8s/base
kubectl -n serviceflow rollout status deployment/mysql --timeout=180s
kubectl -n serviceflow rollout status deployment/api --timeout=180s
kubectl -n serviceflow rollout status deployment/gateway --timeout=180s
kubectl -n serviceflow rollout status deployment/worker --timeout=180s
kubectl -n serviceflow port-forward service/api 8009:8000
curl http://127.0.0.1:8009/api/v1/health
```

API readiness 会等待应用 lifespan 完成建表和 Policy prepare；Gateway readiness 是进程健康，
Worker readiness 是 metrics HTTP 端口。这个区分避免把“容器活着”误当成“业务依赖已就绪”。

## 故障与回滚演示

```bash
kubectl -n serviceflow delete pod -l app=gateway --wait=false
kubectl -n serviceflow get pods -w
kubectl -n serviceflow rollout undo deployment/gateway
kubectl -n serviceflow rollout status deployment/gateway --timeout=120s
kubectl -n serviceflow logs deployment/api --tail=100
```

Kubernetes 只负责本地进程编排。Session、Case、Operation 和 checkpoint 的事实仍在 MySQL，
Redis 只做缓存和短期协调；Secret 文件中的值是占位符，不能用于真实 Provider。
