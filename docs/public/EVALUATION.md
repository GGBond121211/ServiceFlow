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
