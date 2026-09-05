# Step 4 Policy RAG 参数决策记录

> 本记录中的旧数字已作废。它们建立在 11 条政策、9 条查询、HashEmbedding 和临时 BM25 上；只能作为 Bad Case，不能支撑决策。当前重测结果见 `experiments/results/step4-policy-retrieval-live-2026-09-04.json`。

## 实验来源

原始失败结果为 `experiments/results/step4-policy-retrieval-matrix-2026-09-04.json`，汇总见同目录的 `.md` 文件。固定变量是 11 条法规释义、9 条查询、CN 地区过滤、有效期过滤和 `HashEmbedding-128-test-adapter`。该方法已标记 `invalid_methodology`。当前有效的小规模重测固定 33 条政策、28 条查询和真实 `qwen3.7-text-embedding`，见 `step4-policy-retrieval-live-2026-09-04.json`。

## 当前决策

| 决策点 | 当前选择 | 数据依据 | 代价、失效条件与回滚 |
|---|---|---|---|
| Chunk | 暂用政策条款边界；不增加 overlap | 最大文档为 122 个测试词项，256/512/1024 均为一文档一块 | 文档变长或条款跨块后可能失效；扩大语料后重跑 Chunk 实验即可回滚 |
| 检索策略 | 当前运行时使用 BM25 + Qdrant semantic 的 Hybrid，exact 保留 fallback | 有效重测 Recall@5：BM25=0.9167、semantic=0.9487、hybrid=0.9551；MRR：0.8654、0.9423、0.9615 | 结果只适用于 33/28 数据与当前配置；holdout 或更大语料失效时回退 exact 或 semantic |
| Rerank | 已启用 qwen3.7-text-rerank；失败时回退 Hybrid | `step4-qwen37-rerank-live-2026-09-04.json`：1 query + 3 candidates 成功，300 prompt tokens；`step4-policy-rerank-complete-live-2026-09-04.json`：103 条完整语料链路成功且无 fallback；尚未证明质量优于 Hybrid | 增加外部模型成本、延迟和配置依赖；官方限制为最多 500 文档、单条最多 30,000 tokens、建议请求最多 120,000 tokens；固定评测不收益时关闭 |
| Top-K | 当前运行时 limit=5，candidate_k=10 | 有效重测固定 Top-K=5；没有完成只改变 Top-K 的对照，不能称为最佳 | 证据数量需结合 Context Budget 和单变量实验调整 |
| HNSW | 暂用 M=16、efConstruction=128、efSearch=64 作为实现起点，不称为最佳参数 | `step4-policy-qdrant-ann-live-2026-09-04.json`：33 条政策、3 条代表查询，写入约 1820.103ms，正常/质量/错误地区均通过 | 3 条不能证明规模收益；完成经批准的参数矩阵后再定，必要时回退 exact |

## 未定论

Embedding 模型最终选型、真实 Cross-Encoder、Query Rewrite、产品类别专门规则、chunk/Top-K/RRF 参数和更大规模外推均未完成。因此不得把本记录的小样本结果写成最终生产方案。

## qwen3.7-text-rerank 接入边界

官方文档确认 qwen3.7 使用业务空间 endpoint
`/api/v1/services/rerank/text-rerank/text-rerank`，请求体是嵌套的
`input.query/documents` 与 `parameters.top_n/instruct`；它不是 `qwen3-rerank` 的
OpenAI-compatible `/compatible-api/v1/reranks`。`return_documents` 不作为 qwen3.7 请求参数，
因此 009 依靠返回的 `index` 映射回本地候选文档，避免信任外部回传的原文。
