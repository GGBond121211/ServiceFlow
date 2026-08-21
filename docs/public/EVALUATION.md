# ServiceFlow 评测说明

## 评测目标

评测不只检查模型回复是否通顺，而是检查 Agent 是否走对业务路径，并把模拟数据库更新为预期最终状态。

每个案例都声明：

- 初始订单状态；
- 用户消息（一条或多轮）；
- 期望的结构化意图；
- 期望的政策和工具；
- 订单、退款、工单或审批的最终状态。

运行结束后，评测器从数据库重新读取最终状态，不把 Agent 的自然语言自称当作业务事实。

## 案例数据

固定案例位于 [`tests/eval_cases`](../../tests/eval_cases)：

- `serviceflow_v1.jsonl`：核心业务、边界和信息补充案例；
- `serviceflow_v1_complex_60.jsonl`：复杂中文、多轮状态、隐含诉求、否定改口和歧义请求案例。

所有用户、订单、金额和日期都是项目自建模拟数据，不来自真实企业系统。

## 主要指标

| 指标 | 含义 |
| --- | --- |
| Outcome Accuracy | 业务决策和结果是否都符合期望 |
| Final State Accuracy | 数据库最终状态是否完全符合期望 |
| Policy Accuracy | 是否匹配正确的确定性政策 |
| Tool Accuracy | 是否调用了正确且必要的业务工具 |
| Clarification Rate | 信息不足时是否先追问，并在补充后继续完成 |
| Latency / Token | 本地运行耗时和模型用量，用于工程观察 |

## 软件测试与真实模型评测

软件测试使用 Fake Model 和 SQLite，保护领域规则、仓储、API、工具和图路由；真实模型评测需要本机 `.env` 中存在模型配置。两者目的不同：前者验证代码行为，后者观察自然语言理解和多轮状态合并效果。

## 可复现运行

```powershell
Set-Location backend
uv run pytest -q
uv run serviceflow eval `
  --cases ..\tests\eval_cases\serviceflow_v1.jsonl ..\tests\eval_cases\serviceflow_v1_complex_60.jsonl `
  --output ..\outputs\evaluation `
  --output-stem serviceflow-v1-local
```

评测输出在本地生成并被 Git 忽略。不要为了提高分数删除失败案例或修改案例期望答案；应保留失败并从意图提取、状态合并、政策判断或工具边界中寻找原因。

## 异步压力测试

除了逐案评测，还可以运行异步全链路压力测试：

```powershell
Set-Location backend
uv run serviceflow async-stress
```

它把基础 40 案和复杂中文 60 案合并为 100 个逻辑用户，在 1、10、25、50、100 个并发
档位下通过 HTTP API 顺序完成各自的多轮对话。所有用户共享一个应用、LangGraph 和
异步数据库会话工厂；每个用户使用独立的模拟订单，避免不同案例互相修改业务事实。

压力测试使用确定性的异步回放模型，重点观察异步数据库、Agent 图、审批恢复、HTTP
接口和并发调度，不代表真实模型的语义准确率。真实模型的语义评测仍然使用上面的
`serviceflow eval` 命令。

## 真实 Docker + MySQL + DeepSeek 压力测试

实验分支还提供真实运行链路的压力测试入口。它不是回放模型：请求经过 Docker 中的
FastAPI、LangGraph、异步 SQLAlchemy 和 MySQL，Agent 再由 API 容器中的异步 DeepSeek
模型适配器完成理解。评测器最后直接从 MySQL 重新读取订单、退款、工单和审批状态。

```powershell
Set-Location backend
uv run python -m serviceflow.evaluation.real_stress `
  --level 1 10 50 100 `
  --output-stem serviceflow-real-deepseek-100
```

300 并发的运行方式是把 100 个案例重复三次，形成 300 个独立的临时用户和订单：

```powershell
uv run python -m serviceflow.evaluation.real_stress `
  --repeat 3 --level 300 `
  --output-stem serviceflow-real-deepseek-300
```

该命令会真实消耗模型额度。测试结束后会删除本轮创建的临时业务记录，但保留原有演示
数据。报告额外区分 `business_mismatch`、HTTP 错误、限流、超时和传输错误，避免把
“模型理解错了”和“服务根本没响应”混成一个失败数字。

数据库改造需要用独立的 SQL 基准量化。下面的实验仍连接真实 MySQL，但不调用模型，
这样可以把联合索引和 `LIMIT 1` 的收益从模型网络耗时中隔离出来：

```powershell
Set-Location backend
uv run python -m serviceflow.evaluation.database_benchmark `
  --history-rows 2000 `
  --noise-order-count 100 `
  --noise-rows-per-order 180
```

它在目标订单和其他订单混合的数据分布上，对比旧单列索引与新联合索引的 `EXPLAIN`、
`Using filesort`、实际返回行数、平均耗时和 P95。实验完成后删除所有临时记录。
