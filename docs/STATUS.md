# 当前状态

- 最后更新：2026-08-21
- 项目阶段：ServiceFlow V1 已完成；第一阶段评测已扩展为100案
- 当前风险等级：L2
- 当前 Task：分阶段耗时记录与 DeepSeek 思考模式 A/B 实验已完成，等待用户验收
- 下一 Task：用户确认后再决定是否合并到主分支
- 阻塞：无

## 分阶段耗时与 DeepSeek 思考模式 A/B（2026-08-21）

- API 已通过 `Server-Timing` 暴露模型调用、意图提取、LangGraph、数据库连接、SQL、数据库
  阶段、业务规则和响应组装耗时；真实压力测试同步记录客户端 HTTP 往返以及往返减服务端的
  网络、传输和客户端调度差值。
- SQLAlchemy 引擎通过执行事件累计真实 DBAPI SQL 耗时；Graph 在每个数据库阶段显式测量
  连接池连接获取时间。数据库阶段总耗时仍包含 ORM 映射、事务提交和业务服务调用。
- 新增流式模型探针 `serviceflow.evaluation.model_latency`，能够测量响应头、首 Token
  （TTFT）、首 Token 后生成和完整响应；报告不包含 API Key。
- 软件回归：`62 passed, 1 skipped`；Ruff、Python 编译和 uv 锁文件检查通过。

相同提示词、顺序执行 5 次的模型直连结果：

| 模式 | 平均 TTFT | 平均生成 | 平均完整响应 | 成功 |
| --- | ---: | ---: | ---: | ---: |
| 默认思考 high | 2223.77 ms | 165.69 ms | 2389.46 ms | 5/5 |
| 关闭思考 | 447.68 ms | 280.11 ms | 727.79 ms | 5/5 |
| 思考 low | 3053.43 ms | 192.44 ms | 3245.86 ms | 5/5 |

- 关闭思考相对默认 high：平均 TTFT 下降 `79.87%`，平均完整响应下降 `69.54%`。默认 high
  的 5 次请求均命中 256 个前缀缓存 Token；关闭思考的第一条请求未命中缓存仍明显更快。
- `low` 在本轮没有形成稳定加速，并出现一次 9.08 秒长尾，说明降低推理强度不能消除服务端
  排队和调度抖动。

相同前 20 案、并发 10 的端到端 A/B：

| 模式 | 通过 | 吞吐 | 案例 P50 | 案例 P95 | 模型平均 | 模型 P95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 默认思考 high | 19/20 | 1.00 案例/秒 | 3104.03 ms | 6456.17 ms | 3539.07 ms | 6056.19 ms |
| 关闭思考 | 19/20 | 4.14 案例/秒 | 1161.12 ms | 3069.19 ms | 957.94 ms | 1128.13 ms |

完整 100 案、并发 10 的模式对照：

| 模式 | 通过 | 吞吐 | 案例 P50 | 案例 P95 | 模型平均 | 模型 P95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 同日默认 high | 95/100 | 1.55 案例/秒 | 3169.70 ms | 13340.51 ms | 3588.19 ms | 7261.56 ms |
| 关闭思考 | 91/100 | 4.39 案例/秒 | 1082.37 ms | 2586.83 ms | 969.77 ms | 1069.34 ms |
| 思考 low | 92/100 | 2.41 案例/秒 | 2220.02 ms | 6679.97 ms | 2195.70 ms | 5069.03 ms |

- 关闭思考显著提升速度，但复杂换货、多轮改口和歧义追问的通过率低于同日 high；`low` 只追回
  1 个案例且明显变慢。因此 Compose 与 `.env.example` 最终仍默认 `enabled + high`，保留
  `disabled` 作为明确接受语义回归后的低延迟选项。
- 关闭思考的 100 案中模型 P95 约 1.07 秒，但最大值仍达到 19.62 秒，证明 Base URL 和 API
  Key 并不意味着每次请求必须慢，也不能保证每次都快；外部模型服务仍存在偶发长尾。
- 产物：`serviceflow-model-latency-*.json/md`、`serviceflow-phase-timing-thinking-*.json/md`、
  `serviceflow-phase-timing-thinking-high-100-c10-20260821.json/md`，
  均位于被 Git 忽略的 `outputs/evaluation/`。

## 异步全链路实验分支（2026-08-20）

- 分支：`experiment/async-full-chain-20260820`；本轮没有合并到主分支。
- 后端路由、LangGraph 节点、模型适配器、应用服务、业务工具、SQLAlchemy 仓储、评测 runner、CLI 和测试均已改为异步 I/O；纯政策判断和序列化函数保持同步。
- 数据库驱动：Compose 使用 `mysql+aiomysql`，SQLite 隔离测试使用 `sqlite+aiosqlite`；新增 `aiomysql`、`aiosqlite` 和 `pytest-asyncio` 锁定依赖。
- 软件回归：`58 passed, 1 skipped`；连接当前 Compose MySQL 后的集成复验为 `59 passed`。
- 异步压力测试：基础 40 案 + 复杂中文 60 案，共 100 个逻辑用户；并发档位 1、10、25、50、100 均为 `100 passed, 0 failed, 0 HTTP errors`。
- 压力测试使用确定性异步回放模型，验证异步 API、LangGraph、数据库和审批恢复，不代表真实模型语义质量；结果文件为 `outputs/evaluation/serviceflow-async-pressure.json` 和对应 Markdown 报告。
- 压力运行会打印 LangGraph 对自定义枚举 checkpoint 的未来严格模式兼容性提示；当前不影响结果，主分支原有文档已经记录该限制。
- Docker Desktop、MySQL 和 API 已在本分支实际启动；真实压测使用 API 容器内的 `mysql+aiomysql`，模型为 `deepseek-v4-flash`。

## 真实 Docker + MySQL + DeepSeek 压测（2026-08-20）

- 测试链路：真实 Docker Compose API → FastAPI → LangGraph → AsyncOpenAI/DeepSeek →
  真实 MySQL；每个案例使用独立临时用户和订单，最终状态直接从 MySQL 读取。
- 100 个案例在并发 1、10、50、100 下分别执行；300 并发为同一组 100 个案例重复 3 次，
  共 300 个独立逻辑用户。测试结束后确认临时用户和订单均已清理，原演示数据仍为 3 个用户、
  12 个订单。

| 并发 | 案例 | 通过/失败 | 请求数 | HTTP 错误 | 吞吐（案例/秒） | P50 | P95 | P99 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 100 | 94/6 | 231 | 0 | 0.20 | 2.78 秒 | 17.65 秒 | 23.13 秒 |
| 10 | 100 | 95/5 | 232 | 0 | 1.86 | 2.59 秒 | 13.24 秒 | 16.52 秒 |
| 50 | 100 | 95/5 | 232 | 0 | 3.64 | 3.98 秒 | 13.97 秒 | 17.22 秒 |
| 100 | 100 | 93/7 | 231 | 0 | 3.16 | 9.25 秒 | 20.43 秒 | 25.26 秒 |
| 300 | 300 | 277/23 | 692 | 0 | 4.56 | 24.31 秒 | 29.30 秒 | 41.13 秒 |

- 300 并发的 23 个失败中，22 个是 `business_mismatch`，1 个是
  `transport_error: Server disconnected without sending a response`；没有观察到 HTTP 4xx/5xx、
  限流或 API/MySQL 容器重启。这个单次传输错误只能说明高并发下出现过一次连接级异常，
  不能据此断言具体根因。
- 主要语义短板是复杂中文换货/维修与工单的边界、高金额退款审批、歧义请求追问，以及
  “查询背景 + 隐含办理诉求”的组合句。它们不是数据库写入失败，而是模型决策与案例期望不一致。
- 300 并发后容器仍保持运行；采样时 API 约 `206 MiB`、MySQL 约 `503 MiB`，CPU 分别约
  `0.39%`、`1.66%`。这是测试结束后的采样，不等同于全程峰值，但没有显示出 MySQL CPU
  已经打满的证据。真实模型响应与其排队/并发能力是当前第一嫌疑瓶颈。
- 产物：`outputs/evaluation/serviceflow-real-deepseek-100-l1.json/md`、`l10`、`l50`、
  `l100`、`serviceflow-real-deepseek-300-l300.json/md`，以及一案真实冒烟报告。

## DeepSeek 官方限速核对（2026-08-20）

- 已读取 [DeepSeek 官方限速与隔离文档](https://api-docs.deepseek.com/zh-cn/quick_start/rate_limit)：
  当前文档列出 `deepseek-v4-flash` 账号级并发上限为 2500，`deepseek-v4-pro` 为 500；一个
  请求从发出到响应完成都计入并发，超过限制时应返回 HTTP 429。
- 本项目真实压测使用 `deepseek-v4-flash`，最高峰值用户为 300，没有出现 HTTP 429、HTTP 4xx/5xx
  或限流错误。因此，当前结果不能解释为撞上官方 2500 并发硬上限。
- 普通账号的多个 `user_id` 会合并计算账号总并发；当前模型适配器没有向 DeepSeek 额外传递
  `user_id`，本轮按账号总并发理解即可。300 并发下的连接断开更像一次连接级异常，仍需重复
  试验才能判断是否稳定复现。

## MySQL 查询优化实验（2026-08-20）

- 当前 6 张业务表均为 InnoDB；订单主键、订单明细的 `order_id` 和三类售后记录的
  `order_id` 均已有索引，外键关系完整。
- 已为 `refunds`、`tickets`、`approvals` 增加 `(order_id, created_at)` 联合索引；已有数据库通过
  幂等建表流程补齐索引，旧单列索引暂时保留以便安全回滚和做前后对照。
- 已将评测终态读取中的“查询全部历史记录后在 Python 取第一条”改为数据库侧
  `ORDER BY created_at DESC LIMIT 1`。
- 真实 MySQL 基准使用目标订单每张表 2000 条历史记录，以及 100 个其他订单、每个订单 180 条
  噪声记录；每种查询预热 5 次、测量 30 次。旧查询使用旧单列索引，新查询使用实际联合索引。

| 表 | 旧 P95 | 新 P95 | P95 降幅 | 返回行数 | 旧 Extra | 新 Extra |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| `refunds` | 47.2018 ms | 3.7418 ms | 92.07% | 2000 → 1 | `Using filesort` | `Backward index scan` |
| `tickets` | 46.7192 ms | 2.4284 ms | 94.80% | 2000 → 1 | `Using filesort` | `Backward index scan` |
| `approvals` | 41.9089 ms | 2.9549 ms | 92.95% | 2000 → 1 | `Using filesort` | `Backward index scan` |

- 这组结果直接证明了 SQL 层改造有效：联合索引消除了排序步骤，`LIMIT 1` 将返回数据量从
  2000 行降到 1 行。平均延迟也分别下降约 92.50%、94.54% 和 92.75%。
- 随后用改造后的真实 Docker API、真实 MySQL 和真实 DeepSeek 重跑 100 案：并发 10 为 `93/100`
  通过、P95 `13.8948` 秒；并发 50 为 `92/100` 通过、P95 `18.0988` 秒。失败全部是模型业务
  语义不匹配，没有 HTTP、限流或传输错误。端到端总耗时没有显示 SQL 级别的明显下降，说明
  模型响应时间远大于这几次状态查询；这不是数据库改造失败，而是数据库优化收益被端到端大模型
  耗时淹没。
- 产物：`outputs/evaluation/serviceflow-mysql-query-optimization-20260820-v2.json/md`、
  `outputs/evaluation/serviceflow-real-deepseek-db-optimization-20260820.json/md`。

## 中文可读性维护

- 已将运行时意图 Prompt、Agent 用户回复、政策原因、评测报告和前端栏目改为中文；订单字段、状态枚举、工具名、政策编号和 JSON 契约继续保留英文。
- 已展开源码与测试中的列表/集合推导式、三元表达式、walrus 写法、前端模板 `map` 和单行 CSS，便于逐步阅读和调试。
- 验证：前端 `node --check frontend/app.js` 通过；Ruff 检查和格式检查通过；默认 SQLite 测试 `58 passed, 1 skipped`，连接 MySQL 后全量测试 `59 passed`，仅有 1 条既有迁移警告。

## MySQL 存储迁移

- 已将最终演示数据库从 PostgreSQL 切换为 MySQL 8.4；异步连接驱动为 `mysql+aiomysql`。
- Compose 服务由 `postgres` 改为 `mysql`，宿主机数据库端口由 `54329` 改为 `33069`。
- SQLite 继续用于快速、隔离的软件测试；MySQL 用于 Compose 集成和浏览器演示。
- MySQL 容器中已确认 6 张业务表，演示数据为 3 个用户、12 个订单；按“先重置、后查询”顺序读取 `ORDER-001` 正常返回。

## 前端精简与数据库核验

- 已移除首页顶部宣传区：主标题、说明文字和“100 冻结评测案例”；
- 已移除页面底部说明栏；保留演示上下文、售后对话、业务状态和工具轨迹；
- `node --check frontend/app.js` 通过，源码中不再包含上述顶部和底部页面元素；
- MySQL 只读核验：`ORDER-001` 的最终状态为 `cancelled`，金额为 `199.00`，取消动作已真实写入数据库。

## 启动辅助文档

- 已在项目根目录新增 `启动与常用命令.txt`，包含 Docker Desktop、Compose、API、前端、MySQL 核验、日志、环境变量和常见排障命令；
- 文档不保存真实 API Key，日常启动优先使用已构建镜像执行 `docker compose up -d`。

## 3 天后端学习计划可视化

- 已新增独立 `learning_visualizer/` 目录，不修改或调用现有业务运行时；
- 页面把权威学习计划整理为 3 天、6 个可点击学习单元；
- 三张函数图分别展示一次请求主链、确定性业务写入和高金额审批中断/恢复；
- 每个节点使用真实函数名和完整文件路径，并提供上一步、当前、下一步、输入、输出、失败分支和教学数据包；
- 页面只使用 HTML、CSS、Vanilla JavaScript、DOM 和 SVG，不请求业务 API、模型或数据库。

## V1 100案评测扩展

- [x] 原核心40案与新增复杂中文60案共同归入第一阶段，合计100案；复杂分区包含12条单句多语义、10条隐含诉求、10条噪声背景、10条否定改口、12条多轮状态和6条歧义追问。
- 合同验证：`uv run pytest tests/evals/test_complex_eval_case_contract.py -q`，4项通过。
- 全部案例为原创模拟国内电商售后表达；没有英文意图测试句，也没有复制外部数据集原文。
- 用户输出原则已纠正：普通成功只展示简洁结果和必要状态；完整政策、工具与检索轨迹保留在开发评测层。
- 真实模型100/100案执行完成：总体 Outcome 95.00%、Final State 98.00%、Policy 95.00%、Tool 98.00%、Clarification 91.67%。
- 核心40案 Outcome 97.50%；复杂中文60案 Outcome 93.33%；完整失败5案全部保留。
- 多轮状态类别 Outcome 83.33%，仍是最明显短板；未在本任务提前修改 Prompt、Agent 或冻结答案。
- 产物：`outputs/evaluation/serviceflow-v1-100-results.json`、`outputs/evaluation/serviceflow-v1-100-report.md`。

## 已完成范围

- [x] Task 00：项目事实、边界、架构、评测和实施计划
- [x] Task 01—03：Python 工具链、领域对象和确定性售后政策
- [x] Task 04—05：SQLite 仓储、MySQL 与确定性种子数据
- [x] Task 06—07：应用服务与非 Agent FastAPI 业务接口
- [x] Task 08—10：10 案基线、模型适配器与结构化意图
- [x] Task 11—12：LangGraph 单 Agent 图与审批中断恢复
- [x] Task 13：Agent 会话 HTTP API
- [x] Task 14：40 案 runner、指标、报告和真实模型评测
- [x] Task 15：原生浏览器演示页面与三条流程
- [x] Task 16：FastAPI 容器与 MySQL + API Compose
- [x] Task 17：最终复验、开发指南、作品集和维护交接

## Task 17 最终验证

### Task 16 独立复验

- `docker compose config`：通过，只有 `mysql` 和 `api` 两个服务；
- Docker Desktop 启动失败根因为 `%LOCALAPPDATA%\Docker\run\dockerInference` 损坏的 AF_UNIX `ReparsePoint`，与项目 Dockerfile/Compose 无关；
- 将损坏的临时 `run` 目录可逆重命名为 `run-corrupt-20260819` 后，Docker Desktop 4.41.2 / Engine 28.1.1 正常恢复；
- `docker compose build`：通过，API 镜像为 `project-0009-serviceflow-api`；
- `docker compose up -d`：MySQL 8.4 和 FastAPI 均运行，端口为 `33069` 与 `8009`；
- HTTP 冒烟：health=`ok`，reset=`3 users / 12 orders`，`ORDER-001=paid / 199.00`。
- 最终检查发现并修复 Compose API 未挂载根目录评测产物导致报告链接 500；新增只读挂载后 `/evaluation/serviceflow-v1-report.md` 可由容器提供。

### 全量软件验证

- `uv sync --locked`：通过，锁定依赖一致；
- 设置本地 Compose MySQL URL 后运行 `uv run pytest -q --basetemp=./.pytest-mysql-final`：`59 passed`；
- `uv run ruff check .`：通过；
- `uv run ruff format --check .`：51 个文件格式正确；
- 唯一软件测试提示是 FastAPI/Starlette `TestClient` 的未来 `httpx2` 迁移提示，当前行为正常。

### 真实 40 案评测

- 模型：`deepseek-v4-flash`；Prompt：`service_agent_v1`；
- 40/40 案执行完成；
- Task Outcome Accuracy：95.00%；
- Final State Accuracy：97.50%；
- Policy Routing Accuracy：95.00%；
- Tool Selection Accuracy：97.50%；
- Clarification Completion Rate：83.33%；
- 总耗时：149185.29 ms；平均单案：3729.63 ms；
- Token：输入 14648，输出 13628；
- 保留失败：`refund_high_rejected_001`、`clarify_exchange_order_001`；冻结答案未修改；
- 产物：`outputs/evaluation/serviceflow-v1-results.json`、`outputs/evaluation/serviceflow-v1-report.md`。
- `.gitignore` 只放行上述两个固定评测产物，其他 `outputs/` 运行文件继续忽略。

### 浏览器与 MySQL 验收

- 未发货取消：`POL-CANCEL-01`，`get_order → cancel_order`，页面终态 `cancelled`；
- 小额退款：`POL-REFUND-01`，`get_order → request_refund`，页面终态 `refunded / completed`；
- 高金额退款：同一 thread 从 `approval_required / pending` 恢复，轨迹为 `get_order → create_approval → decide_approval`，页面终态 `refunded / completed / approved`；
- MySQL 直接查询确认 `ORDER-003=refunded`、审批 `approved`、退款 `completed / 899.00`。
- 最终执行 `docker compose down` 并停止前端静态服务器；`5173`、`8009`、`33069` 端口均已释放，MySQL 数据卷保留。

## 真实限制

- 所有数据、政策和审批决定均为模拟内容，不接真实订单、支付、物流或客户系统；
- API 会话与 LangGraph checkpoint 使用进程内存，API 重启后不恢复未完成 thread，数据库业务状态仍保留；
- 两个真实模型失败案例说明口语意图和多轮问题类型合并仍可出错；
- 项目不包含登录、鉴权、权限、风控、生产安全、高可用、重试、缓存、多 Agent、Redis、消息队列、向量数据库或复杂 RAG；
- LangGraph 1.2.10 对自定义枚举 checkpoint 反序列化有未来严格模式提示，当前审批恢复和评测正常，V1 不为尚未发生的版本失败增加兼容层。

## V1 停止点

主分支 V1 的核心业务、Agent、API、MySQL、Compose、浏览器和100案评测均已有真实证据。异步改造目前只存在于实验分支，待用户验收后再决定是否合并；第二阶段仍需先根据真实模型失败重新定义任务和验收条件。
