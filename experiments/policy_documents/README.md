# ServiceFlow 2.0 Policy Documents

这一目录保存 ServiceFlow 的合成政策语料，不是任何真实平台的内部规则。

## 来源边界

- `source_type=regulation` 的条款是对国家市场监督管理总局公开法规的结构化释义，原文以 `source_url` 和 `source_locator` 为准。
- τ-Bench / τ²-Bench 只用于参考数据结构和 Agent 评测方法，不直接导入其业务政策。
- JDDC 原始对话没有在未授权的情况下复制到本项目。
- GitHub 售后 Agent、DCH-2、CSDS、Bitext Customer Support、τ-Bench/τ³-Bench 只登记为外部参考，
  不直接混入政策语料；它们最多用于学习对话语言、工具设计和评测方法。

## 当前版本

`serviceflow_policy_v2.jsonl` 是 11 条 seed corpus，保留作第一版错误实验的输入，不再代表正式 Policy RAG 语料。

`serviceflow_policy_v2_expanded.jsonl` 是法规基线，共 33 条条款级结构化释义，按七日无理由退货、消费者权益、产品质量和电子商务履约四个官方主题展开。它不是某个平台的内部政策，也不是法律意见；每条记录都必须回到 `source_url` 和 `source_locator` 核对原文。

本轮按四个建设步骤补齐了分层语料：

| 文件 | 层级 | 条数 | 用途 |
|---|---|---:|---|
| `serviceflow_policy_v2_expanded.jsonl` | `regulation` | 33 | 国家法规结构化释义，最高优先级 |
| `local_guidance.jsonl` | `local_guidance` | 14 | 深圳、上海及网络交易地方/监管操作参考 |
| `project_internal.jsonl` | `project_internal` | 20 | 009 演示商家的内部承诺与安全边界 |
| `operations_and_faq.jsonl` | `sop` / `faq` / `category_rule` | 36 | SOP、口语 FAQ、商品类别分流规则 |
| `serviceflow_policy_v2_complete.jsonl` | 以上四层合并 | **103** | 可供后续完整索引发布的合并语料 |

四层不是同等权威：法规回答“法律边界”，地方指引回答“地方合规操作参考”，内部政策回答“本项目承诺”，SOP/FAQ/类别规则回答“系统如何分流和解释”。冲突时由法规优先；内部政策不能缩小法定权益；FAQ 不能单独作为法律依据。

来源、权威等级、许可证和使用边界登记在 `source_registry.yaml`。完整语料已经生成，但当前运行时仍默认使用 33 条法规基线，避免自动为新 103 条语料重建向量索引；切换到完整语料前需要一次经确认的小批量/分批 Embedding 建库操作。

`step4_retrieval_queries.jsonl` 是与语料分开的检索查询集，覆盖有效期、地区、质量售后、三包边界和中英混合表达。`policy_identifier_gap_probe` 刻意保留为 exact baseline 的已知缺口：当前 exact 检索只对标题和正文做词项匹配，还没有把 `policy_id` 纳入可检索文本；它用于后续 BM25/hybrid 实验，不是当前结论。

`PolicyDocument.from_mapping()` 会为每条记录计算 `source_hash`，并在运行时保留政策版本、生效时间、地区、来源和条款定位。
