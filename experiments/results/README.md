# 实验原始结果

**规则：这里的文件是决策台账「依据」列的唯一合法来源。** 台账里任何结论都必须能指到本目录下的具体文件。

## 目录约定

```
results/
├─ <experimentId>/            # 每次实验一个目录
│   ├─ spec.yaml              # 本次的 ExperimentSpec（含 changedVariable）
│   ├─ raw.jsonl              # 逐案原始结果，不做任何筛选
│   ├─ summary.md             # 汇总：均值 / 最好 / 最差 / P50 / P95 / Token / Cost
│   └─ trace/                 # 关键案例的 Trace 导出
└─ simulator_traces/          # 用户模拟器录制轨迹（按 caseId 命名）
```

## 纪律

- **不删除失败结果**，不挑选最好的 trial 上报。
- 每次实验只改一个主要变量；固定变量必须写进 `spec.yaml`。
- `dev / regression / golden` 用于调参，**`holdout` 只在最终验收打开一次**。
- 结果文件不进公开仓库（`outputs/` 与本目录均已 gitignore 或按需处理），但结论进
  `../DECISIONS.md`，并在公开文档中标注"本地运行、模拟数据"。
- 模拟器轨迹要记录 `simulator_model` 与 `dataset_version`；Agent 行为变化导致回放
  miss 时**重新录制**，不要放宽回放规则。
