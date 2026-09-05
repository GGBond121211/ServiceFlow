# 29｜AI 核心概念总览

来源：[JavaGuide 原文](https://javaguide.cn/ai/ai-core-concepts.html)（约 10430 字）

读取日期：2026-09-02。侧边栏位置：「入门总览」，是整个专题的第一篇。

原文自述「只做原文摘录和概念归类，不重新改写已有解释」，因此本篇内容与 04–28 各专题笔记高度重叠。它的价值不在新知识，而在**给出一套统一的概念分层口径**，可用于快速校准术语。

## 三条主线

### 一、大模型基础：自回归生成是所有概念的锚点

原文的组织方式值得记：先讲自回归生成（模型按已有上下文预测下一个 Token，追加后继续预测），再把其余概念挂上去——

- **Token**：模型每一步"补"的文本碎片，是"模型的阅读单位"。用 BPE/Unigram 等子词切分在"词表大小"与"序列长度"之间折中，所以既不是字也不是词。工程上用经验估算做容量规划，用 API 返回的 `usage` 做精确计费。
- **上下文窗口**：一次调用的总 Token 上限，是模型的"工作记忆"。被 System Prompt、历史、RAG 片段、工具 Schema、格式开销和输出共同占用，因此可用的"有效业务内容"远小于标称值。多数模型输入输出合计计算，但部分供应商（如 Gemini）分别设限。
- **采样参数**：logits → softmax → 抽签。Temperature 调分布形状，Top-p/Top-k 砍候选池，Penalty 抑制复读。
- **Prompt**：作用是"缩小模型的搜索范围"。四要素 Role / Task / Context / Format。
- **结构化输出**：三者不在同一层——JSON Mode 是**输出模式**（保证合法 JSON），JSON Schema 是**结构描述规范**（契约格式），Structured Outputs 是**供应商的生成能力**（按 Schema 生成）。Schema 本身不是输出方式。
- **Function Calling**：模型没有执行你的代码，它只生成**结构化的工具调用意图**；执行者是业务服务 / Agent Runtime / MCP Host。回填结果时 `tool_use_id` 必须严格匹配（Anthropic 要求，Gemini 3 同样为每个 functionCall 生成唯一 id），否则并行调用场景下结果会错配。

### 二、Agent：Agent = LLM + Planning + Memory + Tools

- **Agent Loop** 每轮三件事：LLM 推理、调用工具、把结果写回上下文。安全兜底是最大迭代轮次（原文给的经验值 10–20 轮）或 Token 阈值。原文明确：**工程难点不在 while 循环，而在上下文管理**。
- **ReAct**（Yao 等，2022）：推理与行动交替，走一步看一步。代价是多轮迭代增加延迟，且效果依赖工具与 Skills 质量。
- **Plan-and-Execute**（LangChain，2023）：先出全局分步计划再执行，适合步骤多、依赖明确的长任务；缺点是计划定死后动态容错弱，更接近静态工作流。**两者可组合**：CoT 出全局步骤，每步内部嵌 ReAct 子循环。
- **纯 Agent / AI 工作流 / Agentic Workflow 的控制权归属**：纯 Agent 里 LLM 是决策者；AI 工作流里 LLM 只是一个节点，**控制权在图结构里，不在模型手里**；Agentic Workflow 是全局用 Workflow 管结构、在不确定节点嵌 Agent 子循环。
- **Memory 三类功能划分**（比"长短期"更实用）：事实记忆（知道什么）、经验记忆（如何改进）、工作记忆（当前在想什么）。长期记忆与 RAG 技术相似（都用向量库+语义检索）但**数据来源和生命周期不同**：RAG 检索外部知识，长期记忆保存交互中沉淀、需跨会话复用的个性化信息。
- **概念分层（原文最有用的一段）**：Prompt 是用户表达任务 → Function Calling 是模型表达调用意图 → MCP 负责工具从哪来/怎么连 → Skill 负责"做这类任务的流程和规矩" → Agent 负责任务怎么一步步做完。四者不是竞品。
- **Harness**：`Agent = Model + Harness`，"你不是模型，那你做的东西大概率就是 Harness"。类比 CPU 与操作系统。Prompt / Context / Harness Engineering 是一层套一层，不是同层竞争：分别解决"指令说清楚"、"该给 Agent 看什么"、"系统怎么持续执行/纠偏/观测/恢复"。
- **Loop Engineering**：围绕 Agent 设计可持续运行的反馈循环，七个要素——触发、目标、上下文、行动、观察、状态、停止。其中**状态必须写到外部文件/Issue/数据库，不能只靠当前对话记住**。

### 三、RAG：检索对象决定方案

- RAG 补的是三件事：知识时效性、私有数据访问、幻觉缓解。原文明确"别指望它彻底消除幻觉"——检索错误、上下文噪声、引用错配、模型不遵循指令都会导致错误答案，生产级还要配引用校验、答案评估、拒答和人工反馈闭环。
- 两阶段：离线索引（输入 → 清理 → 增强 Metadata → Chunking → Embedding → 入库）+ 在线检索生成。
- **Embedding 维度不能脱离模型比较**："维度越高语义效果越好"是错的；高维增加存储、索引和相似度计算成本。
- **向量检索只是 RAG 的一种实现**：RAG 还可以用 BM25、SQL、知识图谱、搜索 API 取证。
- 文档处理六环节各自的风险（原文有表）：上传伪造/超限、MIME 不符选错解析器、PDF 多栏与合并单元格丢结构、清洗残留噪声、Chunking 语义截断、Metadata 缺来源页码版本权限、入库维度不一致。原文一句要点：**"如果数据在这一步就已经坏掉了，换模型只会让损坏更稳定。"**
- **Chunking 有实测数据可引**：NVIDIA 测试中 Page-Level Chunking 在金融报告和法律文档上平均准确率 0.648（方差最低），但优势仅 0.3–4.5 个百分点，且 FinanceBench 上 1024-token 切分反而更优（0.579 vs 0.566）。查询类型也影响选择：事实型适合 256–512 Token 小块，分析型适合 1024+ 或页面级。**Parent-Child**：300 Token 小块用于检索，挂载到 1200 Token 父段落用于上下文。
- **Hybrid Search**：向量擅长语义改写（"如何取消订阅"匹配"关闭自动续费"），BM25 擅长精确匹配（错误码 E1027、SKU ABX-4421）。RRF 按排名位置融合，好处是不用强行比较 BM25 分数和余弦分数。原文提醒别神化：文档高度结构化、关键词少时增益有限。
- **Query Rewrite 的六种策略**：规范化改写、Multi-Query、Query Decomposition、Step-back Query、HyDE、Self-Query。**关键坑：必须保留原始 query 一起召回再融合**，否则改写模型理解错意图就全偏。
- **Rerank**：向量检索是双塔（query 和 doc 分别编码），快但粗；Rerank 用 Cross-Encoder 把 query 和候选放一起打分，慢但细。一句话区分：**向量相似度问"这两段话语义接近吗"，Rerank 问"这段话能不能回答这个问题"**。推荐链路：Metadata 预过滤 → Hybrid 粗召回 30–100 → 去重合并 → Rerank 选 5–10 → 压缩入 Prompt。
- **GraphRAG**：重点不是"用了图数据库"，而是**检索对象变了**（节点、边、路径、原文证据）。社区摘要是 Microsoft GraphRAG 等实现采用的索引形式，并非所有 GraphRAG 都要求。

## 对 009 的落点

这篇最适合当**术语校准表**，而不是设计输入。三处可直接对上 009 现状：

1. 原文的"纯 Agent / AI 工作流 / Agentic Workflow"三分法，正好印证 009 的定位：ServiceFlow 的控制权在 `agent/graph.py` 的图结构和 `domain/policies.py` 里，**不在模型手里**，属于典型的受约束 Agentic Workflow。面试叙述可以直接引用这套口径。
2. 原文"Function Calling 是模型生成调用意图、执行者是业务服务"的表述，与 009 的 `agent/tools.py → application/case_service.py` 边界完全一致，可作为对外解释的现成说法。
3. Loop Engineering 的"状态必须写到外部"这条，对应 009 的"终态必须回读数据库、不信回复文本"。可作为同一原则的两种表述。

需要警惕的是：这篇文章把 RAG、Memory、MCP、GraphRAG、Skills 平铺在一起介绍，容易造成"这些都该有"的错觉。**009 目前没有 RAG、没有向量库、没有 MCP、没有跨会话 Memory**，这篇文章的存在不改变这一点，也不构成 2.0 的需求（见 `2.0-preparation.md` 的 8 个待确认问题）。

## 关键词

自回归生成、Token、上下文窗口、采样参数、JSON Mode/Schema/Structured Outputs、tool_use_id、Agent Loop、ReAct、Plan-and-Execute、Agentic Workflow、事实/经验/工作记忆、Model + Harness、Parent-Child Chunk、Hybrid Search、RRF、Query Rewrite、HyDE、Cross-Encoder Rerank、GraphRAG。
