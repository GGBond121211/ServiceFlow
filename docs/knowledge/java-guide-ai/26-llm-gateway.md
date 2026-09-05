# 26｜大模型网关

来源：[JavaGuide 原文](https://javaguide.cn/ai/system-design/llm-gateway.html)

## Gateway 的边界

LLM Gateway 是应用与模型供应商之间的治理入口，范围比只选模型的 Router 更大：统一 Provider、密钥、超时、重试、流式/工具/结构化适配、路由、Fallback、限流、预算、缓存、成本、Trace 和审计。对单体或单团队项目，先在应用内建立轻量唯一入口通常够用，不必第一天单独部署平台。

Gateway 与 RAG/Agent/MCP 的关系是：RAG 组织外部证据，Agent 组织任务和工具，MCP 组织跨进程能力，Gateway 治理每一次模型调用。它可以给 Agent 的每一步记录 route、usage 和成本，但不应接管业务规划或工具授权。

## 路由与 Provider

统一请求/响应要包含 request、幂等、租户、用户、scene、messages、Schema 和 options；Provider Adapter 不只转换 endpoint，还要转换工具调用、系统提示、流式事件、usage、错误和供应商专属能力。模型层级名（fast/balanced/flagship）应通过 Model Registry 映射真实模型和价格/上下文能力。

路由可以从固定场景规则开始，进化到成本级联、语义/分类、质量反馈、学习型/个性化/Agentic。决策至少看 scene、Token、输出长度、套餐、风险、健康、历史质量和延迟；要记录候选、selected model/tier、route_reason 和实际 attempt。低置信度走默认中强模型或澄清，高风险规则优先于成本规则。

Fallback 要按错误分类：网络/部分 5xx 可短重试或切换；429 看 Retry-After、排队和预算；上下文超限先压缩；参数错误修请求；安全拒答不应静默切低模型；结构化失败有限修复。已经有工具/副作用或流式片段时，切换模型前要确认可重放，不能拼接两个不完整结果。

## 预算、成本、缓存

限流不只看 QPS，还要按用户、租户、模型、供应商、并发和输入/输出 Token 管理。建议 estimate → reserve → actual usage → reconcile；Fallback/重试每个 attempt 重新预算，拿不到 usage 要保守挂账再对账。成本记录 request/attempt/tenant/user/scene/prompt/model/provider、Token、缓存、价格版本、TTFT/总延迟和 fallback。

精确缓存只适合语义、权限和状态稳定的答案；Prompt cache 要稳定长前缀、动态内容后置；语义缓存必须隔离租户、权限、数据/Prompt 版本和场景，不能把“发货状态”和“退款资格”因相似向量混用。缓存需有失效与数据删除策略。

## 方案选择与对 009 的落点

自研轻量模块可深度结合业务；LiteLLM 便于多 Provider；Cloudflare/Kong/Inworld 等要按托管、企业治理、私有化和实时路由需求核对。复杂路由需要稳定评测集和 Trace，否则难以证明收益。

ServiceFlow 当前未形成多 Provider 生产调用痛点。2.0 若需要统一调用，应先在应用内收口 Provider、错误、usage 和日志，再由真实流量/成本决定是否拆独立 Gateway；不能把 JavaGuide 的网关表当成必须新增的组件清单。

## 关键词

LLM Gateway、Router、Provider Adapter、Model Registry、Fallback、Token reserve/reconcile、route_reason、限流、成本归因、Prompt/Semantic Cache。
