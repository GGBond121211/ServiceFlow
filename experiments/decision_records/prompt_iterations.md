# Prompt 迭代史

对应计划补充 U。**基础设施（Template/Version/Release/Run 四层）在 Step 3，本文件记录的是过程。**

要求：至少 3 次有据可查的迭代，**其中至少一次是"改了却变差、于是回滚"**。
那类记录可信度最高，也直接回答"你怎么知道改动有效"。

## 记录模板

### 迭代 N：<一句话说明改了什么>

- **触发**：哪个失败案例 / 哪个指标回退
- **改动**：具体改了哪一句（给出 diff 或前后对照）
- **假设**：预期哪个指标会变好
- **结果**：Intent Accuracy / Clarification Precision / Policy Routing 前后对比，指向 `../results/<experimentId>/`
- **副作用**：有没有引入新的失败
- **结论**：采纳 / 回滚，以及原因

## 当前状态

○ 骨架。Step 9 开始填。V1 的 `service_agent_v1` 作为起点版本，其内容已冻结在
`../configs/baseline.yaml`。
