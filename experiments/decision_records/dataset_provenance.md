# 评测数据来源与授权（台账 P5）

用户 2026-09-02 授权引入外部数据集，边界很窄。本文件是唯一的来源台账。

## 结论：借方法论，只在一处取数据

2026-09-02 用 `gh` 实测核查了候选数据集（stars / license 均为实测值）。
**中文电商售后的 Agent 评测集在公开世界基本不存在**——GitHub 上只找到两个 1–2 star
的小仓库，京东 JDDC 类语料需申请且授权受限。因此 V2 案例集以自建为主，这是稀缺产出。

## 为什么不导入 τ-bench 的业务数据

`sierra-research/tau-bench`（MIT，1417★）与 `tau2-bench`（MIT，1932★）的 retail 域
与 009 高度同构：`envs/retail/rules.py` 等价于我们的 `domain/policies.py`，
`tools/` 里有 `cancel_pending_order`、`exchange_delivered_order_items`、
`get_order_details`，其 `rules.py` 第 4 条要求"任何数据库变更必须先与用户确认细节
并取得明确授权"——与本项目 Step 6 的 `WAITING_CONFIRMATION` 是同一设计。

**但不导入其数据**，三个理由：

1. 它的 retail 政策与 009 V1 历史默认规则不一致；而 009 V1 的 7 天退款、¥500 审批线、
   30 天换货值本身也没有现实探测依据，不能继续冒充 2.0 的最终标准。导入等于用外部业务身份
   替换本项目的业务身份。
2. `tests/eval_cases/*.jsonl` 是冻结集，改动需用户授权。
3. 对外叙述上，"参考了 τ-bench 方法论但没直接用其数据，因为它的政策与我的业务规则
   不一致"比"我用了 τ-bench"更能体现判断力。

## 2026-09-04 · Step 4 政策来源方向修正

用户明确确认：官方法规作为 009 2.0 的首要政策基线。V1 的 7 天 / ¥500 / 30 天只作为冻结历史
实现保留，不代表现实标准，也不代表 2.0 已经选定这些值。

Step 4 采用三层来源：

1. 官方法规：提供法律底线、适用范围、例外、期限计算、退款方式和质量问题的法规入口；
2. τ-Bench / τ²-Bench：只借鉴政策、任务、工具和评测结构，不直接导入其业务数据；
3. ServiceFlow 自建合成政策：把法规条款与项目内部流程整理成带版本、范围、生效期、来源和
   `source_hash` 的 PolicyDocument。没有法规依据的内部阈值必须标记 `project_internal` / `untested`。

JDDC 仍然只在获得授权后使用原始对话；当前没有复制其原始数据。

## 按用途分配

| 用途 | 来源 | License | 落点 |
|---|---|---|---|
| 用例契约结构（`known_info` / `unknown_info` / `initial_state` / `expected`） | τ2-bench | MIT | `case_v2.py` 的字段设计 |
| LLM 用户模拟器 + `unknown_info` 机制 | τ-bench | MIT | `user_simulator.py` |
| `pass^k` 可靠性指标 | τ-bench | MIT | Step 9 指标 |
| train/dev/test + holdout 三分 | τ-bench | MIT | `V2Split` |
| **注入 payload（唯一直接取数据处）** | `uiuc-kang-lab/InjecAgent`(166★)、`ethz-spylab/agentdojo`(790★) | MIT | 3 条案例，已中文化改造并标 `derived_from` |
| 工具选择指标口径 | `ShishirPatil/gorilla` BFCL | Apache-2.0 | Step 9 的 Tool Selection Accuracy |
| 中文多轮语言模式（指代、改口、歧义澄清） | `thu-coai/CrossWOZ`(725★)、`terryqj0107/RiSAWOZ`(68★) | Apache-2.0 / MIT | 仅语言表达模式，**不取业务内容**（其域为旅游/餐饮预订） |

## 直接取用数据的 3 条案例

| 案例 ID | `derived_from` |
|---|---|
| `v2_inj_direct_001` | `InjecAgent(MIT)/direct-instruction-override` |
| `v2_inj_indirect_policy_001` | `AgentDojo(MIT)/indirect-document-injection` |
| `v2_inj_encoding_001` | `InjecAgent(MIT)/encoded-payload` |

均已中文化改造，`origin` 标为 `derived_external`，契约测试强制校验
`derived_from` 存在且含 license 标注。

## 诚信约束（硬性）

- 借用方法论必须在 `docs/public/EVALUATION.md` 署名来源与 license，不得表述为原创。
- **绝不允许声称"在 τ-bench / BFCL 上取得 X 分"**，除非真跑了对方 harness 并附原始输出。
  只借结构时必须写成"参照其方法论自建案例集"。
- `amazon-agi/tau2-bench-verified`（MIT，51★）存在的理由是修正原数据集"任务定义、
  期望动作与政策/数据库内容不一致"。这与本项目 2026-09-02 在 `docs/PORTFOLIO.md`
  发现的 40 案/100 案数字混写属同类问题，因此**冻结基线前的一致性自查是前置动作，
  不是可选项**。

## V2 案例集构成（2026-09-03 生成，132 条）

| 划分 | 条数 | 用途 |
|---|---:|---|
| smoke | 6 | 最短可用路径 |
| regression | 64 | 核心业务，每次改动全跑 |
| golden | 10 | 发布门禁必过 |
| boundary_security | 24 | 注入 16 + 误拦截探针 8 |
| reliability_concurrency | 12 | Provider / 幂等 / Webhook / Worker |
| **holdout** | 16 | **全程锁定，只在最终验收打开一次** |

来源分布：`handcrafted` 129 条、`derived_external` 3 条。
注入变体 8 类全覆盖（direct 3、indirect_policy_doc 3、forged_tool_annotation 2、
tool_result_injection 2、encoding_or_multilingual 2、long_context_dilution 2、
field_level 2、memory_poisoning 2）。共 16 条注入案例，另有 8 条误拦截探针。

**防模板泄漏**：契约测试断言 holdout 与调参集不共用订单号、不共用来意文本。
