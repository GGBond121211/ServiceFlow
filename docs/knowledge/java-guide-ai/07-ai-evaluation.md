# 07｜AI 应用评测体系

来源：[JavaGuide 原文](https://javaguide.cn/ai/llm-basis/llm-evaluation.html)

## 评测对象

公开 Benchmark 只能做粗筛，不能代替业务 Golden Set。业务集应来自高频问题、人工编写的正常/缺失/对抗样本、历史失败、边界和拒答场景，并按业务分布、高风险级别和版本管理。20–50 条可以作为启动样本，但不代表统计结论；规模和置信度要按目标决定。

评测记录至少要区分：Task（一个业务目标）、Trial（一次运行）、Grader（评分器）、Transcript/Trace（执行证据）、Outcome（最终状态）和 Eval Harness（运行环境与版本）。这样“答案写得像”与“数据库状态正确”不会混成一个分数。

## 评分器与指标

规则评分适合 JSON、枚举、退出码、权限和最终状态；LLM-as-Judge 适合语义相关性、完整性、风格和回归初筛；人工复核负责高风险和校准。Judge 会受位置、长度、自夸、参考答案偏差影响，必须保留 unknown/人工复核路径，不能把它当真理。

RAG 评测拆为检索层（Recall@K、Hit、MRR、Context Precision/Recall）和生成层（Faithfulness、Answer Relevance、完整性、引用准确）。不要把“检索到的文档”本身当作金标准；应有人工标注或业务事实。

Agent 评测要看最终业务状态、工具选择 precision/recall/exact set、参数正确性、不必要调用、恢复能力、pass@k 与稳定通过率；可接受的路径不一定只有一种固定顺序。时间变化的数据要区分固定快照回放与实时探针。

## 评测闭环

一个可回放 EvalRecord 应绑定数据集版本、输入、目标模型/Prompt/RAG/Tool 配置、时间/时区、环境、证据、输出、Trace、Outcome、各评分、Judge 说明、根因、Git 提交和阈值。发布流程可分为离线最小回归、完整 Golden/Trace replay、灰度和线上监控；阈值同时看绝对值和相对回归。

Badcase 处理要保存现象和证据，一次只改变少量变量，区分模型、第三方、架构、代码、环境和评分器根因。线上 Trace 脱敏后进入长期回归集，才会形成“发现 → 定位 → 修复 → 回放 → 灰度”的闭环。

## 对 009 的落点

当前 ServiceFlow 的 100 条评测/模拟结果应继续按现有脚本和数据集解释，不能包装为人工语义准确率或生产效果。2.0 的第一步应是维护少量高价值售后 Golden Set，分别断言意图、策略、工具和最终数据库状态，并保留高额退款审批、非法请求、缺字段和恢复路径的证据。

## 关键词

Golden Set、Trial、Grader、Harness、LLM-as-Judge、Faithfulness、业务后置状态、Badcase、回放、灰度。
