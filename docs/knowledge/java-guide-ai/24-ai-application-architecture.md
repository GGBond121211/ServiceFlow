# 24｜AI 应用系统设计

来源：[JavaGuide 原文（重点章节：核心接口设计）](https://javaguide.cn/ai/system-design/ai-application-architecture.html#核心接口设计)

## 从 Demo 到生产

最小 Demo 是“输入 → 拼 Prompt → 调模型 → 返回答案”。生产系统还要处理多模型/重试/Fallback/熔断、权限、Token 预算、成本归因、Prompt 版本、RAG/Memory/Tool、Trace、评测、PII、数据留存、删除和回滚。HTTP 200 只能说明接口完成，不说明答案、工具或业务最终状态正确。

## 分层与交互模式

入口层把请求标准化为带 `requestId`、tenant/user、scene、input、variables、permission scope 的任务，做鉴权、限流、幂等和敏感输入处理。业务编排层选择普通问答、RAG、Agent、同步、流式、异步、确认或评测路径。模型网关统一 Provider、路由、Fallback、预算、成本和观测。Prompt/Context 需要版本、变量 Schema、灰度和回滚；RAG、Memory、Tool 各自按来源、生命周期和权限治理。

同步适合客户端超时内稳定完成的短任务；流式适合需要首字体验的聊天/长答案；异步适合报告、批量评测、长文档和多工具任务。选择依据是耗时、首字反馈、取消、重试和恢复，而不是框架偏好。

## Prompt、工具、RAG 和观测

Prompt 可建模为模板、版本、发布、运行记录和评测结果；运行时保存版本、变量摘要/Hash、Token 和关联 ID，敏感原文按授权、加密和留存控制。工具执行至少经过注册、工具裁剪、参数 Schema、资源鉴权、风险/确认、执行、审计和结果验证；只读也可能因读取密钥或全量客户数据而高风险。

推荐协作顺序是先确定身份和权限，再分别检索用户范围内 Memory 与共享 RAG，分区、去重、压缩后组装上下文；输出要区分资料事实和用户偏好。引用和事实不应被 Memory 或模型自由文本覆盖。

Trace 默认记录版本、Hash、来源 ID、工具/权限结果、模型和 usage、延迟、成本、结构化结果与反馈；完整 Prompt、文档和工具结果只在受控调试/审计场景保存。质量指标至少拆 Context Recall/Precision、Faithfulness、Answer Relevancy、Tool Success、Format Valid 和 Cost per Success。

## Java 核心接口语义

文章给出的接口重点不是具体框架，而是职责收口：

- `ModelGateway.generate(ModelRequest)` 表达完整同步生成；`stream(ModelRequest)` 表达流式事件，不能让调用方猜测何时完整。
- `ContextAssembler.assemble(AiRequest, ContextPolicy)` 负责受策略约束地组装上下文。
- `RagService.retrieve(RagQuery, PermissionScope)` 返回经过权限边界的召回结果。
- `EvaluationService.runDataset(EvalRunCommand)` 运行可回放评测。

最小链路可概括为：Controller → RequestGuard → Orchestrator → ContextAssembler → PromptService → ModelGateway → OutputParser → TraceService。文章建议按领域能力（api/orchestrator/prompt/context/gateway/rag/memory/tool/eval/observability）拆模块，而不是按供应商 SDK 拆；表也应区分请求 Trace、模型调用、上下文条目、RAG 命中、Memory、工具和评测。

## 对 009 的落点

这是本次 2.0 最直接的系统设计参考，但不是迁移指令。当前 009 仍是 Python/LangGraph V1，先把已有请求、意图、策略、工具、人工恢复和数据库事实的边界写清；只有用户确认 Java 学习/迁移目标后，才决定旁路服务、渐进迁移或保持 Python 主链路。

## 关键词

生产分层、AiRequest、ModelGateway、ContextAssembler、RagService、EvaluationService、同步/流式/异步、Prompt 版本、工具权限、Trace。
