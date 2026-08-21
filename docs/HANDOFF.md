# ServiceFlow V1 维护入口

## 1. 当前事实

- 项目目录：`C:\Users\Alex\Desktop\workspace\Project-0009-ServiceFlow`
- V1 的 Task 00—17 已完成，当前没有下一实施 Task。
- 项目是本科生 Agent 开发实习作品集，所有用户、订单、金额、政策和处理结果均为模拟内容。
- 核心业务、Agent、API、MySQL、Compose、浏览器页面和100案评测均有真实验证证据。
- V1 停止点已达到，不继续增加多 Agent、Redis、向量数据库、安全体系或计划外基础设施。

## 2. 维护时读取顺序

1. `README.md`
2. `AGENTS.md`
3. `docs/STATUS.md`
4. 本文件
5. `docs/DEVELOPMENT.md`
6. 与变更直接相关的产品、架构、评测或边界文档
7. 与变更直接相关的代码和测试

不要依赖聊天记录推断状态，也不要把旧实施计划中的目标当成当前未完成事项。

## 3. 已冻结证据

- 全量软件测试：连接 Compose MySQL 后 `59 passed`，仅有 1 条既有迁移警告；
- Ruff 与格式：通过，51 个文件格式正确；
- Compose：`mysql` 与 `api` 两个服务构建和运行成功；
- HTTP：health、demo reset、ORDER-001 查询成功；
- 浏览器：取消、小额退款、高金额审批退款三条流程成功；
- MySQL：高金额流程最终为订单 `refunded`、退款 `completed`、审批 `approved`；
- 真实评测：40/40 执行，Outcome 95.00%、Final State 97.50%、Policy 95.00%、Tool 97.50%、Clarification 83.33%；
- 失败案例：`refund_high_rejected_001`、`clarify_exchange_order_001`，均保留在完整报告中。
- 第一阶段扩展评测：核心40案加复杂中文60案，100/100执行；总体 Outcome 95.00%、Final State 98.00%、Policy 95.00%、Tool 98.00%、Clarification 91.67%。
- 难度差异：核心40案 Outcome 97.50%，复杂中文60案 Outcome 93.33%；复杂分区4条失败集中于单句主诉求选择、否定后的问题类型和多轮问题类型保留，完整证据未删改。

## 4. 运行入口

- 开发、测试、Compose、评测和 Docker 排障：`docs/DEVELOPMENT.md`
- 架构与状态边界：`docs/ARCHITECTURE.md`
- 评测方法和真实结果：`docs/EVALUATION.md`
- 作品集、简历 bullet 和面试问题：`docs/PORTFOLIO.md`
- 完整结果：`outputs/evaluation/serviceflow-v1-results.json`
- 可读报告：`outputs/evaluation/serviceflow-v1-report.md`
- 当前100案结果：`outputs/evaluation/serviceflow-v1-100-results.json`
- 当前100案报告：`outputs/evaluation/serviceflow-v1-100-report.md`

## 5. 后续变更协议

V1 已结束。若用户提出新功能，先判断它是：

- 对 V1 的明确缺陷修复：写失败测试，做最小修复和相关回归；
- 文档或演示维护：只更新真实过时内容；
- 新产品阶段：先重新定义范围、风险、Task 和验收条件，不能直接沿用已完成的 Task 17。

继续保留以下边界：不接真实支付、物流、商城和客户数据；不增加登录、权限、生产安全、风控、安全测试、重试、缓存、Redis、消息队列、Kubernetes、多 Agent、向量数据库和复杂 RAG。

## 6. 当前运行状态

Task 17 最终验收完成后，Compose 容器和临时前端服务器均应停止；MySQL 数据卷保留。模型密钥只存在于用户环境变量，不在仓库中。
