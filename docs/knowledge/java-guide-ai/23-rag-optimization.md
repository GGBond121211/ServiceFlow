# 23｜RAG 检索优化

来源：[JavaGuide 原文](https://javaguide.cn/ai/rag/rag-optimization.html)

## 优化闭环

RAG 是证据加工流水线：解析/清洗 → Chunk/Metadata → 索引 → 查询理解 → 召回 → 重排 → 上下文 → 生成 → 评测。每个失败样本都应记录正确证据是否入候选、排名、最终上下文、答案是否使用和改动版本；没有固定回放就无法判断是改善还是换了一种错误。

## 分层策略

先治理数据：保留标题、表格、页码、图片说明、工单时间/角色和代码调用结构；Metadata 至少有来源、类型、章节、时间、租户/ACL、版本和业务标签。权限应在召回前参与过滤，不能先取全量 Top-K 再让模型“不泄露”。

Chunk 大小没有万能值：FAQ/短政策、技术教程、法规合同和代码需要不同边界；Parent-Child 是召回粒度与阅读上下文的折中。可以为 Chunk 增加摘要、可能问题、标题或结构化描述作为额外入口，但要评估维护成本。

召回通常采用 Vector + BM25/稀疏 + RRF/加权融合。错误码、SKU、版本和专有名词依赖关键词；口语化表达、同义词和意图改写依赖语义。Query Rewrite、Multi-Query、Decomposition、Step-back、HyDE、Self-Query 都要保留原始 Query 防止改写改变含义。

候选、重排和上下文的上限要分开：粗召回可以较大，Rerank 只保留中等数量，最终 Context 只放能支撑结论的少量片段。Rerank 不能补回候选池里不存在的证据；规则负责时间/权限/版本，专用 Cross-Encoder 负责主链路相关性，LLM Rerank 更适合低流量复杂判断。

上下文要去重、合并相邻片段、按证据强度和版本排序，并写清“证据不足时拒答、关键结论附来源”。压缩要围绕 Query 保留事实、条件、例外，避免摘要模型漏掉约束。

## 排查路径与对 009 的落点

先分类：没召回、排名靠后、没进上下文、上下文正确但答案错、引用错、应拒答未拒答、权限/时间/版本错。再依次检查文档入库、解析、Chunk、过滤、Query、Hybrid、Rerank、裁剪、Prompt 和生成模型。

当前 ServiceFlow 没有 RAG 优化链路。2.0 若建立政策问答，先固定 20–50 条高价值/失败/精确匹配/拒答问题和版本，逐项测召回、上下文、答案、延迟和成本；不要把“扩大 Top-K”作为默认修复。

## 关键词

Data Governance、Chunk、Metadata、Hybrid/RRF、Query Rewrite、HyDE、Rerank、Context Compression、Recall/Precision、拒答、回归。
