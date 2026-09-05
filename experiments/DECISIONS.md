# ServiceFlow 2.0 决策台账

> **这是全项目唯一的决策入口表。** 面试追问"这个点为什么选 A 不选 B"时，先在这里定位，再进 `decision_records/` 看细节。
>
> 建立日期：2026-09-02（计划补充 Q）。

## 填写纪律

1. **每个 Step 完成时立刻追加本步产生的决策行**，不得等到 Step 10 补写。
2. **「依据」列必须指向 `experiments/results/` 下的真实结果文件**。禁止出现"效果更好""更稳定""性能提升明显"这类没有数字支撑的表述。
3. **每一行都要能撑住三轮追问**：① 为什么选它不选替代 ② 数据是多少 ③ 代价、失效条件、回滚方式。**写不出第 ② 列的决策不允许填进本表**——那说明实验还没做。
4. **"评估过但决定不做"的项同样占一行**，「选择」列写"不做"，「依据」列写评估结论（见 `model_adaptation/decision_report.md`）。
5. 状态标记：`○` 未开始 · `◐` 实验进行中 · `●` 已定论

## 台账

| # | 决策点 | 候选方案 | 选择 | 依据（指标 + 数据出处） | 代价 | 什么情况下会改 | 回滚方式 | 状态 | Step |
|--:|---|---|---|---|---|---|---|:--:|:--:|
| 1 | 模型 / Provider 选型（分场景） | 待填：便宜快速档 / 均衡档 / 强能力档 | — | — | — | — | — | ○ | 9 |
| 2 | Embedding 模型选型 | 待填（需覆盖中文政策、商品名、专有名词、中英混合） | — | — | — | — | — | ○ | 9 |
| 3 | Policy Chunk 策略与 overlap | 政策条款边界 / 256 / 512 / 1024 token × overlap 0 / 10% / 20% | **暂用政策条款边界、overlap 0** | 旧矩阵 `step4-policy-retrieval-matrix-2026-09-04.json` 方法无效；新语料 `serviceflow_policy_v2_expanded.jsonl` 当前 33 条条款级记录，尚未完成独立 chunk 对照 | 文档变长或跨条款时可能丢上下文 | 完成 chunk 对照后以 Recall、引用完整性和上下文 token 决定 | 回退条款边界并重建索引 | ◐ | 4 |
| 4 | 检索策略 | **纯向量（对照档）** / BM25 / hybrid + RRF 权重 | **运行时采用 BM25 + Qdrant semantic 的 Hybrid；exact 保留 fallback** | `step4-policy-retrieval-live-2026-09-04.json`：33 条政策、28 条查询、真实 `qwen3.7-text-embedding`；Recall@5：BM25 0.9167、semantic 0.9487、hybrid 0.9551；MRR：0.8654、0.9423、0.9615。仅支持当前数据与配置下的候选结论 | 每次查询包含 BM25 计算和向量库请求；需维护融合权重 | holdout 或更大语料验证收益消失、延迟或成本不达标 | 切换 exact；保留 Qdrant semantic 单路作为对照 | ◐ | 4 |
| 5 | Rerank 加不加 | 不加 / Cross-Encoder 重排 | **启用真实 qwen3.7-text-rerank；保留 fallback** | `step4-qwen37-rerank-live-2026-09-04.json`：1 个查询、3 个候选、`prompt_tokens=300`；`step4-policy-rerank-complete-live-2026-09-04.json`：103 条完整语料链路返回 `qdrant_hybrid_rerank` 且无 fallback；尚未证明质量优于 Hybrid | 增加模型成本、延迟和外部依赖；官方单请求最多 500 文档、建议总输入 120,000 tokens | 固定评测集上 qwen3.7 相对 Hybrid 没有质量收益，或成本/延迟不达标 | 关闭 `SERVICEFLOW_RERANK_ENABLED`，回到 hybrid | ◐ | 4 |
| 6 | Top-K 与 Rerank Top-N | 候选 3 / 5 / 8 / 10；重排另行确定 | **当前运行时 limit=5、candidate_k=10** | `step4-policy-retrieval-live-2026-09-04.json` 的 28 条查询固定 Top-K=5；本轮没有完成只改 Top-K 的对照，不能把 5 写成最佳 | 更多证据增加上下文预算和噪声 | 完成只改变 Top-K 的实验后再定 | 回退 limit=5 | ◐ | 4 |
| 7 | HNSW 参数 | `M` × `efConstruction` × `efSearch` | **当前起点 M=16、efConstruction=128、efSearch=64** | `step4-policy-qdrant-ann-live-2026-09-04.json`：33 条政策、1024 维、Qdrant HNSW；3 条 smoke 查询正常/质量/错误地区均符合预期。3 条不足以证明最佳参数 | 更高参数会增加索引构建、内存和查询开销 | 完成规模化但经批准的参数矩阵后再定 | 恢复当前起点或 exact fallback | ◐ | 4 |
| 8 | 向量库选型 | Qdrant / exact baseline（Flat） | **Qdrant HNSW + exact fallback** | `step4-policy-qdrant-ann-live-2026-09-04.json`：33 条政策写入约 1820.103ms；3 条 smoke 查询中 CN 正常、质量运费、US 空结果均通过。Step 7 将 client 锁定 1.16.2，与 server 1.15.5 回到相邻 minor，启动兼容 warning 已消失 | 增加容器、索引发布、版本治理和 Embedding 服务依赖 | 资源或版本维护成本超过收益，或 ANN 与 exact 质量不符 | 关闭 Qdrant，使用 BM25/exact | ◐ | 4 |
| 9 | Context 预算与历史轮数 | 最近 2 / 4 / 8 轮 × 摘要触发阈值 × 证据 3 / 5 / 8 条 | — | — | — | — | — | ○ | 3 |
| 10 | 最大 Tool Loop 与 repair 次数 | Loop 3 / 5 / 8 × repair 0 / 1 / 2 | **当前起点 Loop=5、工具调用上限=12、repair=0** | `step5-native-tool-loop-live-2026-09-04.json`：真实 `deepseek-v4-flash` 单次 Docker smoke 返回原生 `tool_calls`，序列为 `get_order → get_shipment`，2 次工具调用后 COMPLETED；尚未完成上限单变量效果实验 | 上限过低会提前转人工，过高会增加成本、延迟和循环风险；当前未实现 repair | 固定案例上完成任务率/成本/卡死率对照，或真实失败暴露预算不足 | 调整 `ToolLoopConfig`，回到旧固定图 | ◐ | 5 |
| 11 | Gateway fallback 顺序与路由策略 | 场景路由 × 降级链 × 熔断阈值 | **`step8.1-v1` 五类 Route；DeepSeek V4 Flash 主模型，GPT-5.6 Luna 低成本候选备用；模型提出退款/补偿工具后，必须由 primary-only high-risk-review 重新生成计划，失败转人工** | `step8-1-hardening-2026-09-05.json`：31 项窄测、282 passed / 1 skipped；双副本 a/b/a/b；控制台 ◆ 输入/输出/缓存价 DeepSeek=12/36/0.3996、Luna=1.5/12/0.18。能力 smoke 均过但固定案例质量 A/B 未做 | 高风险规划多一次模型调用且不使用便宜备用模型；多一层 HTTP/Redis/Nginx 与审计 I/O；同一 Frontier 仍是共同故障域 | Step 9 质量不过、上下文/工具能力不兼容，或真实流量暴露路由漂移 | 移除 Luna；取消 `SERVICEFLOW_GATEWAY_URL` 回进程内 Gateway；业务门禁不回滚 | ◐ | 8 |
| 12 | Redis TTL 与缓存策略 | 精确缓存 / Prompt cache / semantic cache 阈值 | — | — | — | — | — | ○ | 3 |
| 13 | Trace 采样策略 | 头部采样 / 尾部采样 / 分层组合 | **当前父子一致的可配置头部采样；审计独立全量；尾部采样留 Step 10 Collector** | `step8-1-hardening-2026-09-05.json`：测试真实调用 API、Gateway、Fake 模型 Provider、MCP ToolExecutor、SQLite、Outbox 与 Worker，断言同 traceId 且 Worker parent 为 outbox enqueue；采样率 0 时审计仍保留 | 头部采样无法按最终错误、成本或延迟保留整条链；本地 in-memory exporter 不是生产后端 | Step 10 接 OTel Collector + Jaeger 后，用尾部策略按错误/fallback/高风险/高成本保留 | 保持全量本地采样；禁用 exporter 不影响独立审计表 | ◐ | 8 |
| 15 | Gateway Streaming 与等待队列 | Streaming / 非流式；有界等待 / fail-fast | **本轮不实现 Streaming，`stream=true` 明确 422；队列上限=0，并发满立即 backpressure** | `step8-1-hardening-2026-09-05.json`：服务测试覆盖 Streaming 拒绝和 queue_limit=0；31 项窄测、Compose 实况通过。结构化 Tool Call 必须完整校验后才执行，排队会占住 HTTP 连接且双副本共享队列需额外协调 | 当前没有 TTFT 实测和流式体验；突发并发会被立即拒绝，不做短暂削峰 | Step 10 实现 SSE 用户体验或真实压力测试证明短队列能提高成功率且不破坏 deadline | 删除 422 分支并实现流事件协议；队列仍必须有上限和超时 | ● | 8 |
| 14 | 可观测后端选型 | Jaeger / Langfuse / 自建 | — | — | — | — | — | ○ | 10 |

### Step 9 初始化记录（2026-09-05）

> 本节记录的是“实验能否开始”的初始化判断，不是把外部默认值写成项目最优解。质量结论仍须来自后续固定数据、单变量实验和 `results/` 原始结果。

| # | 决策点 | 候选方案 | 选择 | 依据（指标 + 数据出处） | 代价 | 什么情况下会改 | 回滚方式 | 状态 | Step |
|---|---|---|---|---|---|---|---|:--:|:--:|
| I9-1 | 外部成熟默认值的使用方式 | 直接采用 / 作为参考起点后实测 / 不记录 | **作为 2.0 baseline 的参考起点** | `experiments/results/step9-initialization-2026-09-05.json` 与 `experiments/configs/step9_reference_defaults.yaml`：BM25 `k1=1.2,b=0.75`、RRF `rank_constant=60`、Qdrant `M=16` 等均标为 reference-only；没有把组件默认值冒充项目最优 | 后续仍需为质量结论付出实验成本 | 2.1 固定集显示质量、延迟、安全或成本不满足门槛 | 保留 `step9_baseline_profile.yaml` 的起点并切换单项配置 | ● | 9 |
| I9-2 | V2 评测集合是否已具备全量实验条件 | 立即跑全部指标 / 先修正评测基础设施 / 2.0 只做契约与低成本 smoke | **2.0 以现有契约、审计和 smoke 收口；全量实验延期** | `experiments/decision_records/step9_dataset_audit.md` 与 `step9-baseline-closure-2026-09-05.json`：132 条可做契约/回归与 Bad Case，但 dev split、完整逐案质量 Runner、政策映射和过程评分仍不足 | 2.0 不产生总体质量或参数最优结论；后续仍需维护数据/Runner | 2.1 完成 P0 门槛且有预算时再开启质量 A/B | 保留当前 JSONL、初始化审计和 V1 冻结基线 | ● | 9 |
| I9-3 | Step 9 检索矩阵范围 | 原笛卡尔积 / E1→E3 单变量 / 2.0 参考起点 + smoke | **2.0 采用参考起点，重型矩阵延期到 2.1+** | `experiments/configs/step9_baseline_profile.yaml`：BM25 `1.2/0.75`、RRF `60`、Qdrant `M=16`、条款边界/overlap `0`、rerank `10→5`；`policy_retrieval_matrix.yaml` 已收窄但本轮不启动付费或全量矩阵 | 不能回答“哪个参数最优”；保留可解释、可回滚的起点 | 数据规模、Runner 和预算满足后再增加单变量或交互矩阵 | 回到条款边界、`K=5`、Hybrid + exact fallback | ● | 9 |
| I9-4 | 2.0 Step 9 发布基线 | 全量质量优化后再进入 Step 10 / 参考默认值与现有证据收口 / 跳过 Step 9 | **参考默认值 + 已有契约/Smoke，作为 2.0 工程基线** | `experiments/results/step9-baseline-closure-2026-09-05.json`：V2 132 条、Policy 103 文档/28 查询、V2 契约 19 项；此前 Step 8.1 回归 282 passed / 1 skipped。该数字用于工程可运行性与审计范围，不是 V2 总体质量 | 参数仍可能次优，2.1 需要新增数据、Runner 和模型额度 | 发布后发现基线无法运行、硬门禁失败，或 2.1 有足够数据证明替代方案更好 | 按 baseline profile 回退单项参数，保留 V1 冻结基线 | ● | 9 |
| I9-5 | 重型实验在 2.0 的处理 | 现在全量执行 / 删除 / **登记为 2.1+ backlog** | **延期，不作为 2.0 发布阻断** | `step9_dataset_audit.md`：当前没有 dev split，工具期望 0/132，状态序列仅 4/132，FPR probe 9 条，Policy 文本平均约 58.5 字符；继续跑会产生高成本但低辨识度结论 | 暂不获得总体质量、FPR 上界或最优参数声明 | 2.1 补齐数据/Runner/预算后按单变量顺序执行 | 不修改冻结案例；只新增版本化派生集和原始结果 | ● | 9 |

### 已定论的决策（准备阶段，2026-09-02）

| # | 决策点 | 候选方案 | 选择 | 依据 | 代价 | 什么情况下会改 | 回滚方式 | 状态 |
|--:|---|---|---|---|---|---|---|:--:|
| P1 | 2.0 语言与框架 | 继续 Python / 迁移 Java + Spring AI | **继续 Python** | V1 全部资产在 Python；迁移会使 100 案基线失效且无业务收益 | 无法用本项目展示 Java 生态 | 目标岗位明确要求 Java 后端 | 无需回滚（未迁移） | ● |
| P2 | 是否引入 RAG | 不做 / 全量业务 RAG / 仅 Policy RAG | **仅 Policy RAG** | 售后政策是天然的可版本化文档；订单事实走数据库不走检索 | 增加索引发布与版本治理成本 | 出现需要跨文档归纳的 Hard Case | 关闭检索开关，回退纯 `policies.py` | ● |
| P3 | 真实副作用 | 接真实支付/物流 / 仅 Fake Provider | **仅 Fake Provider** | 作品集项目不应接触真实资金与客户数据；Fake 足以证明适配器契约与故障路径 | 无法声称有真实生产集成经验 | 不会改（见 `docs/public/BOUNDARIES.md`） | — | ● |
| P4 | 格式化债是否偿还 | 跑 `ruff format` 统一 / 保持现状 | **不还** | V1 已在远程按 `v1.0.0` / `v1.0.1` 冻结，格式化会使工作区偏离冻结版本；11 个文件为格式器版本行为差异，非代码缺陷 | CI 不能用 `ruff format --check` 做门禁 | V1 解冻或重新发布时 | `git restore backend/` | ● |
| P5 | 外部评测数据集 | 直接导入 τ-bench / 只借方法论 / 完全自建 | **只借方法论 + 自建**（注入 payload 除外） | τ-bench retail 政策与 009 V1 历史默认规则不一致，且 V1 的 7 天 / ¥500 / 30 天不是 2.0 最终标准；导入会替换业务身份；中文电商售后无公开兼容评测集 | 自建成本高，样本量受限 | 出现与 009 政策兼容的公开中文集 | 移除 `derived_from` 标记的案例 | ● |
| P6 | 多轮案例生成方式 | 手写脚本对话 / LLM 用户模拟器 | **用户模拟器（三层 + record/replay）** | 手写对话僵硬、覆盖窄、追问由出题人预设；`unknown_info` 机制使追问真被触发 | 需维护轨迹文件，Agent 变更后要重录 | 模拟器成本或维护量失控 | 退回手写脚本对话 | ● |
| P7 | 模拟器可复现方式 | 固定 seed / 录制-回放 | **录制-回放** | 托管 API 即使 `temperature=0` 也不保证逐次一致（批处理浮点非确定性、供应商版本变更、MoE 路由）。验收证据：`test_user_simulator_determinism.py` 11 项，replay 逐字节一致且 `model_calls==0` | 需要维护轨迹版本与案例集版本的对应 | 出现真正可复现的推理服务 | `--allow-live-fallback`（CI 禁用，结果标记不可用于结论） | ● |

### Step 1 产生的决策（2026-09-03）

| # | 决策点 | 候选方案 | 选择 | 依据（指标 + 数据出处） | 代价 | 什么情况下会改 | 回滚方式 | 状态 |
|--:|---|---|---|---|---|---|---|:--:|
| S1-1 | V1 基线冻结口径 | 40 案报告 / 100 案报告 / 两者并列 | **100 案报告为唯一权威** | `outputs/evaluation/serviceflow-v1-100-report.md`：Outcome 95.00% / Final State 98.00% / Policy 95.00% / Tool 98.00% / Clarification 91.67% / 平均 5640.25 ms；核心 40 案 97.50% vs 复杂 60 案 93.33%。40 案运行（Clarification 83.33%、3729.63 ms）案例集不同，降为历史对照 | 早期文档引用需全部更正 | V1 重跑并产生新报告 | `experiments/configs/baseline.yaml` 保留了两次运行的完整坐标 | ● |
| S1-2 | 公开文档是否放基线数字 | 只放方法论 / 放数字 | **放数字**（用户 2026-09-03 决定） | 作品集仓库有量化结果显著优于只有方法论；证据文件 `outputs/` 不入库，故附复现命令 | 公开仓库无原始报告，只能靠复现 | 数据涉及敏感信息时 | 删除 `docs/public/EVALUATION.md` 的「V1 冻结基线」一节 | ● |
| S1-3 | `ARCHITECTURE.md` 如何处理即将过期的描述 | 现在就改 / 加标注不改正文 | **加标注不改正文**（用户 2026-09-03 决定） | 三处（§1 流程图、§3 进程内 checkpoint、§5 两个服务）对 V1 均为真，分别在 Step 5/2/10 才失效。现在改等于描述一个不存在的系统 | 需要在对应 Step 记得回来更新 | 对应 Step 完成时 | 删除顶部标注块 | ● |
| S1-4 | V2 案例集规模与划分 | 计划下限 48 条 / 88 条 / 补语言难度到 132 条 | **132 条，六分法** | smoke 6 / regression 64 / golden 10 / boundary_security 24 / reliability_concurrency 12 / **holdout 16**；注入 8 变体全覆盖（16 条），误拦截探针 8 条，语言难度 48 条（24 种中文现象全覆盖）。契约测试 19 项断言计数、唯一性、变体覆盖、holdout 无泄漏、语言现象全覆盖。数据出处：`backend/tests/evals/test_v2_eval_manifest.py:36-58` 的 manifest 常量 | 案例维护成本上升；多数案例在 Step 7 前为红 | Hard Case 暴露覆盖盲区 | `experiments/build_v2_cases.py` 可重新生成 | ● |
| S1-6 | V1 那 60 条复杂中文案例如何处置 | 原样导入 / 丢弃 / **提炼语言现象后按 2.0 标准重写** | **提炼后重写为 36 条**（用户 2026-09-03 决定） | V1 案例的五处僵硬：单轮固定输入、期望值写死回复文本、无 `unknown_info`、无表达鲁棒性对照、工具顺序严格计分。提炼出 24 种语言现象，重写为 36 条（合语言类共 48 条），逐条可追溯到原 V1 case id（`experiments/language_cases.py` docstring） | V1 那 100 条不再参与日常测试，只作冻结对照 | 需要与 V1 逐案对比时 | V1 案例集仍在 `tests/eval_cases/`，未删除 | ● |
| S1-5 | V2 是否复用 V1 的 `EvalCase` schema | 扩展 V1 模型 / 新建 V2 模型 | **新建 `EvalCaseV2`** | V1 是冻结基线，扩展其模型会改变冻结契约；V2 需要租户、划分、风险等级、确认/审批、`known_info`/`unknown_info` 等 V1 没有的字段 | 两套 schema 并存 | V1 解冻 | 删除 `case_v2.py`，V2 案例集作废 | ● |

### Step 2 产生的决策（2026-09-03）

| # | 决策点 | 候选方案 | 选择 | 依据（指标 + 数据出处） | 代价 | 什么情况下会改 | 回滚方式 | 状态 |
|--:|---|---|---|---|---|---|---|:--:|
| S2-1 | checkpoint 存哪里 | 继续 `InMemorySaver` / 官方 `PostgresSaver` / 自建 SQLAlchemy Saver | **自建 `SqlAlchemyCheckpointSaver`** | 009 的库是 MySQL/SQLite，`langgraph-checkpoint-postgres` 需要另起一个 Postgres，为一个组件多一套基础设施不划算。自建复用同一个 `session_factory`，因此也复用连接池和 SQL 计时钩子。验收证据：`test_durable_session_resume.py` 20 项全绿，其中**真实跨进程**恢复由 `cross_process` fixture 提供（`_resume_worker.py` 独立进程 start + resume，共 2 次 spawn，4 个测试共享） | 要自己维护 checkpointer 契约，LangGraph 升级可能改内部布局（`get_delta_channel_history` 已是 beta） | LangGraph 出官方 MySQL saver，或项目改用 Postgres | `build_service_graph(checkpointer=InMemorySaver())` 一行换回 | ● |
| S2-2 | `channel_values` 存一个 blob 还是按版本分表 | 单 blob / 三张表（checkpoint + blobs + writes） | **三张表** | 图每走一步写一个 checkpoint，但多数通道的值没变。按 `(channel, version)` 分开存，同版本只存一份；单 blob 方案每步复制全量状态，十步就是十倍。表结构照 `InMemorySaver` 内部布局落地 | 读一个 checkpoint 要 3 次查询（本体 + blobs + writes） | 通道数很少且状态很小时单 blob 更简单 | 表结构变更需重建 checkpoint（可丢，业务不受影响） | ● |
| S2-3 | 案件状态转移写在哪 | 散在 if/else / 显式转移表 | **显式表 `CASE_TRANSITIONS`** | 14 个状态的合法出边写成 `Mapping[CaseStatus, frozenset]`，可被测试**遍历断言**：终态无出边、每个状态都有条目、无非法自转移。`test_case_state_machine.py` 15 项 | 加状态要同时改表和测试 | 状态数继续膨胀到难以维护时改为状态图 DSL | 表是纯数据，删除即回到无约束 | ● |
| S2-4 | 模型能不能写业务终态 | 能（由 Prompt 约束）/ 不能（代码约束） | **不能，代码约束** | `_SYSTEM_OWNED_TARGETS` 把 PROCESSING / PENDING_PROVIDER / COMPLETED / FAILED / UNKNOWN / MANUAL_REQUIRED / CANCELLED 列为模型不可达。测试用同一条转移分别以 MODEL 和 SYSTEM 驱动，前者必拒后者必通——这样测的是权限而不是拓扑（`test_model_cannot_declare_business_outcome`，5 组参数化） | 模型自主性受限，Step 5 的 Tool Loop 需要按 actor 过滤可选动作（届时再加函数，本步不预留） | 不会改。这是 `CLAUDE.md` §3 那条"终态回读数据库"在状态机层的落地 | — | ● |
| S2-5 | UNKNOWN 之后允许直接重试吗 | 允许（当失败处理）/ 必须先对账 | **必须先对账** | UNKNOWN 的合法出边只有 COMPLETED / FAILED / MANUAL_REQUIRED / PENDING_PROVIDER，**不含 READY_TO_ACT**；`classify_replay` 对 UNKNOWN 返回 `NEEDS_RECONCILE` 且 `permits_execution == False`。超时后不知道副作用有没有发生，直接重试就是重复扣款 | 需要 Step 7 补上真正的对账实现，否则案件会停在 UNKNOWN | 不会改 | — | ● |
| S2-6 | 幂等只靠 actionId 还是加参数指纹 | 只用 actionId / actionId + requestFingerprint | **两者都要** | 只有 actionId 挡不住"同一个键换金额"。`request_fingerprint` 用 sha256 + 排序 JSON，跨进程稳定（`test_fingerprint_is_stable_across_processes`：设了 `PYTHONHASHSEED=12345` 的子进程与本进程结果相同），并把 `Decimal("199.00")` 与 `"199.00"` 归一。指纹不一致时**优先级最高**，对全部 9 个 OperationStatus 都返回 `FINGERPRINT_MISMATCH` | 参数结构变化会使旧指纹失效（等价于新请求） | 不会改 | — | ● |
| S2-7 | 幂等的最后一道防线 | 应用层判定足够 / 加数据库唯一约束 | **加 `uq_operations_action_id`** | 并发下两个协程可能都读到 `existing is None` 并判 FIRST_ATTEMPT。唯一约束让其中一个 INSERT 失败，`insert()` 返回 `None`，然后**重读重判**变成 IN_FLIGHT。验收：8 路并发同 actionId → 恰好 1 条 Operation、1 个 FIRST_ATTEMPT、7 个 IN_FLIGHT（`test_concurrent_identical_requests_create_one_operation`） | actionId 全局唯一，不能按租户复用 | 需要按租户分片时改成复合唯一键 | 删约束即退回纯应用层判定（不安全） | ● |
| S2-8 | 状态版本冲突：抛异常还是返回结果 | 抛异常 / 返回可解释结果对象 | **返回 `TransitionOutcome`** | 拒绝原因要原样进审计和用户可见解释；异常会把"期望版本 N、实际 M"这层信息压成 traceback。`transition_case` 被拒时仍写一条 `case_transition_rejected` 审计事件——"谁试图非法推进状态"本身就要留痕 | 调用方必须检查 `outcome.ok`，忘了检查就静默失败 | 不会改 | — | ● |
| S2-9 | Session/Goal 和 Case/Operation 放同一个 repository 吗 | 全塞 `case_repository.py`（计划原文）/ 拆两份 | **拆出 `session_repository.py`** | 会话和目标是对话层概念、生命周期长；案件和操作是业务层、会终结。合成一份约 600 行且两组关注点交织。**这是对计划文件清单的偏离，已在 WORKLOG 记录** | 与计划文件清单不一致 | — | 合并两文件即可 | ● |
| S2-10 | RunSnapshot 和 LangGraph checkpoint 的分工 | 只用 checkpoint / 两者并存 | **并存，职责不同** | checkpoint 的结构由框架定，Step 5 换 Tool Loop 后内部形状会变；而"当前目标 / 已确认事实 / 候选动作 / 预算 / deadline / 下一步 / 恢复点"是**我们的**契约，要能被 SQL 查、被排查页读、被评测断言。混在 checkpoint 里就查不动 | 两处都要写，可能不一致 | — | 删 `agent_run_snapshots` 表，退回只读 checkpoint | ● |
| S2-11 | "不保存模型隐藏推理"怎么保证 | 写进规范靠自觉 / 代码级黑名单 | **代码级黑名单** | `run_store._FORBIDDEN_KEYS` 7 个词根（reasoning / thinking / chain_of_thought / cot / scratchpad / hidden / internal_monologue），递归检查**键名**（不查值——用户话里出现"理由"是正常的），命中抛 `HiddenReasoningRejected`。验收：`test_run_snapshot_rejects_hidden_reasoning` | 合法字段若含这些词根会被误拦 | 出现误拦的真实字段名 | 从 `_FORBIDDEN_KEYS` 移除该词根 | ● |
| S2-12 | 审计事件与业务写入的事务边界 | 分开提交 / 同一事务 | **同一事务** | 审计写失败就整体回滚，不允许出现"改了状态但没留记录"。反之 checkpoint 的写入**刻意独立提交**——业务失败了也要留下"跑到哪一步失败的" | 审计表故障会挡住业务 | 审计量大到成为写瓶颈时改异步（需先解决丢事件问题） | 把 `EventLog.append` 移出事务 | ● |
| S2-13 | Operation 状态命名与计划 Step 7 不一致 | 现在就改成 Step 7 的命名 / 保留现名待 Step 7 统一 | **已在 Step 7 统一并迁移** | 当前枚举为 CREATED / CONFIRMATION_REQUIRED / APPROVAL_REQUIRED / DISPATCHED / PENDING / SUCCEEDED / FAILED / UNKNOWN / CANCELLED / MANUAL_REQUIRED；启动迁移将旧值批量映射到新语义，MySQL 实表已验证 | 历史 `confirmed/approved/started` 都映射为 DISPATCHED，无法还原更细历史阶段 | 不再改；新增状态必须同时更新转移表与迁移 | 停止新代码后可按已记录映射反向迁移，但会丢失 DISPATCHED/PENDING 细分 | ● |

| S2-14 | 代码冗余怎么控制 | 靠 review 自觉 / 写成可执行的自查清单 | **可执行清单 R1–R6**（用户 2026-09-03 指出后确立） | Step 2 交付时的实测：11 个符号 `grep -rn` 在 `src/` 内命中数为 1（纯死代码）；模块 docstring 13–29 行且与 WORKLOG/台账三重复制，而 V1 的 `graph.py`(401行)/`case_service.py`(143行)/`models.py`(100行) docstring 均为 0；16 次 subprocess 中仅 2 次不可替代。清理后：代码 2351→2084 行、全量 169→75 秒、测试项 174→177。规则见 `docs/2.0-CODE-DISCIPLINE.md` | 每步交付前要跑一遍 R6 自查；"以后可能用到"的接口要等到那一步才写，届时可能重写签名 | 不会改。这是成本纪律，不是风格偏好 | 删掉 R6 清单即退回靠自觉 | ● |

### Step 5 产生的决策（2026-09-04）

| # | 决策点 | 候选方案 | 选择 | 依据（指标 + 数据出处） | 代价 | 什么情况下会改 | 回滚方式 | 状态 | Step |
|--:|---|---|---|---|---|---|---|:--:|:--:|
| S5-1 | Tool Loop 主路径 | 继续固定 ServiceTools 顺序 / 原生 Tool Calling + MCP | **原生 Tool Calling + MCP，旧固定图保留兼容** | `step5-native-tool-loop-live-2026-09-04.json`：真实 `deepseek-v4-flash` 返回 `get_order → get_shipment`，2 个工具事件后 `COMPLETED`；真实调用链通过 MCP Host/Client/Server 汇总最终订单和物流状态。该文件是单次小规模 smoke，不代表完整任务质量 | 增加模型调用轮数、工具目录和风险执行器维护；没有原生 Tool Calling 的模型不能进入该路由 | 固定案例质量、成本或安全指标不达标 | 让模型不实现 `complete_with_tools`，回退旧固定图/JSON 路径 | ◐ | 5 |
| S5-2 | MCP 传输 | 进程内对象调用 / 本地 stdio 子进程 | **Compose 默认 stdio；测试允许进程内 transport** | `step5-mcp-stdio-contract-2026-09-04.json`：真实子进程完成 `tools/list`、UTF-8 响应解析、`tools/call` 和关闭；`step5-native-tool-loop-stdio-live-2026-09-04.json`：Docker API 默认 stdio + Frontier 真实小调用返回 `COMPLETED`；这些结果证明传输和小规模运行，不证明生产级进程编排 | 启动/关闭子进程增加开销，stderr/stdout 编码和生命周期需要治理 | 延迟预算不允许启动成本，或部署环境不支持 stdio | 设置 `SERVICEFLOW_MCP_TRANSPORT=in_process` | ● | 5 |
| S5-3 | 高风险工具门禁与恢复 | 让模型直接执行 / Prompt 约束 / Executor + 业务服务确认审批 | **Executor 代码门禁；确认由 API 授予，审批由 `CaseService` 决定** | `step5-native-tool-loop-live-2026-09-04.json` 与 Step 5 API 确定性测试：未经确认返回 `confirmation_required`；高金额确认后返回 `approval_required`，审批通过后由 `CaseService` 改库并回读 `order_status=refunded`；工具目录没有 `approve` | 用户交互多一步；当时 API 的 InMemory 限制已在 Step 6 的 S6-3/S6-4 解决 | 出现新的权限/审批主体 | 关闭 Native 路由，保留旧 LangGraph approval/resume | ● | 5 |
| S5-4 | Tool Loop 预算起点 | Loop 3/5/8；工具调用 6/12/20；repair 0/1/2 | **Loop=5、工具调用上限=12、repair=0** | `step5-native-tool-loop-live-2026-09-04.json`：真实序列 2 次调用完成；单次 smoke 只能支撑安全起点，不能证明最优值 | 上限过低会提前 `STUCK`，过高会增加成本、延迟和循环风险；repair 尚未实现 | 固定案例对比任务完成率、卡死率、Token/成本后调整 | 修改 `ToolLoopConfig`，或关闭 Native Route | ◐ | 5 |

### Step 6 产生的决策（2026-09-04）

| # | 决策点 | 选择 | 依据 | 代价与失效条件 | 回滚方式 | 状态 |
|--:|---|---|---|---|---|:--:|
| S6-1 | Answerability 怎么落地 | **代码级五路 Gate：继续/补问/查状态/拒绝/Handoff** | 31 项窄验收覆盖订单不存在、越权、政策缺证据和 Provider UNKNOWN；无证据不会进入确定答复 | 保守 Gate 会增加误转人工；Step 9 必须双向测安全与误拦截 | 关闭 Native route，回到 V1 固定图 | ● |
| S6-2 | 租户与资源权限放哪里 | **Executor 显式绑定部署租户，订单/Case/Operation 执行前二次 ACL** | `test_permission_scope.py` 同时验证跨租户与跨用户都返回相同 `unauthorized` 空数据 | 当前只有本地演示租户，不等于企业 IAM | 保留 V1 演示端点，仅关闭 2.0 Native route | ● |
| S6-3 | 确认与审批可信边界 | **所有写工具确认；高金额退款审批；绑定用户/租户/参数摘要/15 分钟有效期** | 防篡改 API 测试返回 409；低金额确认恢复、高金额确认→审批→数据库退款均通过；重复审批只产生 1 条退款 | 15 分钟是未优化安全起点；本地受信 approver 不是生产身份 | 调整有效期；关闭 Native route | ● |
| S6-4 | API 会话与 checkpoint | **SQL Session + `SqlAlchemyCheckpointSaver`** | API app 重建后恢复 WAITING_CONFIRMATION 并继续执行；Compose 会话在容器重启后仍可读取 | 增加 SQL I/O，并继续承担自建 Saver 的升级维护 | 只可在明确接受丢恢复能力时切回 InMemory | ● |
| S6-5 | 人工接管记录 | **`support_queue` + append-only EventLog + PII 脱敏** | MySQL 真实建表；测试验证邮箱/手机号不落原因字段，事件只保存低敏原因码、队列和优先级 | 脱敏可能误伤文本；当前没有真实客服 SaaS/SLA | 停止创建新 Handoff，保留既有审计数据 | ● |
| S6-6 | Specialist 角色 | **单 Agent 内有限角色标签，不建 swarm** | Order/Shipment/Policy/Operation/Handoff 五类与既有 max_steps/max_tool_calls 共用预算 | 角色只是职责路由，不提供独立自治或并行收益 | 删除角色标签，工具目录不变 | ● |

展开记录：`decision_records/step6_orchestration_risk_handoff.md`。

### Step 7 产生的决策（2026-09-04）

| # | 决策点 | 选择 | 依据 | 代价与失效条件 | 回滚方式 | 状态 |
|--:|---|---|---|---|---|:--:|
| S7-1 | Operation 状态契约 | **统一为计划的 10 状态并做启动迁移** | 新增 DISPATCHED/PENDING 区分“已发出”和“Provider 处理中”；MySQL 表与 246 项回归验证 | 旧阶段映射有信息损失；以后新增状态必须同步转移表、持久层和迁移 | 停止新写入后按记录映射回退 | ● |
| S7-2 | Provider 重试与降级 | **只对 timeout/429/5xx 有限重试；非重试错误不 fallback** | 故障注入验证主 Provider 2 次后备用成功；permission 错误备用调用为 0；未知 timeout 进入 UNKNOWN | 每 Provider 2 次、5 秒 timeout 未做参数实验 | 调低次数或只保留单 Provider；不改变安全错误规则 | ● |
| S7-3 | 幂等并发 | **稳定 actionId + requestFingerprint + 唯一约束 + 行锁** | 20 路并发只有 1 个 Operation、1 次 execute、1 个副作用键；同 key 换金额拒绝 | actionId 当前全局唯一；真实 Provider 还必须支持幂等键 | 停用 Provider 调用，保留 Operation 审计；不可删唯一约束后继续高风险写入 | ● |
| S7-4 | Webhook 与通知一致性 | **Inbox 去重 + 业务状态/Outbox 同事务 + Outbox 行锁** | 重复 Webhook 只推进一次；重复 Outbox 投递后 attempt=1、发送审计计数=1 | 外部收件方仍应支持幂等；本地 sender 只写审计事件 | 停 Worker，保留未发送 Outbox 供人工处理 | ● |
| S7-5 | 异步恢复 | **SQL TaskEnvelope + Celery/Redis Outbox Worker** | lease 恢复、deadline 死信、不可重试转人工均有测试与审计；停 Worker 入队、重启消费的 Docker smoke 通过 | Celery 当前只实际承载 Outbox；reconcile 周期调度待后续接入；参数未优化 | 停 worker；保留 SQL/Redis 待办与审计 | ● |
| S7-6 | UNKNOWN 处理 | **只 query/Webhook/人工对账，不再次 execute** | timeout 后 execute_calls=1；query 成功再转 SUCCEEDED 并写 Outbox | Provider 无查询接口时只能人工处理 | 保持 UNKNOWN/MANUAL_REQUIRED，绝不把回滚解释为可重试失败 | ● |

展开记录：`decision_records/step7_provider_idempotency_async.md`。

## 与其他文件的关系

- **细节**：`decision_records/*.md`，每份对应上表一到多行
- **参数登记**：`configs/parameter_registry.yaml`
- **原始结果**：`results/`
- **面试讲法**：`docs/public/INTERVIEW_DEMO.md`（Step 10 产出），按本表组织追问预案
