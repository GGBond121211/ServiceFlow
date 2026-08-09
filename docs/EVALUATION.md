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

最终固定 40 个案例：

| 类别 | 数量 | 示例 |
|---|---:|---|
| 正常处理 | 16 | 查询、取消、退款、换货、创建工单 |
| 业务边界 | 10 | 已发货不能取消、超过期限、不同金额审批分支 |
| 信息补充 | 6 | 缺少订单号、缺少诉求、多轮补充后继续 |
| 自然语言变体 | 8 | 口语、简写、同义表达、顺序变化 |

评测集不包含 Prompt 注入、恶意输入、越权攻击、工具故障、网络故障和其他安全或故障注入案例。

## 5. 案例格式

目标文件：`tests/eval_cases/serviceflow_v1.jsonl`

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

完成作品集评测。建议目标：

- 40/40 案例成功执行并生成报告；
- Task Outcome Accuracy 不低于 80%；
- Final State Accuracy 不低于 85%；
- Policy Routing Accuracy 不低于 90%；
- 审批分支案例正确率为 100%；
- 每个失败案例都有简短、可核验的原因分类。

如果真实模型未达到建议值，必须展示真实结果和限制，不能伪造或只选择成功案例。
