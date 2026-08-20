# ServiceFlow 公开架构说明

## 1. 一次请求如何流转

```mermaid
flowchart TD
    A["用户输入自然语言"] --> B["前端发送 HTTP JSON"]
    B --> C["FastAPI 会话接口"]
    C --> D["LangGraph 读取当前 thread 状态"]
    D --> E["模型提取结构化意图"]
    E --> F{"信息是否完整？"}
    F -->|否| G["生成追问\n不调用业务工具"]
    F -->|是| H["读取订单"]
    H --> I["Python 确定性政策判断"]
    I --> J{"业务路径"}
    J -->|取消| K["cancel_order"]
    J -->|直接退款| L["request_refund"]
    J -->|换货或维修| M["create_ticket"]
    J -->|高金额退款| N["create_approval"]
    N --> O["interrupt 等待人工决定"]
    O -->|同一 thread resume| P["decide_approval"]
    K --> Q["重新读取数据库最终状态"]
    L --> Q
    M --> Q
    P --> Q
    Q --> R["生成可核验回复"]
    G --> S["返回追问"]
    R --> T["前端展示结果和工具轨迹"]
    S --> T
```

## 2. 分层职责

| 层 | 负责什么 | 不负责什么 |
| --- | --- | --- |
| `domain` | 订单状态、退款期限、金额审批等确定性规则 | HTTP、数据库和模型调用 |
| `application` | 组合业务用例，统一管理副作用边界 | 解释自然语言 |
| `infrastructure` | SQLAlchemy 表、Session、仓储和种子数据 | 决定用户意图 |
| `agent` | LangGraph 状态、模型适配、工具包装和图编排 | 直接拼接 SQL |
| `api` | 对外提供 HTTP JSON 接口 | 把业务规则写进路由 |
| `evaluation` | 重置案例、运行请求、读取终态和计算指标 | 修改期望答案迎合模型 |

## 3. Agent 状态

状态保存可审查的业务字段，例如：

```text
thread_id / user_id / user_message
order_id / issue_type / requested_action
order_snapshot / policy_id / decision
missing_fields / tool_events / approval_id / case_id
final_business_state / assistant_message / error
model_name / prompt_version / token_usage
```

状态不保存模型隐藏推理。LangGraph 的进程内 checkpoint 负责同一进程内的中断恢复；订单、退款、工单和审批状态以 MySQL 为业务事实来源。

当前实验分支将运行链路改为异步：FastAPI 路由使用 `async def`，图调用使用
`ainvoke` / `aget_state`，模型适配器使用异步 Chat API，数据库使用 SQLAlchemy
`AsyncSession`，Compose 中的 MySQL 驱动为 `aiomysql`，SQLite 测试驱动为 `aiosqlite`。
只做日期、状态和政策判断的纯 Python 函数仍保持普通同步函数，因为它们没有等待外部
I/O 的必要。

## 4. 模型与数据库的边界

```mermaid
flowchart LR
    LLM["模型\n理解语言"] --> INTENT["结构化意图"]
    INTENT --> POLICY["Python 政策\n判断是否合法"]
    POLICY --> TOOL["业务工具\n执行受限动作"]
    TOOL --> SERVICE["应用服务"]
    SERVICE --> REPO["SQLAlchemy 仓储"]
    REPO --> DB["MySQL 业务事实"]
```

因此，“模型说已经退款”不等于退款成功。只有工具调用成功、应用服务完成写入，并从数据库重新读取到预期状态，系统才会向用户返回完成结论。

## 5. 服务边界

Compose 只包含两个后端服务：

- `api`：FastAPI 和 LangGraph，宿主机端口 `8009`；
- `mysql`：MySQL 8.4，宿主机端口 `33069`。

前端是静态 HTML/CSS/JavaScript 文件，开发时由本机 Python 静态服务器提供，默认端口 `5173`，不与后端源码互相导入。
