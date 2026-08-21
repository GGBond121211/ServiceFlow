# 评测设计

## 1. 评测目的

ServiceFlow 的评测回答一个核心问题：给定确定的模拟订单状态和用户请求，Agent 能否选择正确业务路径，并把数据库更新为预期最终状态。

评测不依赖真实企业数据，也不以客服语言是否“像真人”为主要标准。

## 2. 软件测试与 Agent 评测

### 软件测试

保护确定性代码：领域规则、SQLAlchemy 仓储、FastAPI API、工具函数和图路由。软件测试全部使用 Fake Model，不访问真实模型网络。

### Agent 评测

使用真实配置模型运行固定案例，记录意图、工具轨迹、政策、最终状态、延迟和 Token。结果写入 `outputs/evaluation/`。

## 3. 数据来源

所有案例、订单和用户均为仓库自建模拟数据。每个案例声明初始状态和期望最终状态，因此不需要真实公司后台标签。

数据必须满足：

- 固定 ID 和固定日期；
- 不使用运行当天时间计算期限；
- 不依赖随机生成结果；
- 每个案例独立重置数据库；
- 规则和期望结果可由人工阅读核验。

## 4. V1 评测集

最终固定100个案例，按难度拆成两个文件分区，由一次 runner 合并执行：

- `tests/eval_cases/serviceflow_v1.jsonl`：核心40案；
- `tests/eval_cases/serviceflow_v1_complex_60.jsonl`：复杂中文60案。

| 类别 | 数量 | 示例 |
|---|---:|---|
| 正常处理 | 16 | 查询、取消、退款、换货、创建工单 |
| 业务边界 | 10 | 已发货不能取消、超过期限、不同金额审批分支 |
| 信息补充 | 6 | 缺少订单号、缺少诉求、多轮补充后继续 |
| 自然语言变体 | 8 | 口语、简写、同义表达、顺序变化 |
| 单句多语义 | 12 | 查询、抱怨、条件和最终动作杂糅 |
| 隐含诉求 | 10 | 不直接使用标准动作词 |
| 噪声背景 | 10 | 长背景中提取最终诉求 |
| 否定改口 | 10 | 区分被否定动作和最终动作 |
| 多轮状态 | 12 | 跨轮补充、保留和明确改口 |
| 歧义请求 | 6 | 不替用户猜测，应先追问 |

评测集不包含 Prompt 注入、恶意输入、越权攻击、工具故障、网络故障和其他安全或故障注入案例。

## 5. 案例格式

冻结文件：`tests/eval_cases/serviceflow_v1.jsonl` 与 `tests/eval_cases/serviceflow_v1_complex_60.jsonl`。

```json
{
  "id": "refund_high_value_001",
  "user_id": "USER-001",
  "initial_state": {
    "order_id": "ORDER-003",
    "status": "delivered",
    "amount": 899,
    "delivered_days_ago": 3
  },
  "messages": ["ORDER-003 的耳机有问题，我想退款"],
  "expected": {
    "intent": "refund",
    "policy_id": "POL-APPROVAL-01",
    "decision": "approval_required",
    "final_order_status": "delivered",
    "approval_status": "pending",
    "expected_tools": ["get_order", "create_approval"]
  }
}
```

多轮案例的 `messages` 保存按顺序输入的用户消息。

## 6. 主要指标

### Task Outcome Accuracy

`decision` 和业务结果都符合案例期望的案例比例。

### Final State Accuracy

数据库中的订单、退款、工单或审批最终状态完全符合预期的案例比例。这是主要指标。

### Policy Routing Accuracy

匹配到正确 `policy_id` 的案例比例。

### Tool Selection Accuracy

案例要求的业务工具是否被调用，以及是否出现与预期流程无关的额外业务工具。

### Clarification Completion Rate

信息不足案例中，Agent 是否先询问缺失信息，并在后续消息到达后完成任务。

### Cost and Latency

记录总 Token、模型调用次数和端到端耗时，只用于比较和面试说明，不设置生产 SLA。

## 7. 不作为主要指标的内容

- 单纯聊天语气；
- 模型自称“已经完成”；
- 测试覆盖率；
- LLM-as-a-Judge 的主观总分；
- 安全、攻击和高并发指标。

自然语言回复只检查是否包含处理结论、订单号和下一步三个必要字段，不要求固定句子。

## 8. 评测运行过程

1. 创建独立测试数据库或清空相关表；
2. 装载案例初始状态；
3. 按顺序发送用户消息；
4. 保存 Agent 结构化结果和工具事件；
5. 从数据库重新读取最终状态；
6. 用确定性断言计算指标；
7. 生成 JSON 明细和 Markdown 汇总；
8. 记录模型名、Prompt 版本、提交号和运行时间。

## 9. 里程碑

### EVAL-01

先冻结 10 个案例，跑通完整评测程序。此时只要求流程可运行，不设置成绩目标。

### EVAL-02

扩展到 40 个案例，修复真实失败并保留失败分析。不得修改案例期望结果来迎合模型。

### EVAL-03

作品集评测已完成。验收参考目标：

- 40/40 案例成功执行并生成报告；
- Task Outcome Accuracy 不低于 80%；
- Final State Accuracy 不低于 85%；
- Policy Routing Accuracy 不低于 90%；
- 审批分支案例正确率为 100%；
- 每个失败案例都有简短、可核验的原因分类。

真实结果和限制必须完整展示，不能伪造或只选择成功案例。

## 10. 当前冻结评测集与运行器

V1 的 40 个确定性案例已冻结在 `tests/eval_cases/serviceflow_v1.jsonl`：16 个正常处理、10 个业务边界、6 个信息补充和 8 个自然语言变体。首批 10 个案例的期望结果保持不变，新增案例同样通过种子订单引用、唯一 ID、枚举和 Task 03 政策重算校验。

`serviceflow.evaluation.runner` 会逐案重建数据库、按顺序发送消息、按案例声明恢复审批、从数据库重新读取最终状态，并计算 outcome、final state、policy、tool、clarification、latency 和 token 指标。`serviceflow.evaluation.report` 将完整明细写为 JSON，并生成包含指标和失败案例的 Markdown 报告。

运行命令：

```powershell
cd backend
uv run serviceflow eval --cases ..\tests\eval_cases\serviceflow_v1.jsonl --output ..\outputs\evaluation
```

软件测试、Fake Model 验证和真实模型 40 案评测均已完成。2026-08-11 最终刷新结果使用 `deepseek-v4-flash` 与 `service_agent_v1`：40/40 案执行完成，Task Outcome Accuracy 为 95.00%，Final State Accuracy 为 97.50%，Policy Routing Accuracy 为 95.00%，Tool Selection Accuracy 为 97.50%，Clarification Completion Rate 为 83.33%。总耗时 149185.29 ms，平均单案耗时 3729.63 ms，总输入 Token 14648，总输出 Token 13628。

最终保留两个失败案例：

- `refund_high_rejected_001`：模型把“退掉”解析为 `cancel` 而不是 `refund`，因此进入 `POL-TICKET-01` 并创建支持工单，没有进入退款审批拒绝分支。
- `clarify_exchange_order_001`：第二轮补充订单号时模型把问题类型解析为 `other`，覆盖了首轮的 `quality`，因此进入 `POL-TICKET-01`；最终订单和工单状态碰巧正确，但政策与信息补充路径错误。

完整逐案证据保存在 `outputs/evaluation/serviceflow-v1-results.json`，可读报告保存在 `outputs/evaluation/serviceflow-v1-report.md`。以上结果未经挑选，冻结案例的期望答案未修改。

## 11. 最终结论与限制

- Outcome、Final State、Policy 和 Tool 四项指标均超过 EVAL-03 参考目标；
- Clarification 为 83.33%，暴露了多轮补充时问题类型被新一轮模型结果覆盖的真实限制；
- 评测使用独立 SQLite 案例数据库以便逐案重建；最终浏览器验收另用 Compose MySQL 核验业务终态；
- 延迟和 Token 只描述本次本地网络与模型运行，不代表生产 SLA 或价格承诺；
- 所有案例、用户、政策、审批决定和数据库内容均为模拟数据。

## 12. V1 全中文复杂语义分区

第一阶段扩展冻结 `tests/eval_cases/serviceflow_v1_complex_60.jsonl` 的60条原创中文售后案例，与原核心40案共同组成V1 100案。该分区不用英文意图句，也不直接复制外部数据集；测试设计借鉴公开任务对话基准的单句多意图、动态对话状态、语言变体、目标改口和最终环境状态核验方法。

类别固定为：

- `blended_intent`：12条，一句话包含查询、抱怨、条件和最终动作等多个语义；
- `implicit_intent`：10条，不直接使用“取消/退款/换货”等标准命令；
- `noisy_context`：10条，在长背景和无关信息中提取最终诉求；
- `correction_negation`：10条，区分被否定、历史提及和最终改口的动作；
- `multi_turn_state`：12条，跨轮保留订单号、问题类型和动作，并允许明确改口；
- `ambiguous_request`：6条，不能替用户猜测，应追问且不得调用业务工具。

合同测试要求至少24条消息达到45个字符、至少12条为多轮、全部消息包含中文，并重新调用领域政策函数核验每个期望 `policy_id` 和 `decision`。该测试库先用于暴露真实模型能力，后续不得修改期望结果迎合模型。

面向用户的产品输出继续保持简洁；policy、tool、token、失败标签和详细轨迹属于评测证据，不默认展示在普通用户界面。

## 13. 真实模型100案结果

2026-08-11 使用未针对复杂60案调优的 `deepseek-v4-flash` 与 `service_agent_v1` 完整执行100/100案。运行命令：

```powershell
cd backend
uv run serviceflow eval --cases ../tests/eval_cases/serviceflow_v1.jsonl ../tests/eval_cases/serviceflow_v1_complex_60.jsonl --output ../outputs/evaluation --output-stem serviceflow-v1-100
```

| 分区 | 案例 | Outcome | Final State | Policy | Tool | Clarification |
|---|---:|---:|---:|---:|---:|---:|
| 核心40案 | 40 | 97.50% | 97.50% | 97.50% | 97.50% | 100.00% |
| 复杂中文60案 | 60 | 93.33% | 98.33% | 93.33% | 98.33% | 88.89% |
| 总体 | 100 | 95.00% | 98.00% | 95.00% | 98.00% | 91.67% |

分类别 Outcome：歧义追问100%、单句多语义91.67%、业务边界100%、信息补充100%、否定改口90%、隐含诉求100%、多轮状态83.33%、自然语言变体100%、噪声背景100%、正常处理93.75%。

100案全部完成模型调用，没有案例运行错误。总耗时564024.70 ms，平均5640.25 ms；输入41791 Token，输出62639 Token。失败5案：核心40案1条、复杂60案4条。

主要事实结论：长背景、隐含诉求和歧义追问均达到100%；仍然失败的是“查询背景中的最终退款”主诉求选择、“否定后换货”的问题类型，以及多轮换货时 `quality` 被后续订单号轮次覆盖为 `other`。复杂中文的主要短板是最终主诉求优先级和多轮字段合并，不能简单归因于领域政策或工具实现。

完整证据：`outputs/evaluation/serviceflow-v1-100-results.json` 与 `outputs/evaluation/serviceflow-v1-100-report.md`。原核心40案报告继续保留，便于比较评测扩展前后的结果。
