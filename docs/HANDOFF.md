# 新对话交接

## 1. 当前事实

- 项目目录：`C:\Users\Alex\Desktop\workspace\Project-0009-ServiceFlow`
- 项目已完成初始化和规划，没有实现任何业务代码。
- 当前完成点：Task 00。
- 下一步：实施计划中的 Task 01。
- 项目所有数据和政策均为模拟内容。
- 项目目标是本科生 Agent 开发实习作品集，不是生产系统。

## 2. 新对话必须读取

1. `README.md`
2. `AGENTS.md`
3. `docs/STATUS.md`
4. `docs/PROJECT_CONTEXT.md`
5. `docs/BOUNDARIES.md`
6. 当前 Task 涉及的文档
7. `.hermes/plans/2026-08-09_125127-serviceflow-implementation.md` 中的当前 Task

不要依赖旧聊天记录推断项目状态。

## 3. 每个 Task 的执行协议

1. 先确认 `docs/STATUS.md` 中唯一的下一 Task；
2. 只读取和修改该 Task 列出的文件；
3. 先写能证明该业务行为的失败测试；
4. 运行最窄测试确认失败原因正确；
5. 实现最小代码；
6. 运行当前测试、相关回归和 Ruff；
7. 只更新因真实行为变化而过时的文档；
8. 更新 `docs/STATUS.md` 的完成项、验证结果和下一 Task；
9. 达到当前 Task 验收条件后停止，不提前实现后续 Task。

如果工作树已有用户修改，必须保留并绕开，不得重置。

## 4. 项目特别边界

- 不增加安全、防攻击、权限、风控和安全测试；
- 不增加重试、熔断、缓存、复杂恢复和高可用；
- 不把普通业务状态判断误写成生产安全体系；
- 不增加多 Agent、Redis、消息队列、Kubernetes、向量数据库和复杂 RAG；
- 不把计划写成已完成事实；
- 不接真实订单、支付、物流和客户数据；
- 不为尚未实现的 Prompt 创建注册表或多个版本。

## 5. 给新对话的推荐首条消息

```text
请读取当前 Project-0009-ServiceFlow 的 README.md、AGENTS.md、docs/STATUS.md、docs/HANDOFF.md 和详细实施计划。按照计划只执行当前的 Task 01，完成测试和最窄验证后更新 STATUS 并停止，不要提前实施 Task 02，也不要加入安全、防御性代码或计划外基础设施。
```

后续每次可以把 `Task 01` 替换成 `docs/STATUS.md` 记录的下一 Task。

## 6. 项目完成时需要展示的证据

- 三条浏览器端到端流程；
- PostgreSQL 中可核验的最终业务状态；
- LangGraph 真实条件分支和审批恢复；
- 40 案固定评测报告；
- Docker Compose 启动方式；
- 真实失败案例和限制；
- 两个简历项目之间的能力互补说明。
