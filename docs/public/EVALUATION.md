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

## V1 冻结基线

以下是 V1 的**唯一权威基线**，2026-09-02 冻结，作为 2.0 全部改动的固定对照。

**可复现坐标**

| 项 | 值 |
| --- | --- |
| 提交版本 | `1e4f429` |
| 发布标签 | `v1.0.1`（`c7d61fd`） |
| 模型 | `deepseek-v4-flash` |
| Prompt 版本 | `service_agent_v1` |
| 思考模式 | `SERVICEFLOW_THINKING_MODE=enabled` / `REASONING_EFFORT=high` |
| 运行时间 | 2026-08-11T14:06:37Z |
| 案例集 | `serviceflow_v1.jsonl`（40 条）+ `serviceflow_v1_complex_60.jsonl`（60 条）= 100 条 |
| 完成情况 | 100 / 100 |

**指标**

| 指标 | 结果 |
| --- | ---: |
| Outcome Accuracy | 95.00% |
| Final State Accuracy | 98.00% |
| Policy Accuracy | 95.00% |
| Tool Accuracy | 98.00% |
| Clarification Rate | 91.67% |
| 平均单案耗时 | 5640.25 ms |
| Token | 输入 41791 / 输出 62639 |

演示服务在没有本地 `outputs/evaluation/` 报告时，会使用镜像内的公开基线摘要；本地生成的报告存在时优先使用本地结果。

**按难度分区**

| 分区 | 案例数 | 任务结果 | 最终状态 | 政策 | 工具 | 澄清 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 核心 40 案 | 40 | 97.50% | 97.50% | 97.50% | 97.50% | 100.00% |
| 复杂中文 60 案 | 60 | 93.33% | 98.33% | 93.33% | 98.33% | 88.89% |

**保留的 5 个失败案例**（不删除、不修改期望值）

| 案例 ID | 失败原因 |
| --- | --- |
| `refund_high_rejected_001` | 把"退掉"解析为 `cancel`，路由到 `POL-TICKET-01` |
| `blend_query_expired_refund_001` | 把超期退款请求解析为纯 `query`，未创建应有工单 |
| `correct_final_exchange_001` | 意图识别为 `exchange` 正确，政策路由错到 `POL-TICKET-01` |
| `multi_exchange_order_001` | 同上，且多轮澄清未完成 |
| `multi_refund_to_exchange_001` | 同上，且多轮澄清未完成 |

后三例是同一种失败模式：**换货意图识别正确、政策路由错误，但两条路径都产出工单，`ticket_open` 终态碰巧一致**。这说明最终状态指标不能取代政策和工具指标。

**复现命令**

```powershell
Set-Location backend
uv run serviceflow eval `
  --cases ..\tests\eval_cases\serviceflow_v1.jsonl ..\tests\eval_cases\serviceflow_v1_complex_60.jsonl `
  --output ..\outputs\evaluation
```

**边界声明**：以上数字来自**自建模拟数据**上的**本地单次运行**，使用真实模型 API。它不是生产 SLA、不代表线上流量表现、也不是人工语义评分。原始报告与逐案结果在本地 `outputs/evaluation/` 生成（不入库），可用上面的命令复现。更完整的能力与限制说明见 [`BOUNDARIES.md`](BOUNDARIES.md)。

> 同日更早还有一次 40 案单独运行（Clarification 83.33%、平均 3729.63 ms、失败 2 例）。那是**历史对照**，案例集不同，两套数字不可混用。

## 软件测试与真实模型评测

软件测试使用 Fake Model 和 SQLite，保护领域规则、仓储、API、工具和图路由；真实模型评测需要本机 `.env` 中存在模型配置。两者目的不同：前者验证代码行为，后者观察自然语言理解和多轮状态合并效果。

## 可复现运行

```powershell
Set-Location backend
uv run python -m pytest -q --basetemp=../work/pytest-public-evaluation
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

## 2.0 Step 9 baseline 边界

2.0 Step 9 已完成工程 baseline 收口，但没有把参考默认值写成质量最优结论：

- V2 当前为 132 条，Policy RAG 为 103 条文档和 28 条查询；holdout 16 条保持锁定；
- BM25 `1.2/0.75`、RRF `60`、Qdrant `M=16`、政策条款边界、rerank `10→5` 和 Tool Loop `5/12`
  是当前 baseline 的参考默认值；内部实验配置和逐次结果不纳入公开仓库；
- `reference-only`、`measured-smoke-only` 和 `untested` 分开标记；
- dev/regression 拆分、完整 V2 逐案质量 Runner、FPR 扩展、模型/参数 A/B、Policy 语料扩充和大规模
  并发实验延期到 2.1+。

因此，本项目不会声称“V2 总体准确率已证明”“某模型客观最优”“总体 FPR ≤2%”或“生产可靠性已验证”。
普通 CI 使用 Fake/确定性测试；真实模型评测必须显式触发并单独报告模型、数据集、Token、延迟和成本。

数据库改造需要用独立的 SQL 基准量化。下面的实验仍连接真实 MySQL，但不调用模型，
这样可以把联合索引和 `LIMIT 1` 的收益从模型网络耗时中隔离出来：

```powershell
Set-Location backend
uv run python -m serviceflow.evaluation.database_benchmark `
  --history-rows 2000 `
  --noise-order-count 100 `
  --noise-rows-per-order 180
```

## 分阶段耗时与模型首 Token

API 在每个响应的 `Server-Timing` 头中记录模型调用、LangGraph、数据库连接、SQL、业务
规则和响应组装耗时。`real_stress.py` 会把这些阶段聚合成平均值、P50、P95 和最大值。

模型流式探针用于继续拆分收到响应头、首 Token（TTFT）和首 Token 后生成：

```powershell
docker compose exec -T api python -m serviceflow.evaluation.model_latency `
  --iterations 5 --concurrency 1 --output /tmp
```

DeepSeek V4 的思考模式可通过 `SERVICEFLOW_THINKING_MODE` 控制，思考强度通过
`SERVICEFLOW_REASONING_EFFORT` 控制。模式切换必须同时比较延迟和业务通过率，不能只用
速度决定默认配置。

它在目标订单和其他订单混合的数据分布上，对比旧单列索引与新联合索引的 `EXPLAIN`、
`Using filesort`、实际返回行数、平均耗时和 P95。实验完成后删除所有临时记录。
