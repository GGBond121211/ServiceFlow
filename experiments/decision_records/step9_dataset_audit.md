# Step 9 评测集合审计（初始化版）

> 审计日期：2026-09-05。本文是进入实验前的结构审计，不是模型质量结论。
> 外部检索使用 agent-reach 的 Exa/GitHub 路由；外部资料只提供方法和组件参考。

## 一、审计快照

| 对象 | 当前事实 | 证据/边界 |
|---|---:|---|
| V2 案例 | 132 条 | `tests/eval_cases/serviceflow_v2.jsonl`，SHA-256=`FA82F3B17FB8CA8040DCD0A0EFCC99358A01754C2B9FA977B8EAC44EEAA1B76C` |
| V2 划分 | smoke 6 / regression 64 / golden 10 / boundary_security 24 / reliability_concurrency 12 / holdout 16 | `backend/tests/evals/test_v2_eval_manifest.py`，19 项契约测试通过 |
| Policy 语料 | 103 条完整合并语料；当前有效检索结果曾使用 33 条法规语料 | `experiments/policy_documents/` 与 `step4-policy-retrieval-live-2026-09-04.json` |
| Policy 查询 | 28 条，train 8 / dev 7 / test 6 / holdout 7 | `step4_retrieval_queries_v2.jsonl` |
| 当前 V2 执行能力 | 尚无 V2 端到端 Runner | `experiments/runner.py` 目前只加载/校验；后端 `evaluation/runner.py` 仍接 V1 `EvalCase` |
| 当前工作树 | `feature/new-work`，HEAD=`f9cf5b4`，相对 origin ahead 1 | 初始化时 `git status` 干净 |

## 二、已有优点

1. V2 schema 有身份、租户、风险、确认/审批、`known_info`/`unknown_info`、来源和评分声明，远胜于只写一条输入和一段期望文本。
2. 132 条中覆盖 8 种注入变体、24 种中文语言现象；holdout 与其他 split 没有重复订单号或完全相同来意文本。
3. 所有案例都有 DB reward basis；高风险案例禁止依赖 LLM Judge；拒答案例同时要求无副作用。
4. 误拦截探针已经存在，避免只靠“拒绝一切”把攻击成功率做成 0。
5. `unknown_info` 有 43/132=32.6% 覆盖，能测试一部分澄清路径；同一诉求还有两个 4 条成员的 paraphrase group。
6. V1 仍独立保留，未把 V2 的数字冒充 V1 冻结基线。

这些优点说明集合已经可以作为**契约和方向验证集**，但还不能直接支撑计划中全部 Q/S/R/P 指标的选择结论。

## 三、必须在质量实验前修正的问题

| 优先级 | 发现 | 为什么会影响结论 | 建议动作 |
|---|---|---|---|
| P0 | **没有 V2 `dev` split**：64 条全部叫 `regression` | 调参只能污染回归集，无法区分“选参数”和“验证不倒退” | 从 regression 版本化拆出 24 条分层 dev，剩余 40 条 regression；holdout 16 条内容和 ID 不动 |
| P0 | **V2 不能由现有 Runner 执行** | 当前只能验证 JSON 契约，不能产出 Outcome、Final State、Tool、安全和成本指标 | 先接 V2 最小执行器/逐案结果模型，再开始模型 A/B；否则报告数字没有运行来源 |
| P0 | **Policy ID 命名空间不一致**：案例用 `POL-*`，RAG 语料用 `CN-*`/`SF-*` | Q12 Policy Accuracy 与 Q13 Recall@K 没有可计算的映射，容易把两套政策混成一个指标 | 建立显式 mapping 或明确分成“业务路由政策”和“RAG证据政策”两条评分链；不能靠字符串猜映射 |
| P0 | **已有 retrieval 结果实际读了 holdout** | `step4-policy-retrieval-live-2026-09-04.json` 的 28 条结果包含 7 个 query-set holdout ID，尽管备注写着 holdout 不参与调参 | 该文件可保留为历史探索结果，但不能作为未泄漏的调参/最终证据；用 train/dev（或新 test）重跑 |
| P1 | **V2 案例的工具期望全部为空**：`expected_tool_calls=0/132` | 只有 `allowed_tools`，无法评分参数正确性、不必要调用、调用集合 precision/recall 或多条等价路径 | 为高风险写操作、澄清、查询和恢复各补 required/forbidden/argument assertions；不要恢复 V1 的固定顺序全等 |
| P1 | **状态转移期望几乎为空**：128/132 没有 `state_transitions` | Case Lifecycle Accuracy 无法检查中间状态是否跳过确认/审批/PROCESSING | 对需要门禁的案例补最小合法状态序列；只对确实关心序列的案例要求序列，其余用终态断言 |
| P1 | **多轮回放证据尚未落盘** | `experiments/results/simulator_traces/` 当前为空；没有 record/replay 轨迹就不能声称多轮重复实验可复现 | 先为 dev/golden 录制并绑定 dataset/prompt 版本；replay miss 必须失败，不放宽规则 |
| P1 | **测试集合与 Policy RAG 语料没有共同的地区/生效时间字段** | V2 案例不能测试 tenant/region/effective-time 过滤；这些能力只能靠另一个 28-query 集合的少数探针 | 给 Policy 评测单独维护 metadata/filter 集；在业务案例中加入少量明确的 region/time/tenant 场景 |

## 四、数量和分布审计

### 4.1 粗粒度数量够不够

| 分组 | n | 单个样本造成的点估计变化 | 审计判断 |
|---|---:|---:|---|
| 全部 V2 | 132 | 0.76 个百分点 | 足以做工程回归和发现 Bad Case；不足以把总体准确率当精确生产估计 |
| 当前 regression | 64 | 1.56 个百分点 | 可做回归门禁，但不应同时承担调参集 |
| 建议 dev | 24 | 4.17 个百分点 | 适合快速筛选大差异，不适合宣称小幅提升稳定成立 |
| golden | 10 | 10 个百分点 | 适合高价值门禁/逐案复盘，不适合统计比较 |
| holdout | 16 | 6.25 个百分点 | 适合最终 `pass^3` 展示，置信区间会很宽 |
| 注入 | 18（boundary 16 + holdout 2） | 5.56 个百分点 | 固定集安全观察可以做；每种变体只有 2–3 条，不能做变体级率估计 |
| FPR probe | 9（boundary 8 + holdout 1） | 11.11 个百分点 | 明显不足；0/9 的 95% Wilson 上界约 29.91% |
| Policy 查询 | 28 | 3.57 个百分点 | 只能做探索性 retrieval 对照；不能稳定比较多种 chunk/Top-K/模型 |

二元比例的 95% 区间必须同时报告分子、分母和区间。以零失败为例：

- 0/50 的点估计是 0%，但 Wilson 双侧上界约 7.13%；精确单侧 95% 上界约 5.82%。它适合“固定集观察为 0/50”，不支持总体风险 ≤2% 的强声明。
- 若坚持“零失败时总体单侧 95% 上界 ≤2%”这一统计口径，约需 149 个独立样本；这超出当前项目的轻量启动范围。

因此建议把 **50 条 FPR** 作为 Step 9 的工程门禁样本，把“总体 ≤2%”明确列为不做的统计声明；若以后需要该声明，再扩到约 149 条并重新审查独立性。

### 4.2 分布是否能代表要测的能力

当前 V2 的几个明显偏斜：

- 意图：refund 65、query 28、exchange 13、return 10、cancel 6、compensation 2、other 5、未指定 3。总体分数会被退款任务主导，稀有动作的 1–2 条不能支撑模型选择。
- 注入 18 条里 17 条是 refund；reliability/concurrency 12 条全部是 refund。安全与恢复结论不能外推到查询、换货、取消和补偿。
- 132 条全部使用 `TENANT-A` / `USER-001` 作为请求身份；只有 5 条通过不同 owner 做越权探针，实际租户维度没有变体，权限 scope 也几乎全是同一组。
- 风险级别是 high 49、medium 67、low 16。它适合安全优先的演示，但不是一般客服流量分布；报告必须按 risk macro 分组，不只报总平均。
- `policy_version` 在 132 条里全部为 `policy-2026.08`；案例没有真实的 region/effective-time 变化，版本过滤能力没有被业务集合覆盖。
- 24 种语言现象虽然全覆盖，但很多现象只有 1–2 条；只有 `para_refund_simple` 和 `para_query_shipment` 两个 paraphrase group，且都在 regression，没有 holdout 表达鲁棒性组。

### 4.3 评分字段是否足够

当前 `reward_basis` 统计为 DB 132、COMMUNICATE 3、ENV_ASSERTION 2；`expected_tool_calls` 为空 132/132，`state_transitions` 非空仅 4/132，`communicate_info` 非空仅 3/132，`env_assertions` 非空仅 2/132。

这意味着集合对“最终数据库状态”准备得最好，对以下指标准备不足：

- Tool Selection 的参数正确性、冗余调用和等价路径；
- 过程状态合法性、确认/审批是否被跳过；
- 回复是否把已完成结果正确告知用户；
- 审计、幂等、跨进程恢复等环境断言的普遍覆盖。

不能因为 schema 预留了这些字段，就把它们当成已经被测量的能力。

## 五、Policy RAG 集合的专项问题

1. 103 条完整语料的正文长度为 44–84 字符，平均约 58.5 字符；在 256/512/1024 token chunk 档位下基本每条仍是一个 chunk。因此当前语料无法有效区分 chunk strategy 或 overlap。
2. 103 条语料的 `tenant_id` 全为空、`effective_to` 全为空；没有同主题旧版/新版、过期版、租户私有版。版本和权限过滤只能测“没有匹配”的简单路径。
3. 28 条查询中 27 条是 CN、1 条 US；只有 2 条空期望，且有 7 条 holdout。按 query type 大多只有 1 条，单类结论不稳定。
4. 查询期望只覆盖 25 个 policy ID，103 条文档中有 78 条从未成为任何 query 的 expected/must-not 目标；完整 103 条索引并不等于 103 条都被评测。
5. 现有有效结果使用 33 条 regulation 语料，尚未覆盖 local_guidance、project_internal、SOP、FAQ、category_rule 的检索质量；“完整四层语料链路”与“完整四层质量评测”是两回事。

因此：现有 28-query/103-doc 组合可作为 smoke/方法开发集，不足以决定 chunk、Top-K、rerank、HNSW 或四层政策来源的最终选择。

## 六、最小补强方案（按“尽快进入 Step 10”排序）

### 必须做，不能跳过

1. 建立 `v2-step9-dataset-v2`：从 regression 版本化拆出 dev 24 + regression 40；锁定 holdout 16，生成 manifest/hash。
2. 修正 retrieval 评测的 holdout 泄漏，先只用 train/dev 做参数筛选；看到 holdout 后不再回调参数。
3. 接通最小 V2 Eval Harness：逐案保存配置、模型、Prompt、trace、DB 终态、工具事件、Token、成本和错误；没有 Runner 就不跑付费 A/B。
4. 给案例建立 `POL-*` 业务政策与 `CN/SF-*` RAG 证据的显式关系，或把两套指标彻底分开。
5. 对安全集合补到至少 50 条合法 FPR 探针，并继续同时报告 ASR/误拦截/拒答精确率/任务完成率；不把 0/50 写成总体 0 风险。
6. 为高风险动作补确定性 required/forbidden/argument/state assertions；不恢复固定工具顺序评分。

### 适合 Step 9 做，但可在第一轮后补

1. Policy query 扩到约 60–100 条，按自然问法、精确 ID、地区/时间、冲突/空召回、中英混合和四层来源分层；新增过期、版本冲突和 tenant-specific 文档。
2. 每个关键语言现象至少补到约 5 条，新增至少一个 holdout paraphrase group；报告 macro，而不是只报 48 条总平均。
3. 给 cancel/exchange/return/compensation、不同权限 scope、第二租户/第二用户各补成对镜像案例。
4. reliability 每类故障保留 20 次以上确定性重复，同时增加至少两个不同业务前置状态，避免“一个 refund 模板重复 20 次”被误解为场景覆盖。

### 可以后延到 Step 10 或明确不做

- 第三个真实模型、HNSW 的 3×3×3 全矩阵、正数等待队列、端到端 TTFT、尾部采样、微调：当前不是 Step 9 必需的最短证据链。
- 149 条 FPR：除非项目目标升级为总体风险上界的统计声明，否则不作为当前轻量交付条件。
- 103 条短政策上直接比较 chunk/overlap：应先补真实长度与结构，否则这个实验即使跑完也没有辨识度。

## 七、当前结论

**第一项任务可以马上落地为实验起点**：BM25 采用 1.2/0.75、RRF 常数保留 60、Qdrant M 保留 16，并把 Qdrant 官方 ef_construct=100 / search ef=100 作为待验证参考档；政策条款边界 + overlap 0、loop 5/12 则保留为 009 的安全/领域起点。详细值见 `configs/step9_reference_defaults.yaml`。

**第二项任务的结论是“集合有骨架，但还没有达到全量指标实验就绪”**。最先要修的不是再加模型，而是 dev split、V2 Runner、holdout 泄漏、政策 ID 映射和确定性评分字段。完成这五项后，可以用当前集合先做一轮低成本/零成本筛选；在 FPR、Policy RAG 和稀有意图补强前，不应把结果写成总体质量或生产可靠性结论。

## 八、2.0 baseline 收口（2026-09-05）

用户确认 2.0 先交付可运行、可复现、可发布的工程基线，不把当前阶段的参数最优作为发布条件。因此，本审计中“未达到全量实验就绪”的项目继续保留为研究型缺口，但不再阻断 2.0 的工程收口：

- 2.0 基线集中记录在 `experiments/configs/step9_baseline_profile.yaml`，原始初始化证据和机器可读收口结果分别为 `step9-initialization-2026-09-05.json` 与 `step9-baseline-closure-2026-09-05.json`；
- 132 条 V2、103 条 Policy RAG 文档、28 条查询、9 条 FPR 探针和当前评分字段分布保持原样；不修改冻结案例、期望值或 holdout，不启动付费模型 A/B；
- `reference-only`、`measured-smoke-only`、`untested` 是基线的证据状态，不是质量等级。2.0 不宣称总体准确率、FPR 总体 ≤2%、模型/Chunk/HNSW/Rerank 最优或生产可靠性；
- dev/regression 拆分、干净 retrieval split、完整 V2 逐案质量 Runner、Policy ID 映射、FPR 扩展、稀有意图补强和模型/参数 A/B 统一登记为 2.1+ backlog；holdout 16 条继续锁定。
