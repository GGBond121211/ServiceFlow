# 19｜RAG 文档处理与切分策略

来源：[JavaGuide 原文](https://javaguide.cn/ai/rag/rag-document-processing.html)

## 入库前半段决定上限

文档要经过上传/格式校验 → Layout 解析 → 清洗去噪 → Chunking → Metadata/Embedding → 入库，并在格式、解析和切分阶段分层校验。扩展名/MIME、大小、编码和空文件是早期校验；解析后看空内容、乱码率、长度和结构；切分后看大小分布、边界、截断和抽样召回。解析错误、PDF 多栏顺序、表格关系、标题层级和 OCR 错字一旦丢失，换 Embedding 或向量库无法恢复。

## Chunk 策略

固定长度简单可预测，适合基线但可能切断条件和列表；递归字符切分优先段落/句子边界；语义切分更贴合主题但需要额外 Embedding 和最小块约束；按标题/页/条款/函数的结构切分适合有天然语义边界的文档；Parent-Child 用小子块召回、大父块补上下文；Overlap 只作为评测参数，过小断裂、过大重复。

参数没有通用默认值。FAQ、短政策、接口说明可从较小块起步，教程/技术文档可用中等块，法律条款优先保留法律效力单元，代码按文件/类/函数/注释切。文中给出的 Token 范围只是实验起点，必须用同一问题集比较 Recall、Context Precision、答案和成本。

## 结构与多模态

PDF 多栏要用 Layout-Aware Parser，并检查阅读顺序、页码、合并单元格；Word 不应只信 Heading 样式，要重建标题树；Excel 要按数据区域/表头/行记录保留字段关联；OCR 要做字符、表格、段落和业务一致性校验。图片可走 CLIP + 原图、MLLM 描述 + 文本检索或 Multi-Vector（摘要向量 + 原图 docstore）；表格可转 Markdown 或结构化 JSON；图表必须保留 caption、坐标轴、单位、时间、来源和附近正文。

失败降级要显式：空/不支持格式拒绝，解析失败进人工或备用解析器，乱码尝试 OCR/格式转换，Chunk 异常可用固定长度兜底，部分解析必须标缺页/缺失范围。合同法规等完整性要求高的材料不能悄悄以部分内容对外承诺。

## 对 009 的落点

如果 2.0 建政策知识库，优先从 Markdown/HTML/TXT 和模拟政策开始，验证来源、章节、版本、权限、引用和 chunk 抽样；不要先引入多模态、复杂解析器或对象存储。Java 示例只说明处理思想，不是当前项目依赖。

## 关键词

Layout-aware、Chunking、Recursive、Semantic、Parent-Child、Overlap、PDF/Word/Excel/OCR、Multi-Vector、分层校验、部分解析。
