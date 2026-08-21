const ROOT = "C:\\Users\\Alex\\Desktop\\workspace\\Project-0009-ServiceFlow";

const PATHS = {
  learningPlan: `${ROOT}\\.hermes\\plans\\2026-08-19_145615-serviceflow-backend-interview-learning.md`,
  frontend: `${ROOT}\\frontend\\app.js`,
  schemas: `${ROOT}\\backend\\src\\serviceflow\\api\\schemas.py`,
  routes: `${ROOT}\\backend\\src\\serviceflow\\api\\routes.py`,
  app: `${ROOT}\\backend\\src\\serviceflow\\api\\app.py`,
  dependencies: `${ROOT}\\backend\\src\\serviceflow\\api\\dependencies.py`,
  graph: `${ROOT}\\backend\\src\\serviceflow\\agent\\graph.py`,
  state: `${ROOT}\\backend\\src\\serviceflow\\agent\\state.py`,
  intent: `${ROOT}\\backend\\src\\serviceflow\\agent\\intent.py`,
  model: `${ROOT}\\backend\\src\\serviceflow\\agent\\model.py`,
  prompt: `${ROOT}\\backend\\src\\serviceflow\\agent\\prompts\\service_agent_v1.txt`,
  tools: `${ROOT}\\backend\\src\\serviceflow\\agent\\tools.py`,
  models: `${ROOT}\\backend\\src\\serviceflow\\domain\\models.py`,
  policies: `${ROOT}\\backend\\src\\serviceflow\\domain\\policies.py`,
  results: `${ROOT}\\backend\\src\\serviceflow\\domain\\results.py`,
  orderService: `${ROOT}\\backend\\src\\serviceflow\\application\\order_service.py`,
  caseService: `${ROOT}\\backend\\src\\serviceflow\\application\\case_service.py`,
  database: `${ROOT}\\backend\\src\\serviceflow\\infrastructure\\database.py`,
  orders: `${ROOT}\\backend\\src\\serviceflow\\infrastructure\\repositories.py`,
  cases: `${ROOT}\\backend\\src\\serviceflow\\infrastructure\\case_repository.py`,
  tables: `${ROOT}\\backend\\src\\serviceflow\\infrastructure\\tables.py`,
};

const STAGE_LABELS = {
  browser: "浏览器 / HTTP",
  api: "FastAPI",
  agent: "Agent / State",
  domain: "确定性政策",
  data: "业务 / 数据库",
};

const ROADMAP = [
  {
    day: "第一天",
    goal: "HTTP 进入后端",
    units: [
      {
        number: 1,
        title: "HTTP 契约和输入输出",
        files: "schemas.py · README · USER_FLOW",
        mode: "request",
        node: "send-message",
      },
      {
        number: 2,
        title: "API 组装和图骨架",
        files: "routes.py · app.py · graph.py",
        mode: "request",
        node: "api-message",
      },
    ],
  },
  {
    day: "第二天",
    goal: "业务如何写进数据库",
    units: [
      {
        number: 3,
        title: "业务词汇和政策判断",
        files: "models.py · results.py · policies.py",
        mode: "business",
        node: "domain-policy",
      },
      {
        number: 4,
        title: "业务执行和持久化",
        files: "case_service.py · repositories.py",
        mode: "business",
        node: "case-refund",
      },
    ],
  },
  {
    day: "第三天",
    goal: "Agent 状态与审批恢复",
    units: [
      {
        number: 5,
        title: "Prompt、意图和 AgentState",
        files: "prompt · intent.py · state.py · tools.py",
        mode: "request",
        node: "extract-intent",
      },
      {
        number: 6,
        title: "LangGraph 节点与审批",
        files: "graph.py · approval API · tests",
        mode: "approval",
        node: "interrupt",
      },
    ],
  },
];

const COMMON_REQUEST = {
  thread_id: "demo-a1b2c3d4e5f6",
  user_id: "USER-001",
  message: "ORDER-003 的耳机有质量问题，我想退款",
};

const MODES = {
  request: {
    title: "一次请求主链",
    description:
      "从浏览器 sendMessage() 开始，经 FastAPI 与 LangGraph，到数据库终态重新读取并返回页面。播放路径使用高金额退款作为教学示例。",
    canvas: { width: 940, height: 900 },
    steps: [
      "send-message",
      "request",
      "api-message",
      "extract-intent",
      "route-info",
      "load-order",
      "evaluate-policy",
      "execute-action",
      "read-final",
      "compose-response",
      "api-response",
      "render-response",
    ],
    nodes: [
      {
        id: "send-message",
        x: 40,
        y: 32,
        stage: "browser",
        function: "sendMessage()",
        title: "收集用户消息",
        subtitle: "frontend/app.js",
        path: PATHS.frontend,
        summary: "表单提交后读取文本，把用户消息加入页面状态，并准备调用会话消息接口。",
        calls: ["request()", "renderConversation()", "setBusy()", "renderResponse()"],
        input: { event: "submit", message: COMMON_REQUEST.message, thread_id: COMMON_REQUEST.thread_id },
        output: { method: "POST", path: "/conversations/{thread_id}/messages", body: { message: COMMON_REQUEST.message } },
        failure: "消息为空或没有 thread_id 时直接返回；网络错误交给 setError()。",
        packetLabel: "浏览器请求准备",
        packet: { thread_id: COMMON_REQUEST.thread_id, body: { message: COMMON_REQUEST.message } },
      },
      {
        id: "request",
        x: 346,
        y: 32,
        stage: "browser",
        function: "request()",
        title: "发出 HTTP JSON 请求",
        subtitle: "frontend/app.js",
        path: PATHS.frontend,
        summary: "统一补上 JSON 请求头，通过 fetch() 调用 8009 端口，并把成功响应解析成对象。",
        calls: ["fetch()", "Response.text()", "Response.json()"],
        input: { path: "/conversations/demo-…/messages", method: "POST", body: "JSON string" },
        output: { response: "ConversationResponse JSON" },
        failure: "HTTP 非 2xx 时读取错误正文并抛出 Error；这里不做重试。",
        packetLabel: "HTTP 边界",
        packet: { url: "http://127.0.0.1:8009/api/v1/conversations/demo-…/messages", content_type: "application/json" },
      },
      {
        id: "api-message",
        x: 652,
        y: 32,
        stage: "api",
        function: "send_conversation_message()",
        title: "FastAPI 消息入口",
        subtitle: "api/routes.py",
        path: PATHS.routes,
        summary: "校验会话，取得已编译图，组装 AgentState 初始字段，并用 thread_id 调用图。",
        calls: ["_conversation_user()", "_agent_graph()", "await graph.ainvoke()", "_thread_config()", "_conversation_response()"],
        input: { thread_id: COMMON_REQUEST.thread_id, payload: { message: COMMON_REQUEST.message }, request: "FastAPI Request" },
        output: { response_model: "ConversationResponse" },
        failure: "会话不存在时返回 404；模型配置错误或图执行错误会向 HTTP 层传播。",
        packetLabel: "AgentState 初始输入",
        packet: { thread_id: COMMON_REQUEST.thread_id, user_id: COMMON_REQUEST.user_id, user_message: COMMON_REQUEST.message, reference_date: "2026-08-01" },
      },
      {
        id: "extract-intent",
        x: 40,
        y: 202,
        stage: "agent",
        function: "ServiceGraphNodes.extract_intent()",
        title: "抽取结构化意图",
        subtitle: "agent/graph.py",
        path: PATHS.graph,
        summary: "调用 IntentExtractor，把自然语言变成订单号、动作和问题类型；缺失字段可继承同一 thread 的旧状态。",
        calls: ["IntentExtractor.extract()", "StructuredModel.complete_json()", "ParsedIntent.model_validate()"],
        input: { user_message: COMMON_REQUEST.message, previous_state: "optional thread checkpoint" },
        output: { order_id: "ORDER-003", requested_action: "refund", issue_type: "quality", missing_fields: [] },
        failure: "模型 JSON 无法通过 Pydantic 校验时写入 intent_parse_error，不进入数据库读写。",
        packetLabel: "结构化意图",
        packet: { order_id: "ORDER-003", requested_action: "refund", issue_type: "quality", issue_summary: "耳机质量问题", missing_fields: [] },
      },
      {
        id: "route-info",
        x: 346,
        y: 202,
        stage: "agent",
        function: "ServiceGraphNodes.route_missing_info()",
        title: "标记信息完整性",
        subtitle: "agent/graph.py",
        path: PATHS.graph,
        summary: "如果解析失败或字段缺失，就写入 POL-INFO-01；随后条件边决定去查订单还是直接回复。",
        calls: ["_route_after_intent()"],
        input: { error: null, missing_fields: [] },
        output: { next: "load_order" },
        failure: "缺 order_id 或 requested_action 时转 compose_response，不调用任何改状态工具。",
        packetLabel: "条件边决定",
        packet: { has_error: false, has_missing_fields: false, next: "load_order" },
      },
      {
        id: "load-order",
        x: 652,
        y: 202,
        stage: "agent",
        function: "ServiceGraphNodes.load_order()",
        title: "读取订单快照",
        subtitle: "agent/graph.py",
        path: PATHS.graph,
        summary: "通过受限 ServiceTools 读取订单，把领域对象转成可放入 AgentState 的字典快照。",
        calls: ["ServiceTools.get_order()", "CaseService.get_order()", "OrderRepository.get()", "_order_snapshot()"],
        input: { order_id: "ORDER-003" },
        output: { order_snapshot: { status: "delivered", total_amount: "899.00" }, tool_event: "get_order" },
        failure: "订单不存在时写入 order_not_found，条件边直接转回复节点。",
        packetLabel: "订单快照",
        packet: { id: "ORDER-003", user_id: "USER-001", status: "delivered", total_amount: "899.00", delivered_at: "2026-07-29T00:00:00+00:00" },
      },
      {
        id: "evaluate-policy",
        x: 40,
        y: 372,
        stage: "domain",
        function: "ServiceGraphNodes.evaluate_policy()",
        title: "调用确定性政策",
        subtitle: "agent/graph.py",
        path: PATHS.graph,
        summary: "把订单快照还原成领域对象，再交给纯 Python evaluate_policy() 判断政策与决策。",
        calls: ["_order_from_snapshot()", "evaluate_policy()"],
        input: { order_status: "delivered", total_amount: "899.00", requested_action: "refund", reference_date: "2026-08-01" },
        output: { policy_id: "POL-APPROVAL-01", decision: "approval_required" },
        failure: "它本身不调用模型、不写数据库；不满足直办条件时返回查询、审批或工单等确定性分支。",
        packetLabel: "政策结论",
        packet: { policy_id: "POL-APPROVAL-01", decision: "approval_required", reason: "超过 500 元的退款需要人工审批" },
      },
      {
        id: "execute-action",
        x: 346,
        y: 372,
        stage: "agent",
        function: "ServiceGraphNodes.execute_action()",
        title: "把决策映射为工具",
        subtitle: "agent/graph.py",
        path: PATHS.graph,
        summary: "根据 decision 只调用允许的业务工具，并把结果记录为 tool_events、case_id 或 approval_id。",
        calls: ["_execute_decision()", "ServiceTools.create_approval()", "_tool_event()"],
        input: { decision: "approval_required", order_id: "ORDER-003" },
        output: { approval_id: "APPROVAL-…", case_id: "APPROVAL-…", tool_event: "create_approval" },
        failure: "工具返回 ok=false 时把业务错误码写入 state.error；EXPLAIN_ONLY 不产生副作用。",
        packetLabel: "工具执行结果",
        packet: { tool: "create_approval", ok: true, code: "approval_pending", approval_id: "APPROVAL-7F…" },
      },
      {
        id: "read-final",
        x: 652,
        y: 372,
        stage: "data",
        function: "ServiceGraphNodes.read_final_state()",
        title: "重新读取数据库事实",
        subtitle: "agent/graph.py",
        path: PATHS.graph,
        summary: "业务动作后重新打开 Session，读取订单、案例和审批，避免仅凭工具口头结果判定完成。",
        calls: ["ServiceTools.get_order()", "ServiceTools.get_case_status()", "_route_after_final_state()"],
        input: { order_id: "ORDER-003", case_id: "APPROVAL-…", approval_id: "APPROVAL-…" },
        output: { final_business_state: { order_status: "delivered", approval_status: "pending" } },
        failure: "高金额审批仍为 pending 时，条件边转 wait_for_approval()；其余情况转回复。",
        packetLabel: "数据库最终状态",
        packet: { order_status: "delivered", approval_status: "pending" },
      },
      {
        id: "compose-response",
        x: 195,
        y: 542,
        stage: "agent",
        function: "ServiceGraphNodes.compose_response()",
        title: "生成简短用户回复",
        subtitle: "agent/graph.py",
        path: PATHS.graph,
        summary: "按照错误、缺失信息和最终业务状态，用确定性模板生成 assistant_message。",
        calls: ["_missing_field_labels()", "_success_message()"],
        input: { decision: "approval_required", final_business_state: { approval_status: "approved", order_status: "refunded" } },
        output: { assistant_message: "订单 ORDER-003 已审批通过，退款已完成。" },
        failure: "错误分支会生成可读错误；它不会再调用模型，也不会改写数据库。",
        packetLabel: "用户可读结果",
        packet: { assistant_message: "订单 ORDER-003 已审批通过，退款已完成。" },
      },
      {
        id: "api-response",
        x: 500,
        y: 542,
        stage: "api",
        function: "_conversation_response()",
        title: "映射公开响应模型",
        subtitle: "api/routes.py",
        path: PATHS.routes,
        summary: "把内部 AgentState 转成 ConversationResponse，只暴露回复、政策、工具轨迹和最终状态。",
        calls: ["ToolEventResponse.model_validate()", "TokenUsageResponse.model_validate()", "ConversationResponse()"],
        input: { state: "AgentState Mapping", thread_id: COMMON_REQUEST.thread_id },
        output: { response: "ConversationResponse" },
        failure: "字段形状不符合 Pydantic 模型时响应构建失败；pending 审批会补一条默认提示。",
        packetLabel: "HTTP 响应 JSON",
        packet: { thread_id: COMMON_REQUEST.thread_id, policy_id: "POL-APPROVAL-01", decision: "approval_required", tool_events: ["get_order", "create_approval", "decide_approval"], final_business_state: { order_status: "refunded", refund_status: "completed", approval_status: "approved" } },
      },
      {
        id: "render-response",
        x: 346,
        y: 712,
        stage: "browser",
        function: "renderResponse()",
        title: "更新页面业务状态",
        subtitle: "frontend/app.js",
        path: PATHS.frontend,
        summary: "把回复加入对话，并更新政策、订单、案例、审批状态和工具时间线。",
        calls: ["renderConversation()", "renderTimeline()", "formatValue()"],
        input: { response: "ConversationResponse JSON" },
        output: { ui: "对话 + 业务状态 + 工具轨迹" },
        failure: "缺失可选字段时显示空值；pending 审批才显示同意和拒绝按钮。",
        packetLabel: "页面展示状态",
        packet: { decision: "approval_required", policy: "POL-APPROVAL-01", order_status: "refunded", approval_status: "approved" },
      },
    ],
    edges: [
      { from: "send-message", to: "request", label: "调用" },
      { from: "request", to: "api-message", label: "POST JSON", kind: "http" },
      { from: "api-message", to: "extract-intent", label: "await graph.ainvoke" },
      { from: "extract-intent", to: "route-info", label: "写入意图字段", kind: "data" },
      { from: "route-info", to: "load-order", label: "信息完整" },
      { from: "route-info", to: "compose-response", label: "缺信息", kind: "data" },
      { from: "load-order", to: "evaluate-policy", label: "订单存在" },
      { from: "load-order", to: "compose-response", label: "未找到", kind: "data" },
      { from: "evaluate-policy", to: "execute-action", label: "policy + decision", kind: "data" },
      { from: "execute-action", to: "read-final", label: "动作完成" },
      { from: "read-final", to: "compose-response", label: "终态可回复" },
      { from: "compose-response", to: "api-response", label: "AgentState", kind: "return" },
      { from: "api-response", to: "render-response", label: "HTTP JSON", kind: "return" },
    ],
  },

  business: {
    title: "确定性业务写入放大图",
    description:
      "放大“政策决定之后，数据库为什么真的改变”。播放路径追踪七天内小额退款；旁支节点展示取消、审批和工单的真实入口。",
    canvas: { width: 940, height: 1080 },
    steps: [
      "policy-node",
      "domain-policy",
      "execute-node",
      "decision-router",
      "tool-refund",
      "case-refund",
      "repo-refund",
      "repo-status",
      "commit",
      "read-final-business",
    ],
    nodes: [
      {
        id: "policy-node",
        x: 40,
        y: 32,
        stage: "agent",
        function: "ServiceGraphNodes.evaluate_policy()",
        title: "准备政策输入",
        subtitle: "agent/graph.py",
        path: PATHS.graph,
        summary: "从 AgentState 取订单快照、动作、问题类型和参考日期，再调用领域政策。",
        calls: ["_order_from_snapshot()", "evaluate_policy()"],
        input: { order_id: "ORDER-007", status: "delivered", amount: "299.00", action: "refund" },
        output: { policy_id: "POL-REFUND-01", decision: "direct_refund" },
        failure: "订单快照缺失时政策会返回补信息；这里不写数据库。",
        packetLabel: "政策输入",
        packet: { status: "delivered", days_since_delivery: 3, total_amount: "299.00", requested_action: "refund" },
      },
      {
        id: "domain-policy",
        x: 346,
        y: 32,
        stage: "domain",
        function: "evaluate_policy()",
        title: "按固定顺序判断规则",
        subtitle: "domain/policies.py",
        path: PATHS.policies,
        summary: "纯 Python 条件判断负责订单状态、七天退款、三十天换货和 500 元审批阈值。",
        calls: ["_days_since_delivery()", "PolicyDecision()"],
        input: { order: "Order", requested_action: "RequestedAction.REFUND", issue_type: "IssueType.CHANGED_MIND", reference_date: "date" },
        output: { policy_id: "POL-REFUND-01", decision: "Decision.DIRECT_REFUND", reason: "已送达订单仍在七天退款期限内" },
        failure: "不符合直办条件时返回支持工单；相同输入必定得到相同结果。",
        packetLabel: "确定性结论",
        packet: { matched: "delivered && 0 <= days <= 7 && amount <= 500", decision: "direct_refund" },
      },
      {
        id: "execute-node",
        x: 652,
        y: 32,
        stage: "agent",
        function: "ServiceGraphNodes.execute_action()",
        title: "创建受限工具门面",
        subtitle: "agent/graph.py",
        path: PATHS.graph,
        summary: "只根据已经确定的 decision 调用 _execute_decision()，不让模型直接选 SQL。",
        calls: ["ServiceTools()", "_execute_decision()", "_tool_event()"],
        input: { decision: "direct_refund", order_id: "ORDER-007" },
        output: { tool_event: { tool: "request_refund", ok: true } },
        failure: "EXPLAIN_ONLY 不执行工具；工具失败时记录业务错误码。",
        packetLabel: "动作路由输入",
        packet: { decision: "direct_refund", allowed_boundary: "ServiceTools" },
      },
      {
        id: "decision-router",
        x: 346,
        y: 202,
        stage: "agent",
        function: "_execute_decision()",
        title: "决策映射为一个工具",
        subtitle: "agent/graph.py",
        path: PATHS.graph,
        summary: "CANCEL、DIRECT_REFUND、APPROVAL_REQUIRED 和工单决策分别映射到固定工具方法。",
        calls: ["ServiceTools.cancel_order()", "ServiceTools.request_refund()", "ServiceTools.create_approval()", "ServiceTools.create_ticket()"],
        input: { decision: "Decision.DIRECT_REFUND", order_id: "ORDER-007" },
        output: { result: "CaseResult", tool_name: "request_refund" },
        failure: "未知或 EXPLAIN_ONLY 决策返回 (None, '')，不会产生数据库副作用。",
        packetLabel: "工具选择",
        packet: { decision: "direct_refund", selected_tool: "request_refund" },
      },
      {
        id: "tool-cancel",
        x: 40,
        y: 372,
        stage: "data",
        function: "ServiceTools.cancel_order()",
        title: "取消工具旁支",
        subtitle: "agent/tools.py",
        path: PATHS.tools,
        summary: "受限工具把取消动作转交给 CaseService，不暴露 Session 或 SQL 给 Agent。",
        calls: ["CaseService.cancel_order()"],
        input: { order_id: "ORDER-001" },
        output: { case_result: "order_cancelled" },
        failure: "订单不存在或状态不是 paid 时返回结构化失败。",
        packetLabel: "取消旁支",
        packet: { tool: "cancel_order", possible_final: "cancelled" },
      },
      {
        id: "tool-refund",
        x: 346,
        y: 372,
        stage: "data",
        function: "ServiceTools.request_refund()",
        title: "退款工具门面",
        subtitle: "agent/tools.py",
        path: PATHS.tools,
        summary: "Agent 可调用的退款入口，只把 order_id 交给 CaseService。",
        calls: ["CaseService.request_refund()"],
        input: { order_id: "ORDER-007" },
        output: { case_result: "CaseResult" },
        failure: "领域服务会再次检查订单存在性、状态和金额边界。",
        packetLabel: "受限工具调用",
        packet: { tool: "request_refund", direct_database_access: false },
      },
      {
        id: "tool-approval",
        x: 652,
        y: 372,
        stage: "data",
        function: "ServiceTools.create_approval()",
        title: "高金额审批旁支",
        subtitle: "agent/tools.py",
        path: PATHS.tools,
        summary: "超过 500 元时创建 pending 审批，而不是直接完成退款。",
        calls: ["CaseService.create_approval()"],
        input: { order_id: "ORDER-003", action: "refund" },
        output: { approval_status: "pending" },
        failure: "订单不存在时返回 order_not_found。",
        packetLabel: "审批旁支",
        packet: { tool: "create_approval", order_status: "delivered", approval_status: "pending" },
      },
      {
        id: "tool-ticket",
        x: 40,
        y: 542,
        stage: "data",
        function: "ServiceTools.create_ticket()",
        title: "换货 / 支持工单旁支",
        subtitle: "agent/tools.py",
        path: PATHS.tools,
        summary: "质量换货和无法直办请求都通过预定义工单类型进入 CaseService。",
        calls: ["CaseService.create_ticket()"],
        input: { order_id: "ORDER-008", kind: "exchange", summary: "耳机质量问题" },
        output: { ticket_status: "open", order_status: "ticket_open" },
        failure: "未知 kind 返回 action_not_supported。",
        packetLabel: "工单旁支",
        packet: { tool: "create_ticket", kind: "exchange" },
      },
      {
        id: "case-refund",
        x: 346,
        y: 542,
        stage: "data",
        function: "CaseService.request_refund()",
        title: "执行退款业务用例",
        subtitle: "application/case_service.py",
        path: PATHS.caseService,
        summary: "再次读取订单，检查 delivered 与金额，然后创建退款、更新订单并提交事务。",
        calls: ["await OrderRepository.get()", "await CaseRepository.create_refund()", "await OrderRepository.set_status()", "await AsyncSession.commit()"],
        input: { order_id: "ORDER-007" },
        output: { code: "refund_completed", refund_status: "completed", order_status: "refunded" },
        failure: "订单不存在或状态不是 delivered 时不写入；高金额会转 create_approval()。",
        packetLabel: "业务用例状态",
        packet: { before: { order_status: "delivered" }, after: { order_status: "refunded", refund_status: "completed" } },
      },
      {
        id: "repo-refund",
        x: 40,
        y: 712,
        stage: "data",
        function: "CaseRepository.create_refund()",
        title: "创建 RefundRow",
        subtitle: "infrastructure/case_repository.py",
        path: PATHS.cases,
        summary: "创建 refunds 表映射对象，add + flush 后转成领域 Refund 返回。",
        calls: ["AsyncSession.add()", "await AsyncSession.flush()", "_refund_to_domain()"],
        input: { case_id: "REFUND-…", order_id: "ORDER-007", amount: "299.00", status: "completed" },
        output: { refund: "Refund domain object" },
        failure: "数据库约束或 Session 错误会向 application service 传播。",
        packetLabel: "退款表写入",
        packet: { table: "refunds", row: { order_id: "ORDER-007", amount: "299.00", status: "completed" }, committed: false },
      },
      {
        id: "repo-status",
        x: 346,
        y: 712,
        stage: "data",
        function: "OrderRepository.set_status()",
        title: "更新订单状态",
        subtitle: "infrastructure/repositories.py",
        path: PATHS.orders,
        summary: "通过主键读取 OrderRow，把 status 改成 refunded，flush 后重新转成领域对象。",
        calls: ["await AsyncSession.get()", "await AsyncSession.flush()", "await OrderRepository.get()"],
        input: { order_id: "ORDER-007", status: "OrderStatus.REFUNDED" },
        output: { order: "Order(status='refunded')" },
        failure: "找不到订单时抛 LookupError('order_not_found')。",
        packetLabel: "订单表变更",
        packet: { table: "orders", key: "ORDER-007", change: { status: ["delivered", "refunded"] }, committed: false },
      },
      {
        id: "commit",
        x: 652,
        y: 712,
        stage: "data",
        function: "await AsyncSession.commit()",
        title: "提交同一业务事务",
        subtitle: "case_service.py 中的 SQLAlchemy 调用点",
        path: PATHS.caseService,
        summary: "退款记录和订单状态在同一个 Session 中提交，提交完成后才成为数据库事实。",
        calls: ["SQLAlchemy transaction commit"],
        input: { pending_changes: ["refunds INSERT", "orders UPDATE"] },
        output: { committed: true },
        failure: "提交失败会抛数据库异常；本项目没有为理论失败增加重试。",
        packetLabel: "事务边界",
        packet: { transaction: "commit", writes: 2, final: true },
      },
      {
        id: "read-final-business",
        x: 346,
        y: 892,
        stage: "agent",
        function: "ServiceGraphNodes.read_final_state()",
        title: "用新 Session 核验终态",
        subtitle: "agent/graph.py",
        path: PATHS.graph,
        summary: "执行完工具后再读取订单和退款，构造 final_business_state 作为最终结果依据。",
        calls: ["ServiceTools.get_order()", "ServiceTools.get_case_status()"],
        input: { order_id: "ORDER-007", case_id: "REFUND-…" },
        output: { order_status: "refunded", refund_status: "completed" },
        failure: "只有真实读回的状态进入响应；工具名称本身不代表业务成功。",
        packetLabel: "核验后的业务事实",
        packet: { final_business_state: { order_status: "refunded", refund_status: "completed" } },
      },
    ],
    edges: [
      { from: "policy-node", to: "domain-policy", label: "调用" },
      { from: "domain-policy", to: "execute-node", label: "PolicyDecision", kind: "data" },
      { from: "execute-node", to: "decision-router", label: "调用" },
      { from: "decision-router", to: "tool-cancel", label: "cancel" },
      { from: "decision-router", to: "tool-refund", label: "direct_refund" },
      { from: "decision-router", to: "tool-approval", label: "approval_required" },
      { from: "decision-router", to: "tool-ticket", label: "ticket" },
      { from: "tool-refund", to: "case-refund", label: "委托" },
      { from: "case-refund", to: "repo-refund", label: "创建退款" },
      { from: "repo-refund", to: "repo-status", label: "随后更新订单" },
      { from: "repo-status", to: "commit", label: "提交" },
      { from: "commit", to: "read-final-business", label: "重新读取", kind: "return" },
    ],
  },

  approval: {
    title: "高金额审批中断 / 恢复",
    description:
      "同一张图按时间顺序展示第一次请求如何暂停、用户如何提交审批，以及同一个 thread 如何从 wait_for_approval() 恢复并重新读取终态。",
    canvas: { width: 940, height: 1260 },
    steps: [
      "execute-approval",
      "create-approval",
      "pending-final",
      "pending-route",
      "wait-initial",
      "interrupt",
      "frontend-approval",
      "api-approval",
      "graph-resume",
      "wait-resume",
      "tool-decide",
      "case-decide",
      "approval-commit",
      "resume-final",
      "approval-compose",
    ],
    nodes: [
      {
        id: "execute-approval",
        x: 40,
        y: 32,
        stage: "agent",
        function: "ServiceGraphNodes.execute_action()",
        title: "执行 approval_required",
        subtitle: "agent/graph.py",
        path: PATHS.graph,
        summary: "高金额退款决策被映射为 create_approval，而不是 request_refund。",
        calls: ["_execute_decision()", "ServiceTools.create_approval()"],
        input: { decision: "approval_required", order_id: "ORDER-003" },
        output: { approval_id: "APPROVAL-…", case_id: "APPROVAL-…" },
        failure: "创建失败时写入 state.error，不进入等待审批。",
        packetLabel: "高金额决策",
        packet: { amount: "899.00", threshold: "500.00", selected_tool: "create_approval" },
      },
      {
        id: "create-approval",
        x: 346,
        y: 32,
        stage: "data",
        function: "CaseService.create_approval()",
        title: "写入 pending 审批",
        subtitle: "application/case_service.py",
        path: PATHS.caseService,
        summary: "创建审批记录并立即 commit；订单仍保持 delivered，退款尚未创建。",
        calls: ["await OrderRepository.get()", "await CaseRepository.create_approval()", "await AsyncSession.commit()"],
        input: { order_id: "ORDER-003", action: "RequestedAction.REFUND" },
        output: { code: "approval_pending", approval_status: "pending" },
        failure: "订单不存在时返回 order_not_found。",
        packetLabel: "第一次数据库写入",
        packet: { approvals: { status: "pending" }, orders: { status: "delivered" }, refunds: null },
      },
      {
        id: "pending-final",
        x: 652,
        y: 32,
        stage: "agent",
        function: "ServiceGraphNodes.read_final_state()",
        title: "读回 pending 状态",
        subtitle: "agent/graph.py",
        path: PATHS.graph,
        summary: "读取订单和审批，确认数据库确实处于 delivered + pending。",
        calls: ["ServiceTools.get_order()", "ServiceTools.get_case_status()"],
        input: { order_id: "ORDER-003", approval_id: "APPROVAL-…" },
        output: { order_status: "delivered", approval_status: "pending" },
        failure: "如果审批不是 pending，流程不会进入中断。",
        packetLabel: "暂停前终态",
        packet: { final_business_state: { order_status: "delivered", approval_status: "pending" } },
      },
      {
        id: "pending-route",
        x: 346,
        y: 202,
        stage: "agent",
        function: "_route_after_final_state()",
        title: "判断是否需要等待人",
        subtitle: "agent/graph.py",
        path: PATHS.graph,
        summary: "只有 decision=approval_required 且 approval_status=pending 时返回 wait_for_approval。",
        calls: ["StateGraph conditional edge"],
        input: { decision: "approval_required", approval_status: "pending" },
        output: { next: "wait_for_approval" },
        failure: "其他状态直接进入 compose_response，不会暂停。",
        packetLabel: "条件边",
        packet: { condition: "approval_required && pending", next: "wait_for_approval" },
      },
      {
        id: "wait-initial",
        x: 40,
        y: 372,
        stage: "agent",
        function: "ServiceGraphNodes.wait_for_approval()",
        title: "进入审批节点",
        subtitle: "agent/graph.py · 第一次执行",
        path: PATHS.graph,
        summary: "取得 approval_id，调用 interrupt() 把必要信息交给调用方，并在此保存 checkpoint。",
        calls: ["interrupt()"],
        input: { approval_id: "APPROVAL-…", order_id: "ORDER-003" },
        output: { interrupt_payload: { action: "approve_or_reject" } },
        failure: "没有 approval_id 时返回 case_not_found。",
        packetLabel: "中断载荷",
        packet: { approval_id: "APPROVAL-…", order_id: "ORDER-003", action: "approve_or_reject" },
      },
      {
        id: "interrupt",
        x: 346,
        y: 372,
        stage: "agent",
        function: "interrupt()",
        title: "暂停并保留恢复位置",
        subtitle: "graph.py 中的 LangGraph 调用点",
        path: PATHS.graph,
        summary: "LangGraph 停在 wait_for_approval()，InMemorySaver 用 thread_id 保存当前图状态。",
        calls: ["InMemorySaver checkpoint"],
        input: { payload: "approval_id + order_id + action", config: { thread_id: COMMON_REQUEST.thread_id } },
        output: { graph_status: "interrupted", approval_status: "pending" },
        failure: "API 进程重启会丢失内存 checkpoint，V1 不承诺跨进程恢复。",
        packetLabel: "暂停状态",
        packet: { thread_id: COMMON_REQUEST.thread_id, checkpoint: "in-memory", waiting_for: "approved: boolean" },
      },
      {
        id: "frontend-approval",
        x: 652,
        y: 372,
        stage: "browser",
        function: "decideApproval()",
        title: "用户点击同意或拒绝",
        subtitle: "frontend/app.js",
        path: PATHS.frontend,
        summary: "页面携带同一个 thread_id、approval_id 和 approved 布尔值调用审批接口。",
        calls: ["request()", "renderResponse()"],
        input: { approved: true, thread_id: COMMON_REQUEST.thread_id, approval_id: "APPROVAL-…" },
        output: { method: "POST", body: { approved: true } },
        failure: "缺 thread_id 或 approval_id 时不发送请求。",
        packetLabel: "人工决定",
        packet: { approved: true, route: "/conversations/{thread_id}/approvals/{approval_id}" },
      },
      {
        id: "api-approval",
        x: 652,
        y: 542,
        stage: "api",
        function: "decide_conversation_approval()",
        title: "校验审批与会话",
        subtitle: "api/routes.py",
        path: PATHS.routes,
        summary: "确认 thread 存在且 checkpoint 中的 approval_id 匹配，再用 Command(resume=...) 恢复。",
        calls: ["_conversation_user()", "await graph.aget_state()", "Command()", "await graph.ainvoke()", "_conversation_response()"],
        input: { thread_id: COMMON_REQUEST.thread_id, approval_id: "APPROVAL-…", approved: true },
        output: { resumed_state: "AgentState" },
        failure: "会话或审批不匹配时返回 404，不恢复错误 thread。",
        packetLabel: "恢复命令准备",
        packet: { command: { resume: { approved: true } }, configurable: { thread_id: COMMON_REQUEST.thread_id } },
      },
      {
        id: "graph-resume",
        x: 346,
        y: 542,
        stage: "agent",
        function: "CompiledStateGraph.ainvoke()",
        title: "用同一 thread 恢复图",
        subtitle: "routes.py 中的 LangGraph 调用点",
        path: PATHS.routes,
        summary: "Command(resume) 与相同 thread_id 找回暂停位置，把 approved 送回 interrupt() 的返回点。",
        calls: ["Command(resume=...)", "_thread_config()", "ServiceGraphNodes.wait_for_approval()"],
        input: { command: "Command(resume={'approved': true})", thread_id: COMMON_REQUEST.thread_id },
        output: { continuation: "wait_for_approval() after interrupt" },
        failure: "checkpoint 不存在或进程已重启时无法按 V1 设计恢复。",
        packetLabel: "恢复定位",
        packet: { checkpoint_found: true, resume_node: "wait_for_approval", approved: true },
      },
      {
        id: "wait-resume",
        x: 40,
        y: 542,
        stage: "agent",
        function: "ServiceGraphNodes.wait_for_approval()",
        title: "从 interrupt 后继续",
        subtitle: "agent/graph.py · 恢复后",
        path: PATHS.graph,
        summary: "interrupt() 现在返回 approved，节点通过受限工具真正执行审批决定。",
        calls: ["ServiceTools.decide_approval()", "_tool_event()"],
        input: { answer: { approved: true }, approval_id: "APPROVAL-…" },
        output: { case_id: "REFUND-…", tool_event: "decide_approval" },
        failure: "工具失败时写入错误码，并仍由后续节点重新读取可见状态。",
        packetLabel: "恢复后的节点输入",
        packet: { approved: true, approval_id: "APPROVAL-…" },
      },
      {
        id: "tool-decide",
        x: 40,
        y: 712,
        stage: "data",
        function: "ServiceTools.decide_approval()",
        title: "审批工具门面",
        subtitle: "agent/tools.py",
        path: PATHS.tools,
        summary: "继续保持 Agent 与 Session 隔离，只把审批编号和布尔决定交给 CaseService。",
        calls: ["CaseService.decide_approval()"],
        input: { approval_id: "APPROVAL-…", approved: true },
        output: { case_result: "CaseResult" },
        failure: "审批不存在时返回 case_not_found。",
        packetLabel: "受限审批工具",
        packet: { tool: "decide_approval", approved: true, direct_sql: false },
      },
      {
        id: "case-decide",
        x: 346,
        y: 712,
        stage: "data",
        function: "CaseService.decide_approval()",
        title: "更新审批并执行退款",
        subtitle: "application/case_service.py",
        path: PATHS.caseService,
        summary: "同意时把审批设为 approved、创建 completed 退款并把订单改为 refunded；拒绝时只更新审批。",
        calls: ["await CaseRepository.get_approval()", "await CaseRepository.set_approval_status()", "await CaseRepository.create_refund()", "await OrderRepository.set_status()", "await AsyncSession.commit()"],
        input: { approval_id: "APPROVAL-…", approved: true },
        output: { code: "approval_approved", order_status: "refunded", refund_status: "completed" },
        failure: "审批或订单不存在时返回结构化失败；拒绝不会创建退款。",
        packetLabel: "审批业务分支",
        packet: { approved: { approval: "approved", refund: "completed", order: "refunded" }, rejected: { approval: "rejected", refund: null, order: "delivered" } },
      },
      {
        id: "approval-commit",
        x: 652,
        y: 712,
        stage: "data",
        function: "await AsyncSession.commit()",
        title: "提交审批结果事务",
        subtitle: "case_service.py 中的 SQLAlchemy 调用点",
        path: PATHS.caseService,
        summary: "审批、退款和订单状态在同一个 Session 中提交，形成可重新读取的数据库事实。",
        calls: ["SQLAlchemy transaction commit"],
        input: { updates: ["approvals.status", "refunds INSERT", "orders.status"] },
        output: { committed: true },
        failure: "提交异常会向上返回；页面不会伪造成功终态。",
        packetLabel: "恢复后的事务",
        packet: { approvals: "approved", refunds: "completed", orders: "refunded", committed: true },
      },
      {
        id: "resume-final",
        x: 346,
        y: 892,
        stage: "agent",
        function: "ServiceGraphNodes.read_final_state()",
        title: "恢复后再次核验终态",
        subtitle: "agent/graph.py",
        path: PATHS.graph,
        summary: "wait_for_approval() 完成后沿回边再次进入本节点，读出 approved、completed 和 refunded。",
        calls: ["ServiceTools.get_order()", "ServiceTools.get_case_status()", "_route_after_final_state()"],
        input: { approval_id: "APPROVAL-…", case_id: "REFUND-…", order_id: "ORDER-003" },
        output: { order_status: "refunded", refund_status: "completed", approval_status: "approved" },
        failure: "只有 approval_status 仍为 pending 才再次等待；approved/rejected 都去回复。",
        packetLabel: "恢复后的数据库事实",
        packet: { final_business_state: { order_status: "refunded", refund_status: "completed", approval_status: "approved" } },
      },
      {
        id: "approval-compose",
        x: 346,
        y: 1072,
        stage: "agent",
        function: "ServiceGraphNodes.compose_response()",
        title: "生成审批完成回复",
        subtitle: "agent/graph.py",
        path: PATHS.graph,
        summary: "根据最终 approval_status 分别生成审批通过或拒绝的确定性回复。",
        calls: ["_success_message()"],
        input: { decision: "approval_required", final_business_state: { approval_status: "approved", order_status: "refunded" } },
        output: { assistant_message: "订单 ORDER-003 已审批通过，退款已完成。" },
        failure: "如果仍是 pending，会返回审批编号而不是声称退款完成。",
        packetLabel: "最终回复",
        packet: { assistant_message: "订单 ORDER-003 已审批通过，退款已完成。", verified_by_database: true },
      },
    ],
    edges: [
      { from: "execute-approval", to: "create-approval", label: "create_approval" },
      { from: "create-approval", to: "pending-final", label: "commit 后读回", kind: "return" },
      { from: "pending-final", to: "pending-route", label: "pending", kind: "data" },
      { from: "pending-route", to: "wait-initial", label: "需要人工" },
      { from: "wait-initial", to: "interrupt", label: "调用" },
      { from: "interrupt", to: "frontend-approval", label: "页面等待用户", kind: "loop" },
      { from: "frontend-approval", to: "api-approval", label: "POST approved", kind: "http" },
      { from: "api-approval", to: "graph-resume", label: "Command(resume)" },
      { from: "graph-resume", to: "wait-resume", label: "回到中断点", kind: "loop" },
      { from: "wait-resume", to: "tool-decide", label: "approved" },
      { from: "tool-decide", to: "case-decide", label: "委托" },
      { from: "case-decide", to: "approval-commit", label: "提交" },
      { from: "approval-commit", to: "resume-final", label: "回到 read_final_state", kind: "loop" },
      { from: "resume-final", to: "approval-compose", label: "终态已确定" },
    ],
  },
};

const state = {
  mode: "request",
  stepIndex: 0,
  selectedNodeId: "send-message",
  timer: null,
  activeUnit: 1,
};

const elements = {
  roadmap: document.querySelector("#roadmap"),
  canvas: document.querySelector("#graph-canvas"),
  edgeLayer: document.querySelector("#edge-layer"),
  nodeLayer: document.querySelector("#node-layer"),
  modeTitle: document.querySelector("#mode-title"),
  modeDescription: document.querySelector("#mode-description"),
  stepCounter: document.querySelector("#step-counter"),
  stepDescription: document.querySelector("#step-description"),
  progressTrack: document.querySelector(".progress-track"),
  progressFill: document.querySelector("#progress-fill"),
  detailStage: document.querySelector("#detail-stage"),
  detailTitle: document.querySelector("#detail-title"),
  detailSummary: document.querySelector("#detail-summary"),
  detailPath: document.querySelector("#detail-path"),
  detailCalls: document.querySelector("#detail-calls"),
  detailInput: document.querySelector("#detail-input"),
  detailOutput: document.querySelector("#detail-output"),
  detailFailure: document.querySelector("#detail-failure"),
  currentFunction: document.querySelector("#current-function"),
  previousFunctions: document.querySelector("#previous-functions"),
  nextFunctions: document.querySelector("#next-functions"),
  packetTitle: document.querySelector("#packet-title"),
  packetView: document.querySelector("#packet-view"),
  playButton: document.querySelector('[data-action="play"]'),
};

function currentMode() {
  return MODES[state.mode];
}

function findNode(nodeId) {
  return currentMode().nodes.find((node) => node.id === nodeId);
}

function currentNode() {
  return findNode(state.selectedNodeId) || currentMode().nodes[0];
}

function formatJson(value) {
  return JSON.stringify(value, null, 2);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatFunctionName(value) {
  return escapeHtml(value).replaceAll("_", "_<wbr>");
}

function renderRoadmap() {
  elements.roadmap.replaceChildren();
  for (const day of ROADMAP) {
    const column = document.createElement("section");
    column.className = "day-column";
    const heading = document.createElement("div");
    heading.className = "day-heading";
    heading.innerHTML = `<strong>${escapeHtml(day.day)}</strong><span>${escapeHtml(day.goal)}</span>`;
    column.append(heading);

    const list = document.createElement("div");
    list.className = "unit-list";
    for (const unit of day.units) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "unit-button";
      button.dataset.unit = String(unit.number);
      button.classList.toggle("is-active", unit.number === state.activeUnit);
      button.innerHTML = `
        <span class="unit-number">${unit.number}</span>
        <span class="unit-copy">
          <strong>${escapeHtml(unit.title)}</strong>
          <small>${escapeHtml(unit.files)}</small>
        </span>
        <span class="unit-link">定位 →</span>
      `;
      button.addEventListener("click", () => focusLearningUnit(unit));
      list.append(button);
    }
    column.append(list);
    elements.roadmap.append(column);
  }
}

function focusLearningUnit(unit) {
  state.activeUnit = unit.number;
  setMode(unit.mode, unit.node);
  renderRoadmap();
  document.querySelector(".view-header").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderMode(initialNodeId) {
  const mode = currentMode();
  elements.modeTitle.textContent = mode.title;
  elements.modeDescription.textContent = mode.description;
  elements.canvas.style.width = `${mode.canvas.width}px`;
  elements.canvas.style.height = `${mode.canvas.height}px`;
  elements.nodeLayer.replaceChildren();
  elements.edgeLayer.replaceChildren();
  const target = initialNodeId && findNode(initialNodeId) ? initialNodeId : mode.steps[0];
  state.selectedNodeId = target;
  const targetStep = mode.steps.indexOf(target);
  state.stepIndex = targetStep >= 0 ? targetStep : 0;

  for (const node of mode.nodes) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `flow-node stage-${node.stage}`;
    button.dataset.nodeId = node.id;
    button.style.left = `${node.x}px`;
    button.style.top = `${node.y}px`;
    button.innerHTML = `
      <span class="node-stage">${escapeHtml(STAGE_LABELS[node.stage])}</span>
      <code class="node-function">${formatFunctionName(node.function)}</code>
      <span class="node-title">${escapeHtml(node.title)}</span>
      <span class="node-subtitle">${escapeHtml(node.subtitle)}</span>
    `;
    button.addEventListener("click", () => selectNode(node.id, true));
    elements.nodeLayer.append(button);
  }

  updateProgress();
  selectNode(target, false);
  window.requestAnimationFrame(drawEdges);
}

function drawEdges() {
  const mode = currentMode();
  const canvasRect = elements.canvas.getBoundingClientRect();
  elements.edgeLayer.setAttribute("width", String(canvasRect.width));
  elements.edgeLayer.setAttribute("height", String(canvasRect.height));
  elements.edgeLayer.setAttribute("viewBox", `0 0 ${canvasRect.width} ${canvasRect.height}`);
  elements.edgeLayer.replaceChildren();

  const marker = document.createElementNS("http://www.w3.org/2000/svg", "marker");
  marker.setAttribute("id", "flow-arrow");
  marker.setAttribute("markerWidth", "8");
  marker.setAttribute("markerHeight", "8");
  marker.setAttribute("refX", "7");
  marker.setAttribute("refY", "4");
  marker.setAttribute("orient", "auto");
  const arrowPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
  arrowPath.setAttribute("d", "M 0 0 L 8 4 L 0 8 z");
  arrowPath.setAttribute("fill", "#93a4af");
  marker.append(arrowPath);
  elements.edgeLayer.append(marker);

  for (const edge of mode.edges) {
    const source = elements.nodeLayer.querySelector(`[data-node-id="${edge.from}"]`);
    const target = elements.nodeLayer.querySelector(`[data-node-id="${edge.to}"]`);
    if (!source || !target) {
      continue;
    }
    const sourceRect = source.getBoundingClientRect();
    const targetRect = target.getBoundingClientRect();
    const sourceLeft = sourceRect.left - canvasRect.left;
    const sourceTop = sourceRect.top - canvasRect.top;
    const targetLeft = targetRect.left - canvasRect.left;
    const targetTop = targetRect.top - canvasRect.top;
    const sourceCenterX = sourceLeft + sourceRect.width / 2;
    const sourceCenterY = sourceTop + sourceRect.height / 2;
    const targetCenterX = targetLeft + targetRect.width / 2;
    const targetCenterY = targetTop + targetRect.height / 2;
    const mostlyVertical = Math.abs(targetCenterY - sourceCenterY) > 70;

    let startX;
    let startY;
    let endX;
    let endY;
    let pathData;
    let labelX;
    let labelY;
    if (mostlyVertical) {
      const goesDown = targetCenterY >= sourceCenterY;
      startX = sourceCenterX;
      startY = sourceTop + (goesDown ? sourceRect.height : 0);
      endX = targetCenterX;
      endY = targetTop + (goesDown ? 0 : targetRect.height);
      const middleY = (startY + endY) / 2;
      pathData = `M ${startX} ${startY} C ${startX} ${middleY}, ${endX} ${middleY}, ${endX} ${endY}`;
      labelX = (startX + endX) / 2;
      labelY = middleY - 7;
    } else {
      const goesRight = targetCenterX >= sourceCenterX;
      startX = sourceLeft + (goesRight ? sourceRect.width : 0);
      startY = sourceCenterY;
      endX = targetLeft + (goesRight ? 0 : targetRect.width);
      endY = targetCenterY;
      const middleX = (startX + endX) / 2;
      pathData = `M ${startX} ${startY} C ${middleX} ${startY}, ${middleX} ${endY}, ${endX} ${endY}`;
      labelX = middleX;
      labelY = (startY + endY) / 2 - 7;
    }

    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.classList.add("flow-edge", `kind-${edge.kind || "call"}`);
    const sourceStep = mode.steps.indexOf(edge.from);
    const targetStep = mode.steps.indexOf(edge.to);
    if (sourceStep >= 0 && targetStep >= 0 && sourceStep < state.stepIndex && targetStep <= state.stepIndex) {
      path.classList.add("is-done");
    }
    if (edge.from === state.selectedNodeId || edge.to === state.selectedNodeId) {
      path.classList.add("is-active");
    }
    path.setAttribute("d", pathData);
    path.setAttribute("marker-end", "url(#flow-arrow)");
    elements.edgeLayer.append(path);

    if (edge.label) {
      const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
      label.classList.add("edge-label");
      label.setAttribute("x", String(labelX));
      label.setAttribute("y", String(labelY));
      label.textContent = edge.label;
      elements.edgeLayer.append(label);
    }
  }
}

function neighborButtons(edges, direction) {
  const fragment = document.createDocumentFragment();
  if (edges.length === 0) {
    fragment.append(document.createTextNode("—"));
    return fragment;
  }
  for (const edge of edges) {
    const nodeId = direction === "incoming" ? edge.from : edge.to;
    const node = findNode(nodeId);
    if (!node) {
      continue;
    }
    const button = document.createElement("button");
    button.type = "button";
    button.className = "neighbor-button";
    button.textContent = node.function;
    button.setAttribute("aria-label", `定位到 ${node.function}`);
    button.addEventListener("click", () => selectNode(node.id, true));
    fragment.append(button);
  }
  return fragment;
}

function selectNode(nodeId, syncStep) {
  const node = findNode(nodeId);
  if (!node) {
    return;
  }
  state.selectedNodeId = nodeId;
  const nodeStep = currentMode().steps.indexOf(nodeId);
  if (syncStep && nodeStep >= 0) {
    state.stepIndex = nodeStep;
  }

  const incoming = currentMode().edges.filter((edge) => edge.to === node.id);
  const outgoing = currentMode().edges.filter((edge) => edge.from === node.id);
  elements.previousFunctions.replaceChildren(neighborButtons(incoming, "incoming"));
  elements.nextFunctions.replaceChildren(neighborButtons(outgoing, "outgoing"));

  for (const button of document.querySelectorAll(".flow-node")) {
    button.classList.toggle("is-selected", button.dataset.nodeId === node.id);
  }
  elements.detailStage.textContent = STAGE_LABELS[node.stage];
  elements.currentFunction.textContent = node.function;
  elements.detailTitle.textContent = node.title;
  elements.detailSummary.textContent = node.summary;
  elements.detailPath.textContent = node.path;
  elements.detailCalls.textContent = node.calls.length ? node.calls.join("\n") : "—";
  elements.detailInput.textContent = formatJson(node.input);
  elements.detailOutput.textContent = formatJson(node.output);
  elements.detailFailure.textContent = node.failure;
  elements.packetTitle.textContent = node.packetLabel;
  elements.packetView.textContent = formatJson(node.packet);
  updateProgress();
}

function updateProgress() {
  const mode = currentMode();
  const stepNode = findNode(mode.steps[state.stepIndex]) || mode.nodes[0];
  const denominator = Math.max(1, mode.steps.length - 1);
  const percent = (state.stepIndex / denominator) * 100;
  elements.stepCounter.textContent = `第 ${state.stepIndex + 1} / ${mode.steps.length} 步`;
  elements.stepDescription.textContent = `当前：${stepNode.function} — ${stepNode.title}`;
  elements.progressFill.style.width = `${percent}%`;
  elements.progressTrack.setAttribute("aria-valuemax", String(mode.steps.length));
  elements.progressTrack.setAttribute("aria-valuenow", String(state.stepIndex + 1));

  for (const button of document.querySelectorAll(".flow-node")) {
    const step = mode.steps.indexOf(button.dataset.nodeId);
    button.classList.toggle("is-active", step === state.stepIndex);
    button.classList.toggle("is-done", step >= 0 && step < state.stepIndex);
    button.classList.toggle("is-future", step > state.stepIndex);
  }
  window.requestAnimationFrame(drawEdges);
}

function goToStep(nextIndex) {
  const mode = currentMode();
  state.stepIndex = Math.max(0, Math.min(nextIndex, mode.steps.length - 1));
  state.selectedNodeId = mode.steps[state.stepIndex];
  selectNode(state.selectedNodeId, false);
  const selected = elements.nodeLayer.querySelector(`[data-node-id="${state.selectedNodeId}"]`);
  if (selected) {
    selected.scrollIntoView({ behavior: "smooth", block: "center", inline: "center" });
  }
  if (state.stepIndex === mode.steps.length - 1) {
    stopPlayback();
  }
}

function startPlayback() {
  if (state.timer) {
    return;
  }
  elements.playButton.textContent = "暂停";
  elements.playButton.setAttribute("aria-pressed", "true");
  state.timer = window.setInterval(() => {
    if (state.stepIndex >= currentMode().steps.length - 1) {
      stopPlayback();
      return;
    }
    goToStep(state.stepIndex + 1);
  }, 1700);
}

function stopPlayback() {
  if (state.timer) {
    window.clearInterval(state.timer);
  }
  state.timer = null;
  elements.playButton.textContent = "播放";
  elements.playButton.setAttribute("aria-pressed", "false");
}

function setMode(modeKey, initialNodeId) {
  if (!MODES[modeKey]) {
    return;
  }
  stopPlayback();
  state.mode = modeKey;
  for (const button of document.querySelectorAll(".mode-tab")) {
    const selected = button.dataset.mode === modeKey;
    button.classList.toggle("is-selected", selected);
    button.setAttribute("aria-selected", String(selected));
  }
  renderMode(initialNodeId);
}

for (const button of document.querySelectorAll(".mode-tab")) {
  button.addEventListener("click", () => setMode(button.dataset.mode));
}

document.querySelector('[data-action="reset"]').addEventListener("click", () => goToStep(0));
document.querySelector('[data-action="previous"]').addEventListener("click", () => goToStep(state.stepIndex - 1));
document.querySelector('[data-action="next"]').addEventListener("click", () => goToStep(state.stepIndex + 1));
elements.playButton.addEventListener("click", () => {
  if (state.timer) {
    stopPlayback();
  } else {
    startPlayback();
  }
});

window.addEventListener("resize", () => window.requestAnimationFrame(drawEdges));

renderRoadmap();
renderMode();
