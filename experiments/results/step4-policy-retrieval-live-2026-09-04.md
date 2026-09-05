# Step 4 真实 Embedding 检索小规模评测

## 实验坐标

- 项目：009 ServiceFlow；检索实现全部位于 009，不依赖其他项目。
- 语料：`serviceflow_policy_v2_expanded.jsonl`，33 条唯一条款级政策。
- 查询：`step4_retrieval_queries_v2.jsonl`，28 条；train 8 / dev 7 / test 6 / holdout 7。
- Embedding：系统环境配置的 `qwen3.7-text-embedding`，OpenAI-compatible API，1024 维。
- 真实 API 输入：33 条政策 + 28 条查询，共 61 条；未运行 100/300 规模测试。
- 过滤：每条查询都先应用租户、地区和生效期过滤；US 和生效日前查询作为负向案例保留。
- Top-K：5；Hybrid 粗召回候选数：10。

## 结果

| arm | Recall@5 | MRR | 空结果率 | must-not 通过率 |
|---|---:|---:|---:|---:|
| exact | 0.8590 | 0.9038 | 0.5000 | 0.9286 |
| BM25 | 0.9167 | 0.8654 | 0.5000 | 0.9286 |
| semantic（真实 Embedding） | 0.9487 | 0.9423 | 0.5000 | 0.9286 |
| Hybrid（RRF） | **0.9551** | **0.9615** | 0.5000 | 0.9286 |
| 当前启发式 rerank | 0.7885 | 0.6923 | 0.5000 | 0.9286 |

原始逐案结果见同目录 JSON 文件。指标只描述本次 33/28 数据、当前模型和当前配置；holdout 没有参与调参，因此本文件不把这些数字称为生产指标。

## 解释边界

真实 Embedding 的 semantic 和 Hybrid 都高于 BM25，说明旧 HashEmbedding 实验不能支持“向量检索不行”或“Hybrid 一定更差”。当前 rerank 反而降低指标，说明重排必须用独立标注和成本/延迟门槛验证，不能凭概念直接加入。

## 失败记录

首次运行因空过滤范围被 semantic store 拒绝而中断，已修复为空候选返回空结果；另一次运行时检查因 PowerShell 中文输入乱码造成 BM25 空召回，改为 UTF-8 JSONL/Unicode 转义后复现正常。两项均保留在 `docs/2.0-WORKLOG.md`，不删除负向案例。
