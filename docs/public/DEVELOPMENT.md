# ServiceFlow 本地开发与运行

## 前置条件

- Docker Desktop 已启动；
- Python 3.12；
- `uv`（用于 Python 依赖和测试）；
- 一个兼容 OpenAI Chat API 的模型配置。软件测试使用 Fake Model，不需要真实 API Key。

## 环境变量

```powershell
Copy-Item .env.example .env
```

编辑 `.env`：

```text
SERVICEFLOW_API_KEY=你的本机模型密钥
SERVICEFLOW_BASE_URL=https://api.deepseek.com
SERVICEFLOW_MODEL=deepseek-v4-flash
```

不要把真实密钥写入源码、截图、日志、评测结果或 Git 提交。`.env` 已被 `.gitignore` 忽略。

## 启动后端和数据库

```powershell
docker compose build
docker compose up -d
Invoke-RestMethod http://127.0.0.1:8009/api/v1/health
Invoke-RestMethod -Method Post http://127.0.0.1:8009/api/v1/demo/reset
```

查看日志：

```powershell
docker compose logs -f api
docker compose logs -f mysql
```

停止服务：

```powershell
docker compose down
```

默认数据库数据保存在 Docker volume 中。`docker compose down -v` 会删除该模拟数据库卷，请确认不需要保留数据后再执行。

## 启动前端

在项目根目录另开一个终端：

```powershell
python -m http.server 5173 --bind 127.0.0.1 --directory frontend
```

浏览器访问 <http://127.0.0.1:5173/>。

## 运行软件测试

```powershell
Set-Location backend
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

测试代码按 `unit`、`integration`、`api`、`agent` 和 `evals` 分组。测试默认使用 SQLite 临时数据库和 Fake Model，避免把软件测试绑定到网络或真实模型。

## 运行异步全链路压力测试

压力测试使用项目现有的基础 40 案和复杂中文 60 案。每个案例代表一个独立用户，
所有用户共享同一个 FastAPI 应用、LangGraph、异步 SQLAlchemy 会话工厂和数据库；模型
使用确定性的异步回放实现，因此不会产生外部模型费用：

```powershell
Set-Location backend
uv run serviceflow async-stress
```

默认并发档位是 `1 10 25 50 100`，也可以缩小范围：

```powershell
uv run serviceflow async-stress --level 10 100
```

结果写入 `outputs/evaluation/serviceflow-async-pressure.json` 和 Markdown 报告。报告中
同时记录业务通过数、HTTP 错误、吞吐量、P50/P95/P99 延迟和模型回放峰值并发。

### 真实 Docker、MySQL 和 DeepSeek 压力测试

上面的压力测试不调用外部模型，适合日常回归。如果需要验证真实部署链路，可以运行
下面的入口。运行前先确认 `docker compose up -d` 已启动，并且根目录 `.env` 中的模型
配置可用：

```powershell
Set-Location backend
uv run python -m serviceflow.evaluation.real_stress `
  --level 1 10 50 100 `
  --output-stem serviceflow-real-deepseek-100
```

它会使用现有 100 个案例、真实 Docker API、真实 MySQL 和真实 DeepSeek，并从 MySQL
重新读取每个案例的终态。每个案例使用独立临时订单，测试完成后自动清理本轮临时数据。
这个命令会产生模型调用费用，报告输出到 `outputs/evaluation/`。

测试 300 个并发用户时，将 100 个案例重复三次：

```powershell
uv run python -m serviceflow.evaluation.real_stress `
  --repeat 3 --level 300 `
  --output-stem serviceflow-real-deepseek-300
```

真实报告中的 `passed/failed` 检查业务决策、工具轨迹和数据库终态；错误分类会把模型
语义不匹配与 HTTP、超时、限流、传输错误分开记录。

### 量化 MySQL 查询优化

数据库优化不能只看完整 Agent 请求的总耗时，因为真实 DeepSeek 响应通常远大于一次
MySQL 查询。使用下面的真实 MySQL 基准可以单独验证联合索引和 `LIMIT 1`：

```powershell
uv run python -m serviceflow.evaluation.database_benchmark `
  --history-rows 2000 `
  --noise-order-count 100 `
  --noise-rows-per-order 180
```

它会为一个目标订单创建 2000 条历史记录，并为其他订单创建噪声数据，然后将旧查询
与新查询各测多轮。输出中应重点查看：旧计划是否有 `Using filesort`，新计划是否命中
`ix_*_order_created_at`，返回行数是否从全部历史记录降为 1，以及 P95 是否下降。

## 运行固定案例评测

评测案例位于根目录 `tests/eval_cases/`。运行器会逐案重建模拟数据库、发送消息、读取数据库终态，并将结果输出到本地 `outputs/evaluation/`：

```powershell
Set-Location backend
uv run serviceflow eval `
  --cases ..\tests\eval_cases\serviceflow_v1.jsonl ..\tests\eval_cases\serviceflow_v1_complex_60.jsonl `
  --output ..\outputs\evaluation `
  --output-stem serviceflow-v1-local
```

评测输出默认被 Git 忽略，因为其中包含本次模型名称、耗时、Token 和逐案运行元数据。公开仓库只保存可复现的案例输入和期望结果。

## 常用检查

```powershell
docker compose ps
docker compose config
Invoke-RestMethod http://127.0.0.1:8009/api/v1/health
Invoke-RestMethod http://127.0.0.1:8009/api/v1/orders/ORDER-001
```

## 端口说明

```text
前端：127.0.0.1:5173
API：127.0.0.1:8009 → 容器内 8000
MySQL：127.0.0.1:33069 → 容器内 3306
```

这里的端口映射只服务于本机演示，不代表生产部署方案。
