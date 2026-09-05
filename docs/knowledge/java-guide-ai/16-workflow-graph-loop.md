# 16｜AI 工作流：Workflow、Graph 与 Loop

来源：[JavaGuide 原文](https://javaguide.cn/ai/agent/workflow-graph-loop.html)

## 三个层次

Workflow 描述“为了完成目标，任务怎样协作推进”；Graph 用 Node、Edge、State 表达结构；Loop 是 Graph 上由回边形成的控制模式。典型例子是“生成 → 审核 → 不达标则修改 → 再审核”。AI 工作流比线性 Prompt 多了运行时质量判断、状态驱动分支、失败降级和可恢复中间状态。

### Node、Edge、State

- Node 读取 State、执行一个职责并返回状态更新。
- Edge 可以是顺序、条件、动态路由、循环、终止或并行边。
- State 是节点之间共享的工作记忆，字段要有更新语义。

单值字段通常 Replace，消息和事件列表通常 Append；并行写入要使用明确 Reducer/合并规则，否则会出现竞态或覆盖。常见字段包括输入、消息、检索结果、工具结果、模型输出、中间步骤、下一节点和最终输出。

Loop 可是固定次数或条件驱动，通常还要叠加最大轮次、超时、Token/成本预算和熔断。嵌套 Loop 中，工具重试和质量迭代要有独立计数器和边界。一个可靠 Loop 同时写清继续条件、退出条件和安全边界。

## Java/Python 框架映射

文章用 Spring AI Alibaba Graph 与 LangGraph 对照：Java 侧可用 `OverAllState`、`KeyStrategyFactory`、`NodeAction`、条件边、编译器和 Saver；Python 侧可用 TypedDict、函数节点、条件边、reducer 和 checkpoint。人机协同可用中断与状态更新。示例中的 `MemorySaver` 只保证当前进程/同一实例范围，进程重启恢复需要 Redis/数据库等持久化 Saver，并验证序列化、过期与并发。

节点抽象应围绕职责边界（产出什么），边抽象合法流转（何时去哪），State 抽象必须持久记住的信息，而不是把每个 SDK 调用都画成节点。

## 错误和安全

瞬时网络/限流错误可有限退避；LLM 可恢复的工具/格式错误可以写入 State 回到修复节点；用户缺少信息可中断等待；未知异常应暴露给开发者。实际工程还要用熔断、舱壁和补偿，但这些不是 Graph 自动提供的。

模型输出进入路由、数据库、模板和工具前必须校验。特别要防 State 污染：恶意文本影响 `next_node` 等控制字段，绕过审核；也要防 Loop 放大攻击：让评估永远不通过，耗尽 Token。回放测试应覆盖正常退出、上限、超时、人工中断、认证失败和 checkpoint 恢复。

## 对 009 的落点

ServiceFlow 当前 LangGraph 售后路径可以用这套语言解释，但要保留已有 Python 实现和 `interrupt`/恢复事实。2.0 若增加审批、检索或多步处理，应先定义 State 字段和更新语义，再设计边；不从 Java 示例反推当前项目已改用 Spring AI。

## 关键词

Workflow、Graph、Node、Edge、State、Replace、Append、Reducer、条件边、回边、MemorySaver、状态污染、Loop 放大。
