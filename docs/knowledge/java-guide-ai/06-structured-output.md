# 06｜大模型结构化输出详解

来源：[JavaGuide 原文](https://javaguide.cn/ai/llm-basis/structured-output-function-calling.html)

## 结构化输出不是“请返回 JSON”

自由文本容易出现 Markdown 包裹、额外说明、漏字段、类型错误、枚举漂移和边界字段不一致。JSON Mode 重点是“能解析成 JSON”，JSON Schema 进一步描述字段、类型、必填、枚举和对象结构；Structured Output 是否能强约束生成，取决于供应商、模型和 Schema 子集，服务端仍必须验证。

## Function Calling 的边界

Function Calling 的完整过程是：注册工具定义 → 模型提出名称和参数 → 后端解析并校验 → 业务鉴权/策略判断 → 执行工具 → 将结构化结果回传模型 → 生成最终响应。模型提出的是意图，不是授权。`tenantId`、`userId`、`approved=true` 等来自模型的字段不能覆盖认证上下文和服务端状态。

Function Calling、MCP、Agent 和 Skill 各自解决不同问题：Function Calling 是模型调用形状；MCP 是跨 Host/Client/Server 复用工具、资源和 Prompt 的协议；Agent 负责循环决策；Skill 是可发现、按需加载的操作流程。它们可以组合，不能互相替代。

## Schema 设计

一个字段只表达一个含义；明确“用于/不用于”；未知值使用显式状态或 null；枚举要有限；必要时带版本和错误信息。解析失败后的修复应有次数上限，修复请求要给具体校验错误；无法修复时应进入人工、规则降级或明确失败，而不是猜一个结果。

工具要拆成具体业务动作，避免万能 `execute_sql`、任意 URL 或文件操作。执行链应依次覆盖 Schema、业务语义、用户/租户资源权限、风险等级、人工确认、幂等、审计和结果验证；工具超时不应编造“已成功”。

## 对 009 的落点

V1 的意图抽取和工具参数已经体现“模型提议、代码执行”的边界。2.0 若要规范化，应先梳理现有 Pydantic 模型、策略输入、工具结果和错误类型，补充版本/拒答/未知语义，再考虑迁移到 Java 的 DTO 或 Spring AI；不能把文章中的示例接口直接当作当前契约。

## 关键词

JSON Mode、JSON Schema、Structured Output、Function Calling、MCP、Skill、Schema 校验、工具执行器、幂等。
