# 08｜AI Agent 核心概念详解

来源：[JavaGuide 原文](https://javaguide.cn/ai/agent/agent-basis.html)

## 核心定义

Agent 可以理解为：LLM + 目标/规划 + 记忆或状态 + 工具 + 执行循环。它感知当前上下文，决定下一步，调用工具或产生结果，再观察反馈，直到完成、失败或触发边界。模型是决策部件，运行时、工具和业务系统才提供真实世界的能力。

需要区分三种形态：传统程序的路径大多由代码固定；Workflow 的节点和边预先定义；Agent 的下一动作可根据运行时证据动态选择。生产系统通常采用 Agentic Workflow：确定性步骤负责权限、校验、写入和审计，模型负责难以穷举的语言理解、分类和候选行动。

## 运行与抽象

典型 Agent Loop 是“读上下文 → LLM 决策 → 调工具/输出 → 写回观察结果 → 判断是否停止”。循环必须有最大步数、时间、Token、工具次数和无进展检测；“模型说完成”不是唯一停止证据。

三层工程关注点：

- LLM Call：模型、Prompt、结构化输出、模型参数和成本。
- Tools Call：工具 Schema、权限、执行、结果、幂等和副作用。
- Context Engineering：历史、RAG、Memory、工具结果和中间状态的选择与排序。

工具是动作入口；Skill 是可发现的流程/操作规范；MCP 是工具、资源和 Prompt 的跨进程协议；Prompt 是指令表达；Context 是本轮实际输入。把这些概念混为“Agent 能力”会导致权限、状态和可观测边界不清。

## 常见模式

ReAct 让推理与行动交替；Plan-and-Execute 先生成计划再分步执行；Reflection 让独立检查或反馈推动修正；Multi-Agent 让不同角色共享受控结果；图式工作流用 Node/Edge/State 把路径、状态和循环显式化。模式选择应由任务稳定性、工具风险、验收信号和上下文规模决定。

## 对 009 的落点

ServiceFlow V1 的“模型提取意图 + Python 策略 + 受限工具 + 数据库状态 + HITL”已经是一个受约束的 Agentic Workflow，而不是无限自主 Agent。当前模型不负责判断退款权限或最终业务结果。2.0 若增加动态工具选择，仍应保留策略白名单、状态机、审批和最终状态断言。

## 关键词

Agent Loop、ReAct、Plan-and-Execute、Reflection、Agentic Workflow、Tool、Skill、MCP、State、停止边界。
