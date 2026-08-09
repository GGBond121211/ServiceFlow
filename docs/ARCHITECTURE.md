# 目标架构

> 本文描述项目完成后的目标结构。当前仓库尚未实现这些模块，实际进度只以 `docs/STATUS.md` 为准。

## 1. 架构原则

1. 使用模块化单体，不拆微服务。
2. 一个 LangGraph Agent 足够完成 V1。
3. LLM 负责语言理解、结构化意图和自然语言回复；确定性代码负责业务规则、数据库写入和结果判定。
4. Agent 只能调用显式业务工具，不直接访问 SQLAlchemy Session。
5. 先在 SQLite 上学习和运行快速测试，最终演示使用 PostgreSQL。
6. 前端只通过 HTTP JSON API 调用后端。
7. Docker Compose 最终只编排 `api` 和 `postgres` 两个服务。

## 2. 目标组件

```text
Browser UI
    |
    | HTTP JSON
    v
FastAPI routes
    |
    v
Conversation application service
    |
    v
LangGraph service agent
    |-- intent extraction (LLM)
    |-- deterministic policy decision
    |-- tool selection and execution
    |-- approval interruption/resume
    `-- response generation (LLM)
            |
            v
Business tools
    |-- get_order
    |-- cancel_order
    |-- request_refund
    |-- create_ticket
    |-- create_approval
    `-- get_case_status
            |
            v
SQLAlchemy repositories
            |
            v
SQLite in fast tests / PostgreSQL in integration and demo
```

## 3. 目标目录

```text
Project-0009-ServiceFlow/
├─ AGENTS.md
├─ README.md
├─ compose.yaml
├─ backend/
│  ├─ pyproject.toml
│  ├─ uv.lock
│  ├─ Dockerfile
│  ├─ src/serviceflow/
│  │  ├─ __init__.py
│  │  ├─ cli.py
│  │  ├─ config.py
│  │  ├─ domain/
│  │  │  ├─ models.py
│  │  │  ├─ policies.py
│  │  │  └─ results.py
│  │  ├─ application/
│  │  │  ├─ order_service.py
│  │  │  ├─ case_service.py
│  │  │  └─ conversation_service.py
│  │  ├─ infrastructure/
│  │  │  ├─ database.py
│  │  │  ├─ tables.py
│  │  │  ├─ repositories.py
│  │  │  └─ seed.py
│  │  ├─ agent/
│  │  │  ├─ state.py
│  │  │  ├─ model.py
│  │  │  ├─ tools.py
│  │  │  ├─ graph.py
│  │  │  └─ prompts/
│  │  │     └─ service_agent_v1.txt
│  │  ├─ api/
│  │  │  ├─ app.py
│  │  │  ├─ schemas.py
│  │  │  └─ routes.py
│  │  └─ evaluation/
│  │     ├─ models.py
│  │     ├─ runner.py
│  │     └─ report.py
│  └─ tests/
│     ├─ unit/
│     ├─ integration/
│     ├─ api/
│     ├─ agent/
│     ├─ evals/
│     └─ fixtures/
├─ frontend/
│  ├─ index.html
│  ├─ app.js
│  └─ styles.css
├─ docs/
├─ tests/
│  └─ eval_cases/
│     └─ serviceflow_v1.jsonl
├─ work/
└─ outputs/
   └─ evaluation/
```

目录在对应 Task 实际需要时创建；不提前生成空模块。

## 4. 业务与 Agent 分层

### Domain

保存订单、退款、工单、审批等纯业务对象和政策判断，不依赖 FastAPI、SQLAlchemy、LangGraph 或模型 SDK。

### Application

组合领域规则和仓储操作，提供 `cancel_order`、`request_refund`、`create_ticket` 等清楚用例。Agent 工具调用这一层，不直接操作 ORM。

### Infrastructure

保存 SQLAlchemy 表、Session、仓储实现和确定性种子数据。SQLite 与 PostgreSQL 共享同一业务接口，但不为未来数据库创建复杂适配器体系。

### Agent

保存 LangGraph 状态、模型调用、工具包装、Prompt 和图编排。状态只记录可审查字段，不保存模型隐藏推理。

### API

把应用用例和 Agent 会话暴露为 HTTP JSON，不包含业务判断。

### Evaluation

重置案例数据、运行 Agent、读取最终状态并生成 JSON/Markdown 报告。

## 5. LangGraph 状态

目标状态至少包含：

```text
conversation_id
user_id
user_message
intent
order_id
issue_type
requested_action
missing_fields
order_snapshot
matched_policy_id
decision
tool_events
approval_id
final_business_state
assistant_message
model_name
prompt_version
token_usage
```

V1 不增加长期记忆服务。多轮状态保存在普通会话表或 LangGraph 可用的数据库 checkpoint 中；实现时选择其中一个最短方案，不能同时维护两套状态。

## 6. 图节点

```text
START
  -> extract_intent
  -> need_more_info? ---- yes -> ask_for_info -> END
  -> load_order
  -> evaluate_policy
  -> select_action
       | cancel
       | direct_refund
       | approval_required -> wait_for_approval -> resume
       | create_ticket
       ` explain_only
  -> execute_tool
  -> read_final_state
  -> compose_response
  -> END
```

业务规则判断节点必须是确定性 Python 代码。模型不能自行决定订单状态转移是否合法。

## 7. 数据库

V1 计划表：

- `users`
- `orders`
- `order_items`
- `refunds`
- `tickets`
- `approvals`
- `conversations`
- `tool_events`

`tool_events` 用于演示和评测轨迹，不扩展成生产审计系统。数据库创建采用 SQLAlchemy metadata；V1 不引入 Alembic，除非开发过程中真的出现需要保留数据的第二版 schema。

## 8. 模型边界

- 使用 OpenAI-compatible Chat Completions/Responses 适配方式，与具体供应商解耦到一个小模块。
- API Key 只通过环境变量传入，不写入仓库。
- 软件测试使用 Fake Model，不调用网络。
- 只有真实 Agent 评测使用配置的模型。
- 第一个运行 Prompt 出现时才创建 `service_agent_v1.txt`；后续行为变化使用新文件，不覆盖旧版本。

## 9. Docker Compose

学习顺序分两步：

1. 先只用 Compose 启动 PostgreSQL，FastAPI 在宿主机运行；
2. 核心流程稳定后再加入 API 容器。

最终服务只有：

```text
postgres: postgres:16-alpine
api:      backend/Dockerfile
```

前端是静态文件，开发时使用 Python 静态服务器，不增加 Node 构建链或 Nginx 容器。
