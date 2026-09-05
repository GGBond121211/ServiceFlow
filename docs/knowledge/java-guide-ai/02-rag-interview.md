# 02｜RAG 面试题总结

来源：[JavaGuide 原文](https://javaguide.cn/ai/interview-questions/rag-interview-questions.html)

## 总体框架

RAG 面试不能只回答“向量库 + LLM”。完整链路是：文档解析与清洗 → Chunk → Embedding → 索引 → 查询理解 → 召回 → 融合/重排 → 上下文组装 → 生成 → 引用/拒答/评测。线上还要加版本、ACL、增量更新、删除、回滚和可观测性。

## 重点知识

### 基础概念与选型

RAG 解决的是模型参数中没有的新知识、私有知识或需要引用的外部事实；它通过每次请求动态取证，降低过期和幻觉风险，但不能保证绝对正确。传统搜索返回文档列表，RAG 返回基于候选证据组织的答案；若用户只是想找原文，搜索通常更便宜、更可控。

RAG 与微调不是互斥关系：RAG 更适合知识更新和溯源，微调更适合风格、格式和固定行为。长上下文适合少量材料的整体分析，不能替代海量知识库中的检索、权限过滤和成本控制。

### 检索与向量

Embedding 把文本映射到高维向量空间，余弦、内积和 L2 是常见度量；维度越高不等于效果必然越好，要用业务问题集比较质量、延迟和存储。BM25 擅长错误码、SKU、版本号和专有名词，向量检索擅长语义改写，生产常用 Hybrid/RRF。

索引层要区分 Flat 的精确基线和 ANN 的工程取舍。HNSW、IVF、量化算法分别在召回、延迟、内存和构建成本间作平衡；不能只凭网上的百分点或“百万条”的经验值做生产判断。

### 优化与评测

常见优化包括 Query Rewrite、Multi-Query、Decomposition、HyDE、Rerank、上下文压缩和引用校验。RAG 的评测要把检索与生成分开：Recall/Hit/MRR 看证据是否被找回，Context Precision/Recall 看上下文质量，Faithfulness 看答案是否由证据支撑，Answer Relevance 看是否回应问题；再加 P95、Token、成本和用户反馈。

GraphRAG 适合多跳关系和全局主题归纳，不是普通 RAG 的默认升级。知识库更新要考虑文档版本、Embedding/Chunk 版本、软删除、ACL、索引重建、缓存失效和回滚。

## 面试回答模板

被问“RAG 为什么会答错”时，先判断正确证据是否进入候选池：没进入就查解析、Chunk、Query 和召回；进入但没进上下文就查融合和重排；进入上下文仍答错才查上下文排序、Prompt、结构化输出和模型。这样比直接说“换更强模型”更有工程含量。

## 对 009 的落点

当前 ServiceFlow 没有已经上线的 RAG/向量库。若 2.0 要引入知识库，必须先明确文档来源、用户/租户、引用要求、更新时效和最小评测集；先建立可追溯基线，再决定是否需要混合检索、Rerank 或图结构。

## 关键词

Naive/Advanced/Modular RAG、BM25、Hybrid、RRF、Rerank、Faithfulness、Context Recall、GraphRAG、版本化。
