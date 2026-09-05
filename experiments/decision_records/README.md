# 决策记录

每份文件展开 `../DECISIONS.md` 中的一到多行。台账是索引，这里是细节。

## 必须回答的三层（写不出第二层就不要建记录）

1. **为什么选它，不选替代方案？** —— 候选必须先声明，包括被淘汰的和淘汰理由。
2. **数据是多少？** —— 指向 `../results/<experimentId>/`，给具体数字，禁止"效果更好"。
3. **代价、失效条件、回滚方式？** —— 什么情况下这个结论会不成立。

## 现有记录

| 文件 | 覆盖台账行 | 状态 |
|---|---|---|
| `dataset_provenance.md` | P5 | ● 已完成 |
| `user_simulator.md` | P6、P7 | ● 已完成 |
| `prompt_iterations.md` | 待定 | ○ 骨架，Step 9 填 |
| `scale_extrapolation.md` | 待定 | ○ 骨架，Step 9 填 |

Step 4 / 8 / 9 / 10 各自会补充 `policy_rag_chunking.md`、`model_selection.md`、
`context_tool_loop.md`、`gateway_cache_worker.md`、`trace_sampling_audit.md`、
`security_gate_tradeoff.md`、`observability_backend.md`。
