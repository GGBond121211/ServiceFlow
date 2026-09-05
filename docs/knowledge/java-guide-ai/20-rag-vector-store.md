# 20｜RAG 向量索引算法和向量数据库

来源：[JavaGuide 原文](https://javaguide.cn/ai/rag/rag-vector-store.html)

## 向量检索基础

Embedding 把 Chunk 和 Query 映射到同一向量空间；向量库负责在候选中高效取 Top-K，不负责理解文本。没有索引时是全表距离计算，数据增长后成本近似线性；ANN 通过图、聚类或量化以可接受的召回损失换取延迟和资源收益。实际指标取决于数据、硬件、并发、过滤、Top-K 和参数，不能只看理论复杂度。

余弦距离、内积和 L2 要与 Embedding 是否归一化、模型建议和索引 operator class 保持一致。生产常把 Metadata 过滤、BM25、向量召回和 RRF 结合，并要考虑动态更新、删除膨胀、权限/多租户和执行计划。

## 索引与选型

- Flat/ENN：精确、适合小规模、低 QPS、离线评测基线。
- HNSW：多层图，通常低延迟高召回；内存和构建成本较高。`m` 影响连接数，`ef_construction` 影响建图质量，`ef_search` 影响在线召回/延迟。
- IVFFLAT：聚类成桶，内存和构建更友好；要调 `lists/probes`，数据分布变化时可能需要重建。
- IVF-PQ/其他量化：压缩海量向量，节省资源但有精度损失。

PostgreSQL + pgvector 适合已有 PG、规模中小、业务与向量希望统一事务的场景；Elasticsearch/OpenSearch 适合已有关键词、分词、高亮和聚合；Milvus/Qdrant/Weaviate 适合独立扩展和更大向量负载；托管服务降低运维但要关注价格、驻留和供应商依赖。数据条数不能单独决定产品。

过滤是常见陷阱：ANN 先取候选再过滤可能导致结果不足或退化；可以扩大候选、预过滤、部分索引或使用产品支持的迭代扫描，但都要实测执行计划和召回。索引参数调整后同时检查 `EXPLAIN ANALYZE`、召回率、延迟和资源。

## 对 009 的落点

当前项目用 MySQL/SQLite 业务事实，并没有已确认的向量库。2.0 若加入 RAG，应先评测是否需要独立向量设施；不能因为 JavaGuide 的示例选择 PostgreSQL + pgvector 就改写当前数据库。Flat 甚至关键词/数据库查询可能是更合适的第一基线。

## 关键词

Embedding、ENN/ANN、Flat、HNSW、IVFFLAT、IVF-PQ、余弦/内积/L2、pgvector、Hybrid、RRF、预过滤、执行计划。
