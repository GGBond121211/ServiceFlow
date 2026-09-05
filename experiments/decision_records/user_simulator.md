# 用户模拟器设计（台账 P6、P7）

## 决策一：多轮案例用模拟器，不手写台词（P6）

**候选**：① 手写脚本对话 ② LLM 用户模拟器

**选择**：模拟器。

**依据**：手写对话僵硬、覆盖窄，而且"用户会怎么补充信息"由出题人预设，
测不出真实的追问能力。案例只声明 `reason_for_call` / `known_info` /
`unknown_info` / persona，由模拟器扮演用户——Agent 追问时，落在 `unknown_info`
的必须回答不知道，**"缺信息追问"因此是真被触发的**。

**代价**：需要维护轨迹文件；Agent 行为变化后要重新录制。

**何时会改**：模拟器成本或维护量失控。 **回滚**：退回手写脚本对话。

## 决策二：可复现靠录制-回放，不靠固定 seed（P7）

**候选**：① 固定 seed + `temperature=0` ② 录制-回放

**选择**：录制-回放。

**依据**：托管 API 即使 `temperature=0` 也**不保证**逐次一致——批处理浮点非确定性、
供应商换硬件、模型别名指向的版本悄悄变更、MoE 路由差异。把"固定 seed 即可复现"
写进验收会验收一个做不到的东西。

**架构**（三层）：

| 层 | 由谁决定 | 作用 |
|---|---|---|
| 1. 规则层 | **代码** | 这一轮能不能透露某条信息，由 `known_info`/`unknown_info` 判定 |
| 2. 措辞层 | 模型（仅 record） | 把允许的内容说成符合 persona 的自然中文 |
| 3. 录制-回放 | 文件 | 措辞结果存轨迹，之后默认回放 |

**关键收益**：`不泄漏 unknown_info` 成为**代码级保证**，不是对模型的祈祷。
这与本项目"模型不决定业务、代码决定"的核心主张同构，
证据见 `backend/tests/evals/test_user_simulator_determinism.py::test_leak_detected_when_model_emits_unknown_value`。

**模式**：
- `replay` 默认，零模型调用、逐字节一致、可离线，**CI 中强制使用**；
- `record` 显式开启，产物写 `experiments/results/simulator_traces/`，
  记录 `simulator_model` 与 `dataset_version`。

**miss 处理**：回放遇到未录制的提问**显式抛 `TrajectoryMiss`**，不静默降级。
Agent 行为在各 Step 间会变，miss 是预期会发生的，正确处理是重新录制。
开发期可用 `--allow-live-fallback`，CI 禁用。

**模拟器模型选择**：应与被测 Agent 模型**不同**，避免自我对弈偏差（同模型更容易
"猜到"对方意图，使追问难度失真）。预算受限时可用同供应商不同档位，但必须在报告
中写明并说明这是已知限制。当前 `configs/candidate_models.yaml` 的 `simulator_model.selected`
仍为 null，待 Step 9 与模型 A/B 一并确定。

**代价**：轨迹版本要与案例集版本对应；Agent 每次大改都要重录。
**回滚**：`allow_live_fallback` 可临时绕过，但结果标记为不可用于结论。

## 验收证据

`backend/tests/evals/test_user_simulator_determinism.py` 共 11 项，覆盖：
replay 逐字节一致且 `model_calls == 0`、未录制提问抛 `TrajectoryMiss`、
`--allow-live-fallback` 需显式开启、规则层拒绝透露 `unknown_info`、
泄漏检测、record 模式必须提供模型、replay 模式不得写轨迹、
指纹忽略标点但区分语义、轨迹记录模型与数据集版本。
