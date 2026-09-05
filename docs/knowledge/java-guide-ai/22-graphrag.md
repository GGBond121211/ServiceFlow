# 22｜GraphRAG

来源：[JavaGuide 原文](https://javaguide.cn/ai/rag/graphrag.html)

## 适用问题

普通向量 RAG 以 Chunk 相似度为中心，适合答案集中在少量片段的局部事实。GraphRAG 把实体、关系、路径、属性、来源和主题/社区摘要显式建模，适合“系统 → 负责人 → 事故 → 影响链路”这类多跳问题，以及跨文档的全局主题归纳。它不是“向量库加一个图数据库”就自动完成关系推理。

向量检索解决“这段内容像不像问题”；图检索补充“对象之间如何连接”。如果正确文本根本没有被召回，应先查解析、Chunk、BM25、Query Rewrite 和 Rerank；只有文本齐全但无法按业务关系拼接时，GraphRAG 才有明确投入目标。

## 核心对象与模式

知识图谱由 Node/Entity、Edge/Relationship 和 Property 组成。实体可以是系统、接口、人员、事件、条款或风险；关系要有方向、类型、来源 span、置信度、更新时间和抽取模型版本。实体消歧需要词典、别名、规则、阈值和人工校验，不能全靠 LLM。

社区发现把强连接节点聚成主题，为全局问题生成摘要；摘要不能替代原文证据。Local Search 从已知实体扩展邻居和原文，Global Search 基于社区摘要做主题 Map-Reduce，DRIFT Search 兼顾局部实体和跨社区背景；Basic Search 仍可走普通向量链路。

构建阶段包括解析、切分、实体/关系抽取、归一化、社区发现、摘要和写入图/向量/全文索引。查询先做问题分类，再选择向量、局部图、图遍历+向量、社区摘要或结构化查询。Neo4j 方案可用 VectorRetriever、VectorCypherRetriever、Hybrid、Text2Cypher 或 ToolsRetriever；Text2Cypher 必须限制 Schema、只读账号、结果数、超时和查询模板。

## 成本、权限与落地

图的错误可能系统性放大：同名实体没合并、关系方向反了、摘要漏约束、单文档更新牵动社区、权限文档混入全局摘要。节点可见不代表邻居/边/社区摘要可见；动态权限和高敏感数据应避免预生成跨权限摘要。

推荐分阶段：先做好向量 RAG 基线；收集关系型失败；只建少量核心实体/关系并保留原文证据；再评估社区/全局检索；最后按问题类型路由 Hybrid RAG。评测要分别看实体/关系召回、社区一致性、Faithfulness、答案相关性、引用、用户采纳、转人工和成本。

## 对 009 的落点

售后 V1 的核心问题目前是意图、规则和模拟业务状态，不需要 GraphRAG。若 2.0 增加“订单/政策/工单/商品关系分析”，先收集真实跨实体 Badcase；轻量边表或关系表可能比引入 Neo4j 更适合第一实验。

## 关键词

GraphRAG、Entity、Relationship、Knowledge Graph、Local/Global/DRIFT Search、Community Summary、Neo4j、Text2Cypher、实体消歧、权限摘要。
