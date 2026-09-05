# 14｜MCP 协议

来源：[JavaGuide 原文](https://javaguide.cn/ai/agent/mcp.html)

## 协议边界

MCP（Model Context Protocol）定义 Host、Client、Server 之间发现和调用能力的协议边界，不等于 Agent，不等于模型，也不自动提供业务授权。Server 可以暴露 Tools、Resources、Prompts；Host 负责用户和模型环境，Client 负责与具体 Server 建立连接。Roots、Sampling、Elicitation 等能力仍需按实现和权限治理。

协议消息基于 JSON-RPC 2.0，初始化阶段协商版本和能力，之后进行工具/资源操作。工具调用的名称、参数和结果应结构化；Server 不能把“工具描述”当成无害文本，模型和 Client 也不能把返回内容当系统指令。

## 传输与工程

本地 Server 常用 stdio：stdout 只能输出协议消息，日志写 stderr；远程场景使用 Streamable HTTP 等传输。传输连接只解决通信，不负责租户、订单、文件路径、SQL、审批、限流、审计、幂等或结果校验。生产 MCP 需要固定版本和依赖、来源审查、工具白名单、资源级权限、超时/循环/输出上限、敏感数据最小化和紧急禁用。

工具要小而具体，不宜暴露通用 `execute_sql`、任意文件操作或任意 URL。协议版本、官方字段和授权细节会变化；本文记录的是读取日期下的资料，真正实现前必须核对当前官方 MCP 规范、Transport 和 Authorization 文档。

## 安全要点

MCP Server 不能只凭 OAuth scope 就放行任意资源；Token audience、租户、用户和资源仍需逐请求核验。不要把一个面向 MCP Server 的 Token 直接透传到下游 API；每段调用应使用受限凭证并保留委托关系。工具注解的 read-only/destructive 提示只能帮助展示风险，不能替代后端识别副作用。

## 对 009 的落点

当前 ServiceFlow 没有 MCP 依赖。若 2.0 为了复用售后工具而评估 MCP，先验证真实的跨客户端/跨 Agent 复用需求，再定义 `query_order`、`check_refund_eligibility` 等细粒度工具和服务端授权；不要因为 MCP 能“连接工具”就放宽现有策略或把模拟 DB 暴露为通用接口。

## 关键词

Host、Client、Server、Tools、Resources、Prompts、JSON-RPC、stdio、Streamable HTTP、OAuth、Token Passthrough、资源级鉴权。
