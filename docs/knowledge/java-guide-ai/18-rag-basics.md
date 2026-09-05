# 18｜RAG 基础概念

来源：[JavaGuide 原文](https://javaguide.cn/ai/rag/rag-basis.html)

## RAG 的链路与价值

RAG 是先从外部知识源检索相关片段，再把原问题、证据和指令交给 LLM 生成。它主要补足模型的时效性、私有数据和可引用性，能降低幻觉但不能消除错误；检索、上下文、权限和引用任何一环出错都会影响答案。

离线索引：文档输入 → 清洗/增强 Metadata → Chunk → Embedding → 向量/全文/其他索引。在线生成：接收 Query → 改写/向量化 → 召回 → 上下文组装 → 生成 → 引用/反馈。Embedding 只表示语义匹配，维度高不保证效果；距离度量要与模型和索引一致。

## Search、RAG、Fine-tuning、长上下文

传统搜索返回文档列表，延迟和审计更可控；RAG 返回答案，适合跨片段归纳但增加模型成本、引用和权限风险。简单找原文不必上 RAG。RAG 适合新知识和私有知识，微调适合风格、格式和固定行为，两者可组合但维护成本更高。长上下文适合少量长材料的整体分析，不能替代海量知识库中的检索、ACL、成本和引用。

RAG 可分 Naive（切块/Embedding/Top-K）、Advanced（Rewrite/HyDE/Hybrid/Rerank/压缩）和 Modular（组件可插拔、按场景路由）。生产价值在于证据可检索、可引用、可审计，而不是模型“变聪明”。

## 局限与评测

检索质量决定上限；Chunk 太大/太小、解析错误、Embedding 不合适都会使生成层无法补救。上下文越多未必越好，延迟、Token、噪声、Lost in the Middle 和权限都是真实成本。最低限度要有引用、拒答、权限过滤、失败样本和质量回放。

## 对 009 的落点

当前 ServiceFlow 不是 RAG 项目。若 2.0 要把售后政策、FAQ 或 JavaGuide 知识作为知识库，应先明确文档来源、更新时效、权限和引用形式，再建立小型评测集；不能把本目录的研读笔记直接当成已接入的在线 RAG。

## 关键词

Retrieval-Augmented Generation、Embedding、Chunk、Top-K、Search、Fine-tuning、Naive/Advanced/Modular RAG、引用、拒答。
