# Step 7：Provider、幂等、Outbox 与异步恢复

日期：2026-09-04

## 选择

- Provider 统一为 canonical request/response；当前只提供可脚本化的 Fake Provider，不接真实支付、物流或客服系统。
- timeout、429、5xx 才允许有限重试和换备用 Provider；鉴权、参数、政策、权限、安全错误直接失败，不能借 fallback 绕过门禁。
- 副作用动作使用稳定 `actionId/idempotency_key`、参数指纹、数据库唯一约束和行锁。相同键同参数重放已有 Operation；相同键换参数拒绝。
- Provider timeout 且结果不确定时进入 `UNKNOWN`，只允许 query、Webhook 或人工对账推进，禁止再次 execute。
- ProviderEventInbox 以 `(provider,event_id)` 去重；业务状态与 Outbox 在同一事务提交；Outbox 发送使用行锁，重复投递读取 `sent` 后直接返回。
- Celery + Redis 当前承载 Outbox 投递；SQL TaskEnvelope 承载 Provider reconcile 的持久任务契约、lease、deadline、死信/人工队列与审计。Worker 不依赖内存闭包。

## 证据

- 20 路并发同请求：一个 Operation、一次 Fake Provider execute、一个副作用键；参数变化被拒。
- timeout outcome-unknown：Operation 进入 UNKNOWN，query 对账成功后变为 SUCCEEDED，execute 次数仍为 1。
- 5xx：主 Provider 最多 2 次后切备用；permission 错误不重试、不 fallback。
- 重复 Webhook 和重复 Outbox 均只推进/发送一次。
- Worker 停止时任务进入 Redis，重启后消费成功；同一消息再次投递后 MySQL `attempt=1`，`outbox_delivered` 审计事件计数仍为 1。
- 最终全量回归：246 passed / 1 skipped；Ruff 通过。

原始坐标：`experiments/results/step7-provider-async-recovery-2026-09-04.json`。

## 代价、边界和失效条件

- 当前 Provider 是 Fake，实现证明故障语义和事务契约，不证明真实供应商集成经验、可用性或资金安全。
- Celery 只实际承载 Outbox；Provider reconcile 已有可持久服务与任务契约，但尚未绑定周期调度。Step 8 再把 trace context restore 为真实 OpenTelemetry span。
- SSE 是 Step 7 的可选项，本轮没有实现；高风险动作成功仍只认数据库 Operation/业务终态。
- 默认每 Provider 2 次尝试、Task 最多 3 次、5 分钟 deadline 是安全起点，不是参数实验结论。
- 如果真实 Provider 不支持幂等键或状态查询，不能直接接入高风险动作；必须进入人工对账或换支持该契约的 Provider。

## 回滚

停用 `worker` 服务和 ProviderOperationService 调用路径即可停止新增异步任务；保留 Operation、Inbox、Outbox、Task 与审计表中的历史数据。不能通过回滚重新执行 UNKNOWN 动作。
