# qwen3.7-text-rerank 真实 smoke

- 时间：2026-09-04
- 项目：Project-0009-ServiceFlow
- 范围：1 个中文售后查询 + 3 个候选文档，未执行整库评测或 100/300 规模调用
- 凭据：复用系统中的 `CODEINSIGHT_EMBEDDING_API_KEY`，密钥值不落盘
- 结果：HTTP 请求成功，按 `relevance_score` 降序返回输入索引 `0 → 1 → 2`
- 实现：通过 `serviceflow.infrastructure.rerank_model.QwenTextReranker.from_environment()` 调用成功
- 用量：`prompt_tokens=300`，`total_tokens=300`

## 结论

1. 当前阿里云业务空间的 Embedding 凭据可以调用 `qwen3.7-text-rerank`。
2. 该模型需要 DashScope workspace endpoint：
   `.../api/v1/services/rerank/text-rerank/text-rerank`，不是 OpenAI-compatible 的 `/v1/reranks`。
3. qwen3.7 的 HTTP 输入使用 `input.query/documents` 和 `parameters.top_n/instruct`；返回 `output.results[index/relevance_score]`。
4. 分数只用于同一次请求内排序，不能跨请求比较；代码通过输入索引映射回 PolicyDocument，不依赖服务端回传原文。
5. 这次只证明接入链路，不足以决定 rerank 是否打开，也不足以证明它比当前 Hybrid 更好。完整对比需要固定评测集和用户对更大调用的确认。
