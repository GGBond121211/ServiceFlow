# 10｜多 Agent 协作系统设计

来源：[JavaGuide 原文](https://javaguide.cn/ai/agent/multi-agent.html)

## 什么时候需要多 Agent

多 Agent 不是“多调几个模型”。独立 Agent 应有清晰的目标、上下文、工具、权限或验收标准，并产出可交接的结果。若只是固定的连续调用，Prompt Chain 或 Workflow 更简单。决定拆分前，先尝试缩小工具、改善 Schema、隔离上下文和增加确定性路由。

适合拆分的信号是：角色专业性不同、工具权限不同、任务可并行、上下文互相污染、输出需要独立评审，或单 Agent 已有可重复失败样本。代价包括编排复杂度、Token/延迟、状态一致性、故障传播、Trace 和评测难度。

## 编排模式

常见结构包括顺序、并行、Router、Supervisor、Handoff、Evaluator/Generator、群体讨论和事件驱动。文章以研究任务为例：研究员顺序取资料，技术和舆情角色并行，管理者汇总；外层是 DAG，角色内部可以有 ReAct Loop。成功条件应明确，例如关键研究结果齐全且至少一条辅助分支有效，而不是只看所有 Agent 是否返回 200。

## 契约、通信与状态

每个子任务应有类似 `AgentTask` 的契约：任务 ID、父任务、角色、输入、依赖、允许工具、输出 Schema、最大迭代、超时、deadline 和 attempts。结果至少包含结构化数据、证据/来源、产出时间、缺失项和置信度。原始大材料不要无边界写入共享上下文，应该通过 artifact/reference 传递。

状态可分 RoleState 与 AgentRunState；分布式场景还要有 owner、版本、lease 和 fencing。生命周期要区分 PENDING、READY、RUNNING、WAITING_INPUT、SUCCEEDED、RETRYABLE_FAILED、FINAL_FAILED、CANCELED。消息传播用显式 TaskContext，不依赖不可见 ThreadLocal；跨服务可采用结构化任务协议或 A2A，但协议不能替代业务权限和一致性。

并发冲突要区分状态冲突、事实冲突、所有权冲突和副作用冲突，用 slot/CAS/lease/fencing/幂等控制；失败处理要有预算、checkpoint、远端超时 UNKNOWN、部分成功/法定人数和补偿。补偿是业务动作，不等同于数据库回滚。

## 对 009 的落点

当前售后路径的工具和策略边界相对集中，没有证据表明需要多 Agent。2.0 若要加入“客服理解/政策检索/业务执行/质量评审”等角色，应先写任务契约和失败样本，明确哪些角色可以读写什么，最后由确定性编排器汇总；不能用多 Agent 掩盖单 Agent 的 Schema、检索或状态问题。

## 关键词

DAG、Supervisor、Handoff、Parallel、AgentTask、RoleResult、A2A、lease、fencing、部分成功、补偿、Trace。
