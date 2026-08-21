# ServiceFlow V1 Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 构建一个使用模拟订单和售后政策的单 Agent 售后工单系统，让自然语言请求经过确定性业务规则和工具调用改变 PostgreSQL 状态，并用 40 个固定案例证明效果。

**Architecture:** 使用 Python 模块化单体。FastAPI 提供 HTTP JSON API，LangGraph 编排一个 Service Agent，LLM 只负责结构化语言理解和回复，Python 领域代码负责政策与状态判断，SQLAlchemy 保存模拟业务状态；开发初期使用 SQLite，最终通过 Docker Compose 运行 FastAPI 与 PostgreSQL。

**Tech Stack:** Python 3.12、uv、FastAPI、Pydantic、Uvicorn、SQLAlchemy 2、SQLite、PostgreSQL 16、OpenAI-compatible API、LangGraph、pytest、Ruff、原生 HTML/CSS/JavaScript、Docker、Docker Compose。

---

## 0. 实施协议

### 当前事实

- Task 00—17 已完成，ServiceFlow V1 已通过最终软件、Compose、真实 40 案评测、浏览器和 PostgreSQL 验收。
- 最终连接 Compose PostgreSQL 的完整测试为 53 个通过，当前没有待实施 Task。
- Agent 会话 API、40 案报告、原生前端、API 容器和作品集文档均已实现；本计划保留为实施历史，不再表示当前待办。
- 所有数据、政策和处理结果都是模拟内容。

### 每轮规则

1. 新对话先读 `README.md`、`AGENTS.md`、`docs/STATUS.md`、`docs/HANDOFF.md` 和当前 Task。
2. 每轮只执行 `docs/STATUS.md` 指向的一个 Task。
3. 先写失败测试，再写最小实现；文档任务除外。
4. 只运行当前 Task 相关测试和 Ruff；里程碑 Task 才运行完整测试。
5. 更新 `docs/STATUS.md` 后停止，不提前实施下一 Task。
6. 用户自行决定是否提交；计划给出建议提交命令，但不得自动 push。
7. 不增加安全、权限、防攻击、安全测试、重试、缓存、熔断、消息队列和计划外抽象。

### 通用命令约定

除 Docker 命令外，后端命令均从以下目录执行：

```powershell
cd C:\Users\Alex\Desktop\workspace\Project-0009-ServiceFlow\backend
```

常用验证：

```powershell
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

---

### Task 00: 初始化项目事实文档（已完成）

**Objective:** 建立新对话可以恢复的项目边界、目标、架构、评测和计划。

**Files:**

- Created: `README.md`
- Created: `AGENTS.md`
- Created: `docs/PROJECT_CONTEXT.md`
- Created: `docs/PRODUCT.md`
- Created: `docs/BOUNDARIES.md`
- Created: `docs/ARCHITECTURE.md`
- Created: `docs/EVALUATION.md`
- Created: `docs/DECISIONS.md`
- Created: `docs/STATUS.md`
- Created: `docs/HANDOFF.md`
- Created: `.gitignore`
- Created: `.hermes/plans/2026-08-09_125127-serviceflow-implementation.md`

**Acceptance:**

- 文档明确项目是学生作品集和模拟系统；
- 文档明确不做生产安全、防御性代码和安全测试；
- 所有未来功能均写成目标而不是已完成事实；
- `docs/STATUS.md` 指向 Task 01。

---

### Task 01: 初始化 Python 后端工具链

**Objective:** 建立可安装、可测试、可 lint 的最小 Python 3.12 包，不实现业务。

**Files:**

- Delete: `backend/.gitkeep`
- Create: `backend/pyproject.toml`
- Create: `backend/src/serviceflow/__init__.py`
- Create: `backend/tests/test_package.py`
- Modify: `docs/STATUS.md`

**Step 1: 写失败测试**

```python
# backend/tests/test_package.py
import serviceflow


def test_package_exposes_version() -> None:
    assert serviceflow.__version__ == "0.1.0"
```

**Step 2: 验证失败**

Run:

```powershell
uv run pytest tests/test_package.py -v
```

Expected: FAIL，因为项目尚未安装或 `serviceflow` 不存在。

**Step 3: 创建最小包配置**

`backend/pyproject.toml` 至少包含：

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "serviceflow"
version = "0.1.0"
description = "Evaluated service workflow agent over simulated after-sales data"
requires-python = ">=3.12,<3.14"
dependencies = []

[dependency-groups]
dev = [
    "pytest>=8.4,<10",
    "ruff>=0.12,<1",
]

[tool.hatch.build.targets.wheel]
packages = ["src/serviceflow"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP"]
```

`backend/src/serviceflow/__init__.py`：

```python
__version__ = "0.1.0"
```

**Step 4: 锁定依赖并验证**

Run:

```powershell
uv lock
uv sync --locked
uv run pytest tests/test_package.py -v
uv run ruff check .
uv run ruff format --check .
```

Expected: 1 test passed；Ruff 无错误。

**Step 5: 更新状态并建议提交**

`docs/STATUS.md` 标记 Task 01 完成、记录四条命令结果、下一步改为 Task 02。

```powershell
git add backend docs/STATUS.md
git commit -m "chore: initialize serviceflow backend"
```

---

### Task 02: 定义领域对象和处理结果

**Objective:** 用纯 Python 定义订单、退款、工单、审批和决策对象，不依赖数据库或模型。

**Files:**

- Create: `backend/src/serviceflow/domain/__init__.py`
- Create: `backend/src/serviceflow/domain/models.py`
- Create: `backend/src/serviceflow/domain/results.py`
- Create: `backend/tests/unit/test_domain_models.py`
- Modify: `docs/STATUS.md`

**Required contracts:**

```python
class OrderStatus(StrEnum):
    PAID = "paid"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUND_PENDING = "refund_pending"
    REFUNDED = "refunded"
    TICKET_OPEN = "ticket_open"


class RequestedAction(StrEnum):
    QUERY = "query"
    CANCEL = "cancel"
    REFUND = "refund"
    EXCHANGE = "exchange"
    REPAIR = "repair"


class IssueType(StrEnum):
    NONE = "none"
    QUALITY = "quality"
    CHANGED_MIND = "changed_mind"
    OTHER = "other"


class Decision(StrEnum):
    ASK_FOR_INFO = "ask_for_info"
    EXPLAIN_ONLY = "explain_only"
    CANCEL = "cancel"
    DIRECT_REFUND = "direct_refund"
    APPROVAL_REQUIRED = "approval_required"
    CREATE_EXCHANGE_TICKET = "create_exchange_ticket"
    CREATE_SUPPORT_TICKET = "create_support_ticket"
```

使用 `@dataclass(frozen=True, slots=True)` 定义 `Order`、`OrderItem`、`Refund`、`Ticket`、`Approval` 和 `PolicyDecision`。金额使用 `Decimal`，日期使用 `date` 或 `datetime`，不要使用浮点数。

**Step 1: 写失败测试**

测试至少证明：

- 字符串枚举值稳定；
- `Order.total_amount` 使用 Decimal；
- 冻结对象不能被原地修改；
- `PolicyDecision` 保存 `policy_id`、`decision` 和简短 `reason`。

**Step 2: 验证失败**

```powershell
uv run pytest tests/unit/test_domain_models.py -v
```

Expected: FAIL，因为领域模块不存在。

**Step 3: 最小实现并验证**

```powershell
uv run pytest tests/unit/test_domain_models.py -v
uv run ruff check src/serviceflow/domain tests/unit/test_domain_models.py
uv run ruff format --check src/serviceflow/domain tests/unit/test_domain_models.py
```

**Acceptance:** 不导入 FastAPI、SQLAlchemy、LangGraph 或 OpenAI。

```powershell
git add backend/src/serviceflow/domain backend/tests/unit docs/STATUS.md
git commit -m "feat: define serviceflow domain models"
```

---

### Task 03: 实现确定性售后政策

**Objective:** 把 `docs/PRODUCT.md` 中的模拟政策和只读查询分支实现为可单测的纯函数。

**Files:**

- Create: `backend/src/serviceflow/domain/policies.py`
- Create: `backend/tests/unit/test_policies.py`
- Modify: `docs/PRODUCT.md`（仅在实现发现契约矛盾时）
- Modify: `docs/STATUS.md`

**Required API:**

```python
def evaluate_policy(
    *,
    order: Order | None,
    requested_action: RequestedAction | None,
    issue_type: IssueType | None,
    reference_date: date,
) -> PolicyDecision:
    ...
```

**Decision order:**

1. 缺少订单或诉求：`POL-INFO-01`；
2. 查询：`EXPLAIN_ONLY`；
3. `paid` 订单取消：`POL-CANCEL-01`；
4. `delivered` 且七天内退款：金额大于 500 走 `POL-APPROVAL-01`，否则 `POL-REFUND-01`；
5. 质量问题且三十天内换货：`POL-EXCHANGE-01`；
6. 其他组合：`POL-TICKET-01`。

**Step 1: 表驱动失败测试**

至少覆盖以上六条规则和七天/三十天边界。日期必须通过 `reference_date` 注入，不能读取系统当天日期。

```python
@pytest.mark.parametrize(
    ("case_name", "expected_policy", "expected_decision"),
    [
        ("missing_order", "POL-INFO-01", Decision.ASK_FOR_INFO),
        ("paid_cancel", "POL-CANCEL-01", Decision.CANCEL),
        ("small_refund", "POL-REFUND-01", Decision.DIRECT_REFUND),
        ("large_refund", "POL-APPROVAL-01", Decision.APPROVAL_REQUIRED),
    ],
)
def test_policy_cases(...):
    ...
```

**Step 2: 运行失败、最小实现、再验证**

```powershell
uv run pytest tests/unit/test_policies.py -v
uv run pytest tests/unit -q
uv run ruff check src/serviceflow/domain tests/unit
```

**Acceptance:** 政策结果完全确定，不调用模型或数据库。

```powershell
git add backend/src/serviceflow/domain backend/tests/unit docs
git commit -m "feat: implement deterministic after-sales policies"
```

---

### Task 04: 建立 SQLite 仓储最短闭环

**Objective:** 使用 SQLAlchemy 在 SQLite 中保存和读取核心业务对象，让学生先掌握 ORM 基础。

**Files:**

- Modify: `backend/pyproject.toml`
- Modify: `backend/uv.lock`
- Create: `backend/src/serviceflow/config.py`
- Create: `backend/src/serviceflow/infrastructure/__init__.py`
- Create: `backend/src/serviceflow/infrastructure/database.py`
- Create: `backend/src/serviceflow/infrastructure/tables.py`
- Create: `backend/src/serviceflow/infrastructure/repositories.py`
- Create: `backend/tests/integration/test_sqlite_repositories.py`
- Modify: `docs/STATUS.md`

**Dependencies:**

```toml
dependencies = [
    "sqlalchemy>=2.0,<3",
]
```

**Tables for this Task:**

- `users(id, display_name)`
- `orders(id, user_id, status, total_amount, placed_at, delivered_at)`
- `order_items(id, order_id, product_name, category, unit_price, quantity)`

**Required repository methods:**

```python
class OrderRepository:
    def get(self, order_id: str) -> Order | None: ...
    def add(self, order: Order) -> None: ...
    def set_status(self, order_id: str, status: OrderStatus) -> Order: ...
```

这个仓储有当前真实用途，不创建泛型 `BaseRepository`、Unit of Work 或接口工厂。

**TDD steps:**

1. 使用临时 SQLite 文件写失败测试；
2. 证明 `add` 后 `get` 能还原领域对象；
3. 证明 `set_status` 后重新查询得到新状态；
4. 证明不存在订单返回 `None`；
5. 写最小 SQLAlchemy 实现；
6. 运行：

```powershell
uv lock
uv sync --locked
uv run pytest tests/integration/test_sqlite_repositories.py -v
uv run pytest tests/unit tests/integration/test_sqlite_repositories.py -q
uv run ruff check src/serviceflow/infrastructure tests/integration
```

**Acceptance:** SQLite 测试不需要 Docker；数据库连接字符串由 `SERVICEFLOW_DATABASE_URL` 提供，默认指向本地 SQLite 开发文件。

```powershell
git add backend docs/STATUS.md
git commit -m "feat: add sqlite order persistence"
```

---

### Task 05: 接入 PostgreSQL 和确定性种子数据

**Objective:** 让同一 SQLAlchemy 代码运行在 PostgreSQL，并提供可重复的模拟订单数据。

**Files:**

- Modify: `backend/pyproject.toml`
- Modify: `backend/uv.lock`
- Create: `compose.yaml`
- Create: `.env.example`
- Create: `backend/src/serviceflow/infrastructure/seed.py`
- Create: `backend/src/serviceflow/cli.py`
- Create: `backend/tests/fixtures/seed_data.json`
- Create: `backend/tests/integration/test_postgres_smoke.py`
- Modify: `backend/pyproject.toml`（增加 `serviceflow` CLI）
- Modify: `docs/STATUS.md`

**Dependencies and script:**

```toml
dependencies = [
    "sqlalchemy>=2.0,<3",
    "psycopg[binary]>=3.2,<4",
]

[project.scripts]
serviceflow = "serviceflow.cli:main"
```

**First Compose scope:**

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: serviceflow
      POSTGRES_USER: serviceflow
      POSTGRES_PASSWORD: serviceflow
    ports:
      - "54329:5432"
    volumes:
      - serviceflow_pgdata:/var/lib/postgresql/data

volumes:
  serviceflow_pgdata:
```

不要在本 Task 增加 API 容器、healthcheck、Redis 或自动重试。

**Seed data contract:**

- 3 个模拟用户；
- 12 个明确订单；
- 覆盖 paid、shipped、delivered、cancelled；
- 覆盖 199、499、899 三种代表金额；
- 日期固定在 2026-07，不使用当前时间；
- 重复 seed 先清空项目表再重建，仅用于本地模拟环境。

**CLI commands:**

```powershell
uv run serviceflow db-init
uv run serviceflow seed
uv run serviceflow show-order ORDER-001
```

**Verification:**

```powershell
docker compose up -d postgres
$env:SERVICEFLOW_DATABASE_URL="postgresql+psycopg://serviceflow:serviceflow@localhost:54329/serviceflow"
uv run serviceflow db-init
uv run serviceflow seed
uv run pytest tests/integration/test_postgres_smoke.py -v
docker compose down
```

Expected: PostgreSQL smoke test 通过，`show-order` 输出固定订单 JSON。

```powershell
git add compose.yaml .env.example backend docs/STATUS.md
git commit -m "feat: add postgres demo database"
```

---

### Task 06: 实现订单和售后应用服务

**Objective:** 实现 Agent 和 API 都能复用的确定性业务用例。

**Files:**

- Extend: `backend/src/serviceflow/infrastructure/tables.py`
- Extend: `backend/src/serviceflow/infrastructure/repositories.py`
- Create: `backend/src/serviceflow/application/__init__.py`
- Create: `backend/src/serviceflow/application/order_service.py`
- Create: `backend/src/serviceflow/application/case_service.py`
- Create: `backend/tests/integration/test_case_service.py`
- Modify: `docs/STATUS.md`

**New tables:**

- `refunds(id, order_id, amount, status, created_at)`
- `tickets(id, order_id, kind, status, summary, created_at)`
- `approvals(id, order_id, requested_action, status, created_at)`

**Required service methods:**

```python
class CaseService:
    def get_order(self, order_id: str) -> Order | None: ...
    def cancel_order(self, order_id: str) -> CaseResult: ...
    def request_refund(self, order_id: str) -> CaseResult: ...
    def create_ticket(self, order_id: str, kind: str, summary: str) -> CaseResult: ...
    def create_approval(self, order_id: str, action: RequestedAction) -> CaseResult: ...
    def decide_approval(self, approval_id: str, approved: bool) -> CaseResult: ...
    def get_case_status(self, case_id: str) -> CaseResult | None: ...
```

业务方法在同一个 SQLAlchemy Session 中完成必要写入和状态更新。只处理本项目规则，不增加自动重试、幂等平台或分布式事务。

**TDD cases:**

- paid 订单取消后状态为 cancelled；
- delivered 小额订单产生 completed refund 并变为 refunded；
- 大额订单只创建 pending approval；
- 质量问题创建 exchange ticket 并变为 ticket_open；
- 查询不存在订单返回结构化 `order_not_found`。

**Verification:**

```powershell
uv run pytest tests/integration/test_case_service.py -v
uv run pytest tests/unit tests/integration -q
uv run ruff check src/serviceflow/application src/serviceflow/infrastructure tests/integration
```

```powershell
git add backend/src/serviceflow backend/tests docs/STATUS.md
git commit -m "feat: add after-sales application services"
```

---

### Task 07: 增加非 Agent FastAPI 业务接口

**Objective:** 先证明普通 HTTP API 和数据库业务闭环，再引入 LLM。

**Files:**

- Modify: `backend/pyproject.toml`
- Modify: `backend/uv.lock`
- Create: `backend/src/serviceflow/api/__init__.py`
- Create: `backend/src/serviceflow/api/app.py`
- Create: `backend/src/serviceflow/api/schemas.py`
- Create: `backend/src/serviceflow/api/routes.py`
- Create: `backend/tests/api/test_business_api.py`
- Modify: `docs/STATUS.md`

**Dependencies:**

```toml
dependencies = [
    "fastapi>=0.116,<1",
    "pydantic>=2.11,<3",
    "uvicorn>=0.35,<1",
]

[dependency-groups]
dev = [
    "httpx>=0.28,<1",
    "pytest>=8.4,<10",
    "ruff>=0.12,<1",
]
```

**Routes:**

- `GET /api/v1/health`
- `GET /api/v1/orders/{order_id}`
- `POST /api/v1/demo/reset`
- `GET /api/v1/cases/{case_id}`

`demo/reset` 只重载项目模拟数据，不做生产语义。

**TDD:** 使用 FastAPI `TestClient` 和临时 SQLite 依赖覆盖，证明 health、订单查询、404 和 reset 行为。

**Verification:**

```powershell
uv lock
uv sync --locked
uv run pytest tests/api/test_business_api.py -v
uv run uvicorn serviceflow.api.app:app --host 127.0.0.1 --port 8009
```

手工读取 `http://127.0.0.1:8009/docs`，确认四个端点存在后停止服务。

```powershell
git add backend docs/STATUS.md
git commit -m "feat: expose serviceflow business api"
```

---

### Task 08: 冻结首批 10 个评测案例

**Objective:** 在模型接入前建立不可随意改变的业务答案集。

**Files:**

- Delete: `tests/.gitkeep`
- Create: `tests/eval_cases/serviceflow_v1_seed.jsonl`
- Create: `backend/src/serviceflow/evaluation/__init__.py`
- Create: `backend/src/serviceflow/evaluation/models.py`
- Create: `backend/src/serviceflow/evaluation/loader.py`
- Create: `backend/tests/evals/test_eval_case_contract.py`
- Modify: `docs/EVALUATION.md`
- Modify: `docs/STATUS.md`

**Ten case IDs:**

```text
cancel_paid_001
query_shipped_001
refund_small_001
refund_high_value_001
exchange_quality_001
support_ticket_expired_001
missing_order_id_001
missing_action_001
refund_seven_day_boundary_001
exchange_thirty_day_boundary_001
```

每个案例必须包含 `id`、`user_id`、`initial_state`、`messages` 和 `expected`。期望值包括 intent、policy_id、decision、expected_tools 和 final state。

**TDD:**

1. loader 能读取 10 个唯一案例；
2. 枚举值均能解析；
3. 每个订单 ID 都存在于 seed fixture；
4. 使用 Task 03 政策函数重新计算时，期望 policy 和 decision 一致。

不加入安全、恶意输入、工具故障和网络故障案例。

```powershell
uv run pytest tests/evals/test_eval_case_contract.py -v
uv run pytest tests/unit tests/evals -q
uv run ruff check src/serviceflow/evaluation tests/evals
```

**Acceptance:** 10 个案例通过确定性契约校验；后续不能为提高模型成绩修改其正确答案。

```powershell
git add tests/eval_cases backend/src/serviceflow/evaluation backend/tests/evals docs
git commit -m "test: freeze initial serviceflow eval cases"
```

---

### Task 09: 实现 OpenAI-compatible 模型适配器

**Objective:** 建立一个可注入 Fake Model 的结构化模型调用边界，软件测试不访问网络。

**Files:**

- Modify: `backend/pyproject.toml`
- Modify: `backend/uv.lock`
- Create: `backend/src/serviceflow/agent/__init__.py`
- Create: `backend/src/serviceflow/agent/model.py`
- Create: `backend/tests/agent/test_model_adapter.py`
- Modify: `.env.example`
- Modify: `docs/STATUS.md`

**Dependencies:**

```toml
dependencies = [
    "openai>=2,<3",
]
```

**Environment contract:**

```text
SERVICEFLOW_API_KEY
SERVICEFLOW_BASE_URL
SERVICEFLOW_MODEL
```

**Required boundary:**

```python
class StructuredModel(Protocol):
    def complete_json(self, *, system: str, user: str) -> ModelResult: ...


@dataclass(frozen=True, slots=True)
class ModelResult:
    content: dict[str, object]
    model: str
    input_tokens: int
    output_tokens: int
```

`OpenAICompatibleModel` 只负责一次请求和 JSON 结果解析。不要在本 Task 添加重试、fallback、模型路由、缓存或流式输出。

**Tests:**

- 缺少环境变量时返回清楚配置错误；
- fake OpenAI client 的 JSON 被映射为 `ModelResult`；
- token 使用被记录；
- 测试代码不访问网络。

```powershell
uv lock
uv sync --locked
uv run pytest tests/agent/test_model_adapter.py -v
uv run ruff check src/serviceflow/agent tests/agent
```

```powershell
git add backend .env.example docs/STATUS.md
git commit -m "feat: add structured model adapter"
```

---

### Task 10: 实现结构化意图提取

**Objective:** 让模型把用户消息转换为稳定的订单售后意图，第一次建立实际运行 Prompt。

**Files:**

- Create: `backend/src/serviceflow/agent/state.py`
- Create: `backend/src/serviceflow/agent/intent.py`
- Create: `backend/src/serviceflow/agent/prompts/service_agent_v1.txt`
- Create: `backend/tests/agent/test_intent_extraction.py`
- Modify: `docs/STATUS.md`

**ParsedIntent schema:**

```python
class ParsedIntent(BaseModel):
    order_id: str | None
    requested_action: RequestedAction | None
    issue_type: IssueType
    issue_summary: str
    missing_fields: list[str]
```

Prompt 只描述支持的意图、JSON schema、模拟业务背景和缺失字段规则。不要让 Prompt 自行决定政策或数据库状态。

**TDD with Fake Model:**

- 取消订单请求；
- 质量问题退款请求；
- 缺少订单号；
- 仅查询处理结果；
- 模型输出无法解析时返回 `intent_parse_error`，不增加重试。

```powershell
uv run pytest tests/agent/test_intent_extraction.py -v
uv run pytest tests/agent -q
uv run ruff check src/serviceflow/agent tests/agent
```

**Acceptance:** Prompt 文件名和运行结果记录版本 `service_agent_v1`；这是第一个且唯一的 Prompt 版本。

```powershell
git add backend/src/serviceflow/agent backend/tests/agent docs/STATUS.md
git commit -m "feat: extract structured service intent"
```

---

### Task 11: 编排 LangGraph 单 Agent 工作流

**Objective:** 完成不含人工恢复的第一条端到端 Agent 路径。

**Files:**

- Modify: `backend/pyproject.toml`
- Modify: `backend/uv.lock`
- Create: `backend/src/serviceflow/agent/tools.py`
- Create: `backend/src/serviceflow/agent/graph.py`
- Create: `backend/tests/agent/test_agent_graph.py`
- Create: `backend/tests/evals/test_seed_eval_with_fake_model.py`
- Modify: `docs/STATUS.md`

**Dependencies:**

```toml
dependencies = [
    "langgraph>=0.6,<2",
]
```

**Graph nodes:**

```text
extract_intent
route_missing_info
load_order
evaluate_policy
execute_action
read_final_state
compose_response
```

`tools.py` 只把 Task 06 的 `CaseService` 方法包装成结构化 Agent 工具，不能复制业务规则。

**TDD paths:**

- paid 订单自然语言取消后数据库为 cancelled；
- 小额退款后数据库为 refunded；
- 换货请求创建 ticket；
- 信息不足时只返回补充问题；
- 10 个 seed 案例使用预设 Fake Model 结果完成可重复执行。

此 Task 遇到 `APPROVAL_REQUIRED` 时只返回 pending，不实现恢复；恢复留给 Task 12。

```powershell
uv lock
uv sync --locked
uv run pytest tests/agent/test_agent_graph.py -v
uv run pytest tests/evals/test_seed_eval_with_fake_model.py -v
uv run pytest tests/unit tests/integration tests/agent tests/evals -q
uv run ruff check src tests
```

```powershell
git add backend docs/STATUS.md
git commit -m "feat: build single service agent graph"
```

---

### Task 12: 增加人工审批中断与恢复

**Objective:** 展示高金额退款经过 LangGraph 中断、人工决定和继续执行的真实业务分支。

**Files:**

- Modify: `backend/src/serviceflow/agent/state.py`
- Modify: `backend/src/serviceflow/agent/graph.py`
- Modify: `backend/src/serviceflow/application/case_service.py`
- Create: `backend/tests/agent/test_approval_resume.py`
- Modify: `docs/ARCHITECTURE.md`（记录最终选用的 checkpoint 方案）
- Modify: `docs/STATUS.md`

**Required behavior:**

1. 高金额退款创建 `approval`，状态 `pending`；
2. 图返回 `approval_required` 和 `approval_id`；
3. 演示者提交 approve 后，同一 thread 继续并完成退款；
4. 提交 reject 后，订单保持原状态，审批变为 rejected；
5. 测试使用 LangGraph 内存 checkpointer；业务审批状态保存在数据库；
6. 不增加用户角色、鉴权、风控或安全测试。

**TDD:**

```python
def test_high_value_refund_pauses_and_resumes_after_approval(...):
    first = graph.invoke(..., config={"configurable": {"thread_id": "case-1"}})
    assert first["decision"] == "approval_required"

    resumed = graph.invoke(Command(resume={"approved": True}), config=...)
    assert resumed["final_business_state"]["order_status"] == "refunded"
```

同时测试拒绝分支。

```powershell
uv run pytest tests/agent/test_approval_resume.py -v
uv run pytest tests/agent tests/integration/test_case_service.py -q
uv run ruff check src/serviceflow/agent src/serviceflow/application tests/agent
```

```powershell
git add backend docs
git commit -m "feat: support approval pause and resume"
```

---

### Task 13: 暴露 Agent 会话 HTTP API

**Objective:** 让浏览器可以创建会话、发送消息、查询轨迹并提交审批决定。

**Files:**

- Modify: `backend/src/serviceflow/api/schemas.py`
- Modify: `backend/src/serviceflow/api/routes.py`
- Modify: `backend/src/serviceflow/api/app.py`
- Create: `backend/tests/api/test_agent_api.py`
- Modify: `docs/STATUS.md`

**Routes:**

- `POST /api/v1/conversations`
- `POST /api/v1/conversations/{thread_id}/messages`
- `GET /api/v1/conversations/{thread_id}`
- `POST /api/v1/conversations/{thread_id}/approvals/{approval_id}`

**Response contract:**

```json
{
  "thread_id": "demo-001",
  "assistant_message": "...",
  "decision": "approval_required",
  "policy_id": "POL-APPROVAL-01",
  "tool_events": [],
  "final_business_state": {},
  "approval": {"id": "APPROVAL-001", "status": "pending"},
  "model": "fake-or-real-model",
  "prompt_version": "service_agent_v1",
  "token_usage": {"input": 0, "output": 0}
}
```

**TDD:** 使用 Fake Model 和 SQLite 覆盖创建会话、直接处理、信息补充、审批同意和审批拒绝。测试不调用真实模型。

```powershell
uv run pytest tests/api/test_agent_api.py -v
uv run pytest tests/api tests/agent -q
uv run ruff check src/serviceflow/api tests/api
```

```powershell
git add backend/src/serviceflow/api backend/tests/api docs/STATUS.md
git commit -m "feat: expose service agent conversations"
```

---

### Task 14: 扩展 40 案评测并生成报告

**Objective:** 用真实模型和固定业务状态量化项目效果。

**Files:**

- Rename: `tests/eval_cases/serviceflow_v1_seed.jsonl` -> `tests/eval_cases/serviceflow_v1.jsonl`
- Create: `backend/src/serviceflow/evaluation/runner.py`
- Create: `backend/src/serviceflow/evaluation/report.py`
- Modify: `backend/src/serviceflow/cli.py`
- Create: `backend/tests/evals/test_eval_runner.py`
- Create: `backend/tests/evals/test_eval_metrics.py`
- Create at runtime: `outputs/evaluation/serviceflow-v1-results.json`
- Create at runtime: `outputs/evaluation/serviceflow-v1-report.md`
- Modify: `docs/EVALUATION.md`
- Modify: `docs/STATUS.md`

**Case composition:**

- 16 normal handling；
- 10 business boundaries；
- 6 clarification；
- 8 natural-language variants；
- total exactly 40 unique IDs；
- no security, malicious input, failure injection or load cases.

**CLI:**

```powershell
uv run serviceflow eval --cases ..\tests\eval_cases\serviceflow_v1.jsonl --output ..\outputs\evaluation
```

**Runner behavior:**

1. 每案重置数据库到声明的初始状态；
2. 发送一条或多条消息；
3. 如果案例要求审批，按案例中的固定决定恢复；
4. 从数据库重新读取最终状态；
5. 计算 outcome、final state、policy、tool、clarification、latency、token；
6. 保存每案明细和聚合指标；
7. 记录模型、Prompt 版本、提交号和时间。

**TDD:** 指标测试全部使用手工构造结果，runner 测试使用 Fake Model。真实模型评测是本 Task 的手工验收，不是普通 pytest。

```powershell
uv run pytest tests/evals/test_eval_runner.py tests/evals/test_eval_metrics.py -v
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

配置真实模型后运行一次完整评测。不得为提高成绩修改冻结案例的期望结果。

**Acceptance:** 40 个案例都被执行；报告包含成功率和失败案例；真实结果未达到建议目标也要如实保存。

```powershell
git add tests/eval_cases backend/src/serviceflow/evaluation backend/tests/evals outputs/evaluation docs
git commit -m "feat: evaluate service agent on fixed cases"
```

---

### Task 15: 增加轻量浏览器演示

**Objective:** 用一个无需 Node 构建链的页面展示对话、订单、工具轨迹和审批。

**Files:**

- Delete: `frontend/.gitkeep`
- Create: `frontend/index.html`
- Create: `frontend/app.js`
- Create: `frontend/styles.css`
- Modify: `backend/src/serviceflow/api/app.py`
- Create: `backend/tests/api/test_cors_and_contract.py`
- Modify: `docs/STATUS.md`

**Page layout:**

- 模拟用户和示例订单选择；
- 对话消息区；
- 文本输入与发送按钮；
- 当前订单/退款/工单/审批状态卡片；
- 工具事件时间线；
- pending 审批的同意和拒绝按钮；
- 三个一键填充演示案例；
- 评测摘要链接。

只使用原生 HTML/CSS/JS。不要加入 React、Vue、npm、组件库、登录页或管理后台。

FastAPI 允许本地 `http://127.0.0.1:5173` 和 `http://localhost:5173` CORS，用于开发演示。

**Verification:**

```powershell
# Terminal 1
uv run uvicorn serviceflow.api.app:app --host 127.0.0.1 --port 8009

# Terminal 2, from frontend/
python -m http.server 5173
```

浏览器手工完成：未发货取消、小额退款、高金额审批后退款。保存三个检查结果到 `docs/STATUS.md`，不创建前端安全测试。

```powershell
uv run pytest tests/api/test_cors_and_contract.py -v
uv run pytest tests/api -q
uv run ruff check src/serviceflow/api tests/api
```

```powershell
git add frontend backend/src/serviceflow/api backend/tests/api docs/STATUS.md
git commit -m "feat: add serviceflow browser demo"
```

---

### Task 16: 容器化 API 并完成 Docker Compose

**Objective:** 使用一条 Compose 命令启动 PostgreSQL 和 FastAPI，完成可移交演示环境。

**Files:**

- Create: `backend/Dockerfile`
- Create: `backend/.dockerignore`
- Modify: `compose.yaml`
- Modify: `.env.example`
- Modify: `README.md`
- Create: `backend/tests/api/test_health.py`（若已有 health 测试则复用，不重复创建）
- Modify: `docs/STATUS.md`

**Dockerfile expectations:**

- 基于固定 Python 3.12 slim 镜像；
- 复制 `pyproject.toml` 和 `uv.lock`；
- 使用锁文件安装运行依赖；
- 复制 `src/`；
- 启动 `uvicorn serviceflow.api.app:app --host 0.0.0.0 --port 8000`；
- 不加入多阶段优化、非 root 用户、安全扫描和生产服务器调优。

**Final Compose:**

- `postgres`：现有 PostgreSQL 16；
- `api`：从 `backend/Dockerfile` 构建；
- API 读取 Compose 内部数据库地址；
- 暴露宿主机 `8009`；
- 不增加 Redis、Nginx、队列或自动重试脚本。

**Verification:**

```powershell
docker compose build
docker compose up -d
Invoke-RestMethod http://127.0.0.1:8009/api/v1/health
Invoke-RestMethod -Method Post http://127.0.0.1:8009/api/v1/demo/reset
Invoke-RestMethod http://127.0.0.1:8009/api/v1/orders/ORDER-001
docker compose down
```

Expected: 三个 HTTP 请求返回成功；`docker compose ps` 中两个服务运行。

```powershell
git add backend/Dockerfile backend/.dockerignore compose.yaml .env.example README.md docs/STATUS.md
git commit -m "chore: run serviceflow with docker compose"
```

---

### Task 17: 完成最终评测与作品集交付

**Objective:** 冻结一个真实、可运行、可面试讲解的 V1，并在达到验收后停止。

**Files:**

- Create: `docs/DEVELOPMENT.md`
- Create: `docs/PORTFOLIO.md`
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/EVALUATION.md`
- Modify: `docs/STATUS.md`
- Modify: `docs/HANDOFF.md`
- Create or refresh: `outputs/evaluation/serviceflow-v1-results.json`
- Create or refresh: `outputs/evaluation/serviceflow-v1-report.md`

**Step 1: 全量软件验证**

```powershell
cd backend
uv sync --locked
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

**Step 2: PostgreSQL 与 Compose 验证**

```powershell
cd ..
docker compose build
docker compose up -d
Invoke-RestMethod http://127.0.0.1:8009/api/v1/health
docker compose down
```

**Step 3: 真实 Agent 评测**

配置环境变量，运行 40 案评测，保存未经挑选的完整结果。报告必须包含：

- 模型和 Prompt 版本；
- 40 案执行总数；
- 六项核心指标；
- 失败案例和原因分类；
- Token 和耗时；
- 已知限制。

**Step 4: 浏览器验收**

重新运行三条演示：

1. paid 订单取消；
2. 小额直接退款；
3. 高金额审批后退款。

**Step 5: 完成作品集说明**

`docs/PORTFOLIO.md` 至少包含：

- 一句话项目介绍；
- 与 CodeInsight 的能力互补；
- 架构图；
- 三条演示流程；
- 评测方法和真实指标；
- 两条推荐简历 bullet，但指标必须来自实际报告；
- 五个常见面试问题及基于代码的回答位置；
- 明确说明模拟数据和非生产边界。

**Step 6: 更新最终状态**

`docs/STATUS.md` 改为 `V1 已完成`，记录验证命令和结果；`README.md` 不得保留“尚未实现”描述；`docs/HANDOFF.md` 改为维护入口。

**V1 stop point:**

- 核心业务、Agent、API、PostgreSQL、Compose、前端和 40 案评测全部有真实证据；
- 不增加多 Agent、MCP、Redis、向量数据库、安全测试或其他扩展；
- 没有值得回写的全局经验时，在 README 记录“无新增全局条目”；
- 达到条件后停止。

```powershell
git add README.md docs outputs/evaluation
git commit -m "docs: complete serviceflow v1 portfolio"
```

---

## 1. Task 依赖关系

```text
00 docs complete
  -> 01 toolchain
  -> 02 domain
  -> 03 policies
  -> 04 sqlite persistence
  -> 05 postgres + seed
  -> 06 application services
  -> 07 deterministic API
  -> 08 first 10 eval cases
  -> 09 model adapter
  -> 10 intent extraction
  -> 11 agent graph
  -> 12 approval resume
  -> 13 agent API
  -> 14 forty-case eval
  -> 15 browser demo
  -> 16 final compose
  -> 17 portfolio delivery
```

不得跳过 03、06 或 08 直接做 Agent；否则业务正确答案和评测依据都不稳定。

## 2. PostgreSQL 与 Docker 学习检查点

### PostgreSQL 最低知识范围

只要求掌握：表、主键、外键、SELECT、INSERT、UPDATE、SQLAlchemy Session、一次事务和数据库 URL。V1 不学习查询优化、复制、分区、备份和权限管理。

### Docker Compose 最低知识范围

只要求掌握：services、image、build、ports、environment、volumes、`up`、`down` 和 `logs`。V1 不学习 Kubernetes、Swarm、Nginx 或生产部署。

## 3. 主要风险与处理方式

- **模型输出不稳定：** 用结构化意图、确定性政策和最终数据库状态缩小模型职责；保留真实失败，不增加重试。
- **同时学习数据库和 Agent 负担过大：** Task 02-04 先用纯 Python 和 SQLite；Task 05 单独学习 PostgreSQL。
- **Docker 调试占用工期：** Task 05 只运行数据库，Task 16 才容器化 API。
- **LangGraph API 版本变化：** Task 11 开始前读取已锁定版本的官方文档，按当前安装版本实现；不凭旧记忆猜 API。
- **案例过拟合：** 先冻结 10 案，再扩展 30 个语言和业务变体；不能修改期望结果迎合模型。
- **作品集过度工程化：** 每个新机制必须对应本文某个用户故事或已发生失败，否则不加入。

## 4. 开放配置

Task 09 已确认 `SERVICEFLOW_BASE_URL` 和 `SERVICEFLOW_MODEL` 的环境契约，并完成一次真实模型 JSON 冒烟。以下配置继续按需填写：

- 单次 40 案评测预算；
- LangGraph 锁定版本对应的 checkpointer API。

这些配置只能通过环境变量和锁文件体现，不得把 Key 写入仓库。
