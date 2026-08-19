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
