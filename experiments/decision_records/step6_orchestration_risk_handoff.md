# Step 6 编排、风控与人工接管决策记录

日期：2026-09-04。状态：实现完成，学习闭环待用户口头验收。

## 结论

1. Answerability 使用代码级五路结果：继续、补问、查询状态、拒绝、转人工。模型可以提出动作，不能把无证据答案说成确定事实。
2. Tool Executor 必须显式绑定部署租户；订单和 Operation 在执行前再次做资源归属检查。未知资源和越权资源都不返回业务字段。
3. 所有写工具先确认；高金额退款继续使用模拟的 ¥500 审批线。确认绑定用户、租户、参数 SHA-256 和 15 分钟有效期；审批只能由服务端受信 `approver` 角色执行。
4. Handoff 是持久业务记录，不是回复文案：写入 `support_queue`，同时追加 `handoff_created` 审计事件；原因和上下文先做邮箱、手机号及敏感字段脱敏。
5. API 正式使用 `SqlAlchemyCheckpointSaver` 和持久 Session，替换 `InMemorySaver` 与进程内会话字典。checkpoint 仍只是恢复上下文，订单、审批、Operation 和 Handoff 的数据库记录才是业务事实。
6. 角色只做有限职责标记，继续使用单 Agent 和既有 Tool Loop 跳数预算，不创建 Multi-Agent swarm。

## 证据

- Step 6 窄验收：31 passed，覆盖权限、确认、退款/补偿动作绑定、Answerability、Handoff、Provider UNKNOWN、防篡改和 API 重启恢复。
- 最终全量回归：232 passed / 1 skipped / 160.67s。
- `uv run ruff check .` 与 `git diff --check` 通过。
- Compose 重建成功，`/api/v1/health` 返回 `ok`，MySQL 中存在 `support_queue`。
- 创建会话 `demo-09d01f7f508a` 后重启 API，仍可按同一 thread_id 从 SQL 读取。

## 代价、失效条件与回滚

- SQL checkpoint 和每次会话查询增加数据库 I/O；如果恢复延迟不可接受，先测量再优化，不能退回不持久且对外宣称可恢复。
- 15 分钟确认有效期是安全起点，不是实验最优值；出现合法用户频繁过期时再做单变量对照。
- 当前 `serviceflow-demo-approver` 是本地演示身份，不是企业 IAM。接真实身份系统前不得写成生产审批权限。
- Policy 缺证据和 Provider UNKNOWN 会保守转人工，可能产生误转；Step 9 必须同时报告违规率和误拦截/误转率。
- 可关闭 Native route 回到 V1 固定图；Handoff 表和审计记录保留，不能通过删除记录“回滚”。

## Bad Case

1. 第一次接入租户门禁时，旧测试因 Executor 没有显式部署租户而全部得到 `unauthorized`。修正为构造 Executor 时强制提供租户，不让调用方通过请求上下文自行声明可信租户。
2. Compose 重启虽然成功恢复 SQL 会话，但退出时出现 `aiomysql RuntimeError: Event loop is closed`。根因是旧 `on_event` 只负责启动、不关闭连接池；改为 FastAPI lifespan 后，在关闭阶段显式 dispose 自有数据库 Engine。
3. 高金额补偿最初会沿用退款审批恢复分支。现在 Approval 绑定具体 `RequestedAction`，补偿审批只创建支持工单；回归断言退款表为 0。

## 未扩大到 Step 7/8 的边界

- 没有实现真实 Provider、Webhook、Outbox、Worker、自动 reconcile 或重试。
- 没有实现企业 IAM、真实审批人目录、生产 SLA 或在线安全评分。
- `UNKNOWN` 当前只能生成对账 Handoff；自动查询 Provider 并推进终态属于 Step 7。
