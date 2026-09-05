# Step 4 Policy RAG 检索参数实验

> **invalid_methodology：本文件仅保留为失败实验记录，不得作为 009 技术结论。** 语料过小、使用 HashEmbedding 测试替身和临时 BM25；重测见 `step4-policy-retrieval-live-2026-09-04.json`。

## 实验坐标

- 数据：11 条政策、9 条查询；查询集包含地区/有效期负向案例和政策编号缺口探针。
- Embedding：`HashEmbedding-128-test-adapter`，只用于低成本可复现对照，不是最终中文 Embedding 选型。
- 运行环境：本地 Qdrant `qdrant/qdrant:v1.15.5`，单机、无模型 API 调用。
- 原始结果：同目录 `step4-policy-retrieval-matrix-2026-09-04.json`。

## 检索策略对比（Top-K=5）

| 方案 | Recall@5 | MRR | Empty Recall | P95(ms) |
|---|---:|---:|---:|---:|
| exact baseline | 0.8611 | **0.8889** | 0.3333 | 2.914 |
| pure vector | 0.7778 | 0.7917 | 0.3333 | 4.037 |
| BM25 only | **0.9167** | 0.8333 | 0.3333 | **1.613** |
| hybrid, vector weight 0.3 | 0.8333 | 0.8333 | 0.3333 | 2.706 |
| hybrid, vector weight 0.5 | 0.6944 | 0.8333 | 0.3333 | 2.599 |
| hybrid, vector weight 0.7 | 0.6944 | 0.8333 | 0.3333 | 2.829 |
| vector + lexical rerank adapter | 0.7778 | **0.9167** | 0.3333 | 2.201 |

## 参数对比

- Top-K=3：Recall 0.6944，P95 3.088ms。
- Top-K=5：Recall 0.6944，P95 3.189ms。
- Top-K=8：Recall **1.0000**，P95 2.578ms。
- 三种 token 分块上限下，语料最大文档长度为 122 个测试词项；256/512/1024 都是一文档一块，因此本轮不能证明更大语料下的 Chunk 优劣。
- HNSW 共 27 组（M=8/16/32 × efConstruction=64/100/200 × efSearch=32/64/128），Recall@5 全部为 0.7778，MRR 全部为 0.7917；小语料上没有观察到参数对质量的影响。

## 结论边界

以上结论全部作废。该文件只支持一个方法论结论：错误的 HashEmbedding、临时 BM25 和 11/9 小数据不能用于决定 009 的 Policy RAG。有效重测见 `step4-policy-retrieval-live-2026-09-04.json`。
