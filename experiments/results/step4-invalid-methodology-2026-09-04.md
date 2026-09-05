# Step 4 旧检索实验：方法作废说明

`step4-policy-retrieval-matrix-2026-09-04.json` 和同名 Markdown 结果保留为 Bad Case，但不再作为技术结论。

作废原因：

- 语料只有 11 条政策、查询只有 9 条，不能代表 Policy RAG 的真实覆盖范围；
- semantic 使用 `HashEmbedding-128-test-adapter`，不是语义 Embedding 模型；
- BM25 是临时实验脚本中的简化实现，不是当前 009 的政策检索实现；
- Hybrid、Top-K 和 HNSW 结论都建立在上述错误输入和实现之上；
- 没有调用系统中配置的真实 Embedding API。

因此旧结果中“BM25 优于向量”“Hybrid 不如 BM25”“Top-K=8”“HNSW 参数已选定”等结论全部撤销。文件不删除，原因是它记录了本项目一次真实的方法论失败：错误数据和错误检索器可以产生看似精确、实际不可外推的数字。

重测入口：

- `experiments/run_policy_retrieval_experiment.py`：009 独立的 exact、BM25、semantic、Hybrid、rerank 对照；
- `experiments/run_policy_qdrant_ann_smoke.py`：真实 Embedding + 本地 Qdrant HNSW smoke；
- `experiments/results/step4-policy-retrieval-live-2026-09-04.json`；
- `experiments/results/step4-policy-qdrant-ann-live-2026-09-04.json`。
