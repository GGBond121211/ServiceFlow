# 21｜RAG 知识库文档更新策略

来源：[JavaGuide 原文](https://javaguide.cn/ai/rag/rag-knowledge-update.html)

## 更新要解决什么

更新完成后，检索要对应当前文档且不越权；失败可定位、补偿和回滚。Embedding 模型、Chunk 策略和解析器一旦变化，历史向量不能默认继续混用。Chunk 元数据至少需要 `doc_id`、`chunk_id`、`content_hash`、`version_id`、策略/大小、来源/章节/页码、租户/ACL、时间、Embedding 模型/维度和删除标记。

`content_hash` 判断正文是否变化，`version_id` 追踪历史，软删除保留审计/恢复依据；查询默认排除已删除和非活动版本。租户和 ACL 应在检索前或检索时过滤，并在组装上下文、返回引用前再次防御性检查。

## 增量、全量和版本切换

新增/修改/删除都必须幂等。修改可先构建不可见的新版本，校验向量库、元数据库和全文索引，再通过 `active_version`/索引别名原子切换；旧版本异步清理。删除要区分软删除、延迟物理删除和合规立即擦除，并清理旁路缓存。权限变化也可能触发重新索引或只更新 ACL 元数据。

增量更新适合日常变更，可用 Webhook、CDC 或轮询，推荐事件驱动加轮询兜底，并可用队列解耦。全量重建适合 Embedding/Chunk/结构升级、严重不一致和按实际索引健康度安排的维护；蓝绿索引验证后切换，保留旧索引供回滚。

## 可靠性

唯一约束、条件更新、claim/lease、outbox 和 reconciliation 共同处理重复、并发、部分成功和漏写。事件要带 `source_version`/revision，旧事件不能覆盖新版本；瞬时错误有限指数退避，永久错误进入 DLQ，不能无差别重试。更新状态应区分 pending、processing、partial_failed、ready，超租约任务可以被接管。

回滚应能按索引别名、模型+索引、历史快照或权限影响范围快速切回；发生权限泄露时先阻断检索入口和相关索引，再修复。灰度可按文档、用户或问题类型分批，并同时观测召回、引用、延迟和负反馈；文中阈值是示例，不是项目默认。

## 观测与对 009 的落点

关键指标包括索引延迟、失败更新、DLQ、陈旧文档、ACL mismatch、部分索引、成功率和召回回归；审计记录 doc、变更类型、时间、操作者、结果和错误。当前 ServiceFlow 没有真实文档索引链路，2.0 若建立知识库，要先决定 source of truth、更新时效和删除要求，不能先写一个“定时全量重建”任务。

## 关键词

Embedding/Chunk 版本、content_hash、active_version、软删除、增量、全量重建、alias、outbox、reconciliation、DLQ、乱序、灰度、回滚。
