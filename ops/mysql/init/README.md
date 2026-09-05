# MySQL 初始化边界

ServiceFlow 当前在 API/Gateway lifespan 中通过 SQLAlchemy 幂等创建缺失表和索引，Compose
只负责提供 MySQL 8.4 与健康检查。这里保留说明目录，避免把一次性 SQL 初始化脚本误认为
正式迁移系统。

启动验证：

```bash
docker compose exec mysql mysqladmin ping -h 127.0.0.1 -userviceflow -pserviceflow --silent
docker compose exec api python -c "from serviceflow.api.dependencies import engine; print(engine.url)"
```

生产环境应引入受版本控制的迁移工具和备份/恢复流程；本项目 2.0 不把本地自动建表写成
生产迁移能力。
