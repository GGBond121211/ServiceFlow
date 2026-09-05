# ServiceFlow 2.0.1

日期：2026-09-05。此版本是 2.0 演示主路径的正确性修复、复杂度收敛与事实口径修正，不是生产化升级。

## 本次修复

| 优先级 | 改动 | 主要证据 |
| --- | --- | --- |
| P0 | 退款执行复用确定性政策，审批时重新检查资格；订单和审批使用条件更新，避免重复退款与覆盖终态 | `application/case_service.py`、`infrastructure/repositories.py`、`tests/integration/test_confirmation_approval.py` |
| P1 | API 查询与 Agent 使用同一应用数据库；订单、工单和会话校验演示用户；审批/重置区分演示角色 | `api/dependencies.py`、`api/routes.py`、`tests/api/` |
| P1 | 确认可拒绝，重复确认返回 409，待确认/审批时禁止覆盖当前动作；恢复后回读数据库 | `api/routes.py`、`infrastructure/tables.py`、`tests/api/test_agent_api.py` |
| P1 | Native 路径补齐取消订单；换货检查问题类型和政策；政策检索向模型提供正文、来源与版本 | `agent/tool_registry.py`、`infrastructure/tool_executor.py`、`tests/integration/test_tool_risk_gates.py` |
| P1 | Native 路径传入有界对话历史，并重新读取订单/工单状态；修复跨用户工单读取 | `agent/graph.py`、`agent/tool_loop.py`、`tests/agent/test_native_tool_loop.py` |
| P2 | 移除仅用来显示计数的 resources/prompts discovery、首次高风险提议触发的重复模型调用；诊断记录限制为最近 100 条，运行时不再积存内存 Span | `agent/tool_loop.py`、`infrastructure/model_gateway.py`、`infrastructure/otel.py` |
| P2 | 全部模型熔断时返回明确的 CIRCUIT_OPEN；服务关闭时释放自身 telemetry | `infrastructure/model_gateway.py`、`infrastructure/gateway_server.py`、Gateway/OTel 集成测试 |
| P3 | 前端确认/拒绝按钮、订单与用户对应关系、忙碌态；回环端口、容器政策路径和版本号统一 | `frontend/`、`compose.yaml`、README 与公开文档 |

以上源码与软件测试路径相对 `backend/`。冻结的 `tests/eval_cases/*.jsonl`、政策阈值与评测期望未修改。

原 Native 退款成功测试使用的 ORDER-004 已超过固定演示日期下的退款期限；成功用例改用期限内的 ORDER-007，另增低额/高额过期拒绝与审批时过期回归。部分集成测试的成功订单日期同步修正。这是修正 Fake 测试前提，不是修改冻结评测答案来提高分数。

## 保留与删减的复杂度

保留代码控制的资源归属、确认绑定、人工审批、政策检查、数据库条件更新、最终状态回读，以及有界 Tool Loop：它们分别保护越权、错单执行、模型自批、过期退款、并发重复副作用和状态幻觉等具体风险。

删除没有影响工具选择的 discovery 计数和没有业务授权作用的重复模型调用；诊断缓存与运行时 Span 保留改为有界或交给 OTLP 后端。未据此声称测得延迟或质量提升。

Provider/Operation/Outbox/Worker、ContextAssembler/Memory/PromptRelease 等已有组件保留；它们有独立用途和测试，但不能据此宣称全部串入当前 Web Native 售后主路径。未做跨模块重写或批量删测试。

## 验证记录

2026-09-05，本机 Windows：

- `uv run python -m pytest -q --basetemp=../work/pytest-serviceflow-201-final`：**312 passed, 1 skipped，252.12 秒**。
- 跳过项是需要 MySQL 配置的集成 smoke；本次软件回归主要使用 SQLite 与 Fake Model，不能证明 MySQL 并发或真实模型总体质量。
- 首轮全量为 302 passed / 2 failed / 1 skipped。两处失败分别暴露 API 数据库注入不一致、测试依赖运行时内存 Span；修复后相关 33 项窄测与上述全量通过。
- `ruff check`、Python compileall、前端 `node --check`、`git diff --check` 通过。
- `experiments/runner.py list` 成功列出 V1 100 / V2 132 条输入；这只是集合清点，不是模型评测得分。
- `docker compose config --quiet` 与 `docker build --tag serviceflow:2.0.1 ./backend` 通过。

没有付费模型调用、真实业务 Provider 调用、重新部署现有 Compose 服务或重新执行浏览器业务演示。此前 2.0 的运行记录仍是历史证据；本次构建成功不等于全部容器及业务端到端运行成功。提交后的 CI/CD 状态以对应 GitHub Actions 运行记录为准。

## 明确保留的边界与后续版本

- `X-ServiceFlow-User` / `X-ServiceFlow-Demo-Role` 可由调用方自行填写，只模拟主体/角色，不是认证机制。默认仅绑定回环地址；公开服务前必须接入可信身份。
- 数据库 confirmation claim 保证同一待确认动作至多被领取一次，不保证 claim、业务提交、checkpoint 更新之间的 exactly-once。领取后崩溃需人工核对，不能自动重放；同一会话多写者并发串行化尚未实现。
- 固定演示基准日仍为 **2026-08-01**；退货和赔付是人工工单，非真实退货/付款。
- Native 历史只提供指代上下文，不是完整 Memory/Context/PromptRelease 集成；自然语言总结仍可能出错，结构化数据库状态是事实依据。
- 内部 MCP-style 传输不代表标准 MCP SDK 互操作；Answerability 不代表完整的语义冲突裁决。
- 2.1：Native 逐案 Runner、dev split/FPR 扩展、真实模型/检索/参数对照、跨模块主路径取舍与集成；须先确定预算，不能从软件测试推导效果。
- 2.2 或真实部署需求出现时：认证、同会话并发及崩溃恢复闭环、外部 Provider、生产容量与运维。K8s 仍只有静态渲染证据。

## 升级与回退

`confirmation_claims` 是新增表，现有 schema 初始化会创建它。没有删除或重置数据。升级或回退前暂停业务会话并备份数据库；遇到领取后未完成的确认先核对订单、工单与 checkpoint。回退旧代码会失去本次防重等保护，因此应先隔离服务再处理未完成会话。不要用 `docker compose down -v`、删表或重置数据库作为常规回退。
