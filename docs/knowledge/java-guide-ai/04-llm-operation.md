# 04｜万字拆解 LLM 运行机制

来源：[JavaGuide 原文](https://javaguide.cn/ai/llm-basis/llm-operation-mechanism.html)

## 从文本到输出

模型接收的不是“字”，而是模型对应 tokenizer 产生的 Token 序列。模型逐步预测下一个 Token，生成是自回归过程；Token 数、Tokenizer 版本和模型实现相关，中文/英文的粗略换算只能做估算，不能用于精确计费或容量承诺。

Transformer 通过 Embedding、位置/位置信息、Self-Attention 和前馈层处理序列。Attention 的计算与序列长度存在显著成本，长上下文可能增加首字延迟、显存和噪声；上下文窗口包含 System、工具 Schema、用户输入、历史、RAG/Memory 和输出，不等于最大输出长度。

## 上下文和成本

调用前应估算 `input + max_output` 是否超过模型窗口，并为工具调用、重试和输出预留余量。长上下文的风险不只是超限，还有 Lost in the Middle、无关材料稀释注意力和输入成本上升。优先移除低相关资料、去重、摘要、按需检索和裁剪，不应盲目扩大窗口。

成本要拆成输入、输出、缓存命中、可能的 reasoning token 等维度，并关联模型版本、价格版本和场景。Streaming 主要改善 TTFT 和感知体验，不会自动降低总 Token 或总成本。

## 采样参数与可重复性

模型输出经 logits、softmax 形成概率分布；Temperature、Top-p、Top-k、停止条件和惩罚项改变采样行为。`temperature=0` 也不保证跨版本、并发或供应商实现绝对可重复。推理模型的 thinking/reasoning 参数、Token 统计和限制方式由具体供应商决定，不能把一个 API 的字段当作通用标准。

调试时记录实际模型、采样参数、最大输出、finish reason、输入/输出/缓存 Token、截断情况和响应版本。否则同一 Prompt 产生变化时无法判断是模型升级、上下文变化还是采样参数造成的。

## 对 009 的落点

ServiceFlow 当前更重要的是理解模型输入只是“意图提议”，业务规则仍由 Python 决定。若 2.0 增加长 Prompt、知识库或更多工具，应先建立实际 Token/延迟观测，再决定摘要、路由和上下文策略；不把文章中的 Token 估算或上下文比例当作项目默认值。

## 关键词

Tokenizer、Token、Autoregressive、Attention、Context Window、Lost in the Middle、TTFT、Sampling、Usage、缓存。
