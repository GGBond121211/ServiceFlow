from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from serviceflow.infrastructure.database import Base


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100))


class OrderRow(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(32))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    items: Mapped[list["OrderItemRow"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="OrderItemRow.id",
    )


class OrderItemRow(Base):
    __tablename__ = "order_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    product_name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(100))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    quantity: Mapped[int] = mapped_column(Integer)
    order: Mapped[OrderRow] = relationship(back_populates="items")


class RefundRow(Base):
    __tablename__ = "refunds"
    __table_args__ = (
        Index("ix_refunds_order_created_at", "order_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TicketRow(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        Index("ix_tickets_order_created_at", "order_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    summary: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ApprovalRow(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        Index("ix_approvals_order_created_at", "order_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    requested_action: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------------------
# 2.0 Step 2：会话 / 目标 / 案件 / 操作 / 运行
#
# 上面五张表是 V1 的**业务结果**（订单、退款、工单、审批），一行不改动——
# V1 已按 v1.0.0 / v1.0.1 在远程冻结，改了 baseline 就失效。
#
# 下面这些表是新增的**过程与状态**。分工：
#   after_sales_cases / operations   业务状态，MySQL 是最终事实
#   langgraph_checkpoint*            恢复上下文，可以丢，丢了只是要重跑
#   event_log                        审计记录，全量保留，不参与 Trace 采样
# 三者不能互相冒充。
# ---------------------------------------------------------------------------


class ConfirmationClaimRow(Base):
    __tablename__ = "confirmation_claims"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConversationSessionRow(Base):
    """一次对话。V1 只有 LangGraph 的 thread_id，回答不了"这个用户还有几个
    没办完的售后"。"""

    __tablename__ = "conversation_sessions"
    __table_args__ = (
        Index("ix_sessions_tenant_user", "tenant_id", "user_id"),
        Index("ix_sessions_last_active", "last_active_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    # 刻意不加 users.id 外键：评测和多租户场景下会话可能先于用户档案存在。
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    channel: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    summary_version: Mapped[int] = mapped_column(Integer, default=0)


class AfterSalesGoalRow(Base):
    """用户当前想达成什么。一个 Session 可以有多个，但一个 Goal 不能被无声
    地改成另一个案件——判定在 `domain/sessions.resolve_goal`。"""

    __tablename__ = "after_sales_goals"
    __table_args__ = (
        Index("ix_goals_session_status", "session_id", "status"),
        Index("ix_goals_order", "order_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("conversation_sessions.id"), index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(32))
    scene_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16))
    order_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    required_facts: Mapped[list[str]] = mapped_column(JSON, default=list)
    known_facts: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    case_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AfterSalesCaseRow(Base):
    """一个售后案件。`state_version` 是乐观锁列，UPDATE 时带 WHERE 比对。"""

    __tablename__ = "after_sales_cases"
    __table_args__ = (
        Index("ix_cases_tenant_status", "tenant_id", "status"),
        Index("ix_cases_order", "order_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    goal_id: Mapped[str] = mapped_column(ForeignKey("after_sales_goals.id"), index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(32))
    order_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    case_type: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(32))
    state_version: Mapped[int] = mapped_column(Integer)
    policy_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    policy_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    handoff_ticket_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CaseTimelineRow(Base):
    """案件的状态转移流水。只记事实（谁在什么时候把状态从哪推到哪），
    不记模型的推理过程。"""

    __tablename__ = "case_timeline"
    __table_args__ = (Index("ix_case_timeline_case_seq", "case_id", "seq"),)

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("after_sales_cases.id"), index=True)
    from_status: Mapped[str] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str] = mapped_column(String(16))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    note: Mapped[str] = mapped_column(String(500), default="")


class OperationRow(Base):
    """一次有副作用的操作。

    `action_id` 上的唯一约束是幂等的**最后一道防线**：应用层的
    `classify_replay` 可能因并发读到 None，数据库这里一定挡住。
    唯一性是全局的（不按租户分片），因为 action_id 由调用方生成并要求全局唯一。
    """

    __tablename__ = "operations"
    __table_args__ = (
        UniqueConstraint("action_id", name="uq_operations_action_id"),
        Index("ix_operations_case_requested", "case_id", "requested_at"),
        Index("ix_operations_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("after_sales_cases.id"), index=True)
    action_type: Mapped[str] = mapped_column(String(32))
    action_id: Mapped[str] = mapped_column(String(64))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    state_version: Mapped[int] = mapped_column(Integer)
    attempt: Mapped[int] = mapped_column(Integer)
    error_class: Mapped[str] = mapped_column(String(32))
    result_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AgentRunRow(Base):
    """模型的一次运行。和 Case 是多对一：一个案件可能跑很多次。"""

    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_runs_case_started", "case_id", "started_at"),
        Index("ix_runs_thread", "thread_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    thread_id: Mapped[str] = mapped_column(String(64))
    goal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    case_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    operation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AgentRunSnapshotRow(Base):
    """恢复点。`payload` 里的键受 `run_store` 的黑名单校验，
    模型隐藏推理不许进来。"""

    __tablename__ = "agent_run_snapshots"
    __table_args__ = (Index("ix_run_snapshots_run_seq", "run_id", "seq"),)

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    state_version: Mapped[int] = mapped_column(Integer)
    checkpoint_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EventLogRow(Base):
    """业务事件的审计流水。

    注意三点：
    - 这是**业务事件**，不是应用日志（应用日志在 Step 8 走结构化 JSON）。
    - 全量保留，**不参与 Trace 采样**——采样掉的审计等于没有审计。
    - 只追加。`EventLog` 这个类刻意不提供 update / delete。
    """

    __tablename__ = "event_log"
    __table_args__ = (
        Index("ix_event_log_case_seq", "case_id", "seq"),
        Index("ix_event_log_operation_seq", "operation_id", "seq"),
        Index("ix_event_log_session_seq", "session_id", "seq"),
        Index("ix_event_log_type_recorded", "event_type", "recorded_at"),
    )

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64))
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    actor: Mapped[str] = mapped_column(String(16))
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    goal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    case_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    operation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # W3C traceparent 的 trace-id 部分。Step 8 靠它做日志与 Trace 双向跳转。
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SupportQueueRow(Base):
    __tablename__ = "support_queue"
    __table_args__ = (
        Index("ix_support_queue_tenant_status_priority", "tenant_id", "status", "priority"),
        Index("ix_support_queue_session", "session_id"),
        Index("ix_support_queue_case", "case_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(32))
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    case_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason_code: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(500))
    customer_message: Mapped[str] = mapped_column(String(500))
    queue: Mapped[str] = mapped_column(String(32))
    priority: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    context: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(500), nullable=True)


class ProviderEventInboxRow(Base):
    __tablename__ = "provider_event_inbox"
    __table_args__ = (
        UniqueConstraint("provider", "event_id", name="uq_provider_event"),
        Index("ix_provider_event_operation", "operation_id"),
    )

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(64))
    event_id: Mapped[str] = mapped_column(String(128))
    event_type: Mapped[str] = mapped_column(String(64))
    operation_id: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    traceparent: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OutboxMessageRow(Base):
    __tablename__ = "outbox_messages"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_outbox_dedupe_key"),
        Index("ix_outbox_status_available", "status", "available_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dedupe_key: Mapped[str] = mapped_column(String(128))
    aggregate_type: Mapped[str] = mapped_column(String(32))
    aggregate_id: Mapped[str] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16))
    attempt: Mapped[int] = mapped_column(Integer)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(128), nullable=True)
    traceparent: Mapped[str] = mapped_column(String(64))
    tracestate: Mapped[str | None] = mapped_column(String(256), nullable=True)


class TaskEnvelopeRow(Base):
    __tablename__ = "task_envelopes"
    __table_args__ = (
        Index("ix_tasks_status_available", "status", "available_at"),
        Index("ix_tasks_operation", "operation_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64))
    session_id: Mapped[str] = mapped_column(String(64))
    case_id: Mapped[str] = mapped_column(String(64))
    operation_id: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    task_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    attempt: Mapped[int] = mapped_column(Integer)
    max_attempts: Mapped[int] = mapped_column(Integer)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    error_class: Mapped[str] = mapped_column(String(32))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    traceparent: Mapped[str] = mapped_column(String(64))
    tracestate: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# --- LangGraph checkpoint 持久化 -------------------------------------------
#
# 表结构照 InMemorySaver 的三段式内部布局落地：checkpoint 本体、按
# (channel, version) 分开存的 channel 值、以及 pending writes。
# 分三张表而不是把 channel_values 塞进一个 blob，是为了让同一个 channel 的
# 同一版本只存一份——否则每步 checkpoint 都要复制全量状态。


class CheckpointRow(Base):
    __tablename__ = "langgraph_checkpoints"
    __table_args__ = (Index("ix_checkpoints_thread_ns_id", "thread_id", "checkpoint_ns", "id"),)

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    checkpoint_ns: Mapped[str] = mapped_column(String(128), primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    parent_checkpoint_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    checkpoint_type: Mapped[str] = mapped_column(String(32))
    checkpoint_blob: Mapped[bytes] = mapped_column(LargeBinary)
    metadata_type: Mapped[str] = mapped_column(String(32))
    metadata_blob: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CheckpointBlobRow(Base):
    __tablename__ = "langgraph_checkpoint_blobs"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    checkpoint_ns: Mapped[str] = mapped_column(String(128), primary_key=True)
    channel: Mapped[str] = mapped_column(String(128), primary_key=True)
    version: Mapped[str] = mapped_column(String(64), primary_key=True)
    blob_type: Mapped[str] = mapped_column(String(32))
    # "empty" 类型的 channel 只记类型不记内容，所以这里可空。
    blob: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)


class CheckpointWriteRow(Base):
    __tablename__ = "langgraph_checkpoint_writes"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    checkpoint_ns: Mapped[str] = mapped_column(String(128), primary_key=True)
    checkpoint_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[str] = mapped_column(String(128))
    write_type: Mapped[str] = mapped_column(String(32))
    write_blob: Mapped[bytes] = mapped_column(LargeBinary)
    task_path: Mapped[str] = mapped_column(String(256), default="")


class MemoryRow(Base):
    __tablename__ = "agent_memories"
    __table_args__ = (
        Index("ix_memories_owner_active", "tenant_id", "user_id", "status"),
        Index("ix_memories_session_active", "tenant_id", "session_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner: Mapped[str] = mapped_column(String(128))
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    scope: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(64))
    content: Mapped[dict[str, str]] = mapped_column(JSON)
    content_schema: Mapped[dict[str, str]] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consent_status: Mapped[str] = mapped_column(String(16))
    edit_status: Mapped[str] = mapped_column(String(16))
    delete_status: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))


class AIPromptTemplateRow(Base):
    __tablename__ = "ai_prompt_templates"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    scene_code: Mapped[str] = mapped_column(String(64))
    prompt_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AIPromptVersionRow(Base):
    __tablename__ = "ai_prompt_versions"
    __table_args__ = (UniqueConstraint("template_id", "version", name="uq_prompt_version"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    template_id: Mapped[str] = mapped_column(ForeignKey("ai_prompt_templates.id"), index=True)
    version: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    variables_schema: Mapped[dict[str, object]] = mapped_column(JSON)
    model_config: Mapped[dict[str, object]] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(64))
    change_reason: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AIPromptReleaseRow(Base):
    __tablename__ = "ai_prompt_releases"
    __table_args__ = (
        UniqueConstraint("version_id", "environment", "tenant_id", name="uq_prompt_release_scope"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("ai_prompt_versions.id"), index=True)
    environment: Mapped[str] = mapped_column(String(32))
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    traffic_ratio: Mapped[float] = mapped_column(Numeric(5, 4))
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AIPromptRunRow(Base):
    __tablename__ = "ai_prompt_runs"
    __table_args__ = (
        Index("ix_prompt_runs_request", "request_id"),
        Index("ix_prompt_runs_version", "version_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(128), index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    template_id: Mapped[str] = mapped_column(String(64))
    version_id: Mapped[str] = mapped_column(String(64))
    release_id: Mapped[str] = mapped_column(String(64))
    variables_hash: Mapped[str] = mapped_column(String(64))
    variables_summary: Mapped[dict[str, object]] = mapped_column(JSON)
    model_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    policy_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
