from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, object]
    read_only: bool
    side_effect: bool
    risk_level: str
    idempotent: bool
    requires_confirmation: bool
    requires_approval: bool
    allowed_scene: tuple[str, ...]
    timeout_seconds: float
    audit_fields: tuple[str, ...]

    def as_openai_tool(self) -> dict[str, object]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self, definitions: tuple[ToolDefinition, ...]) -> None:
        self._definitions = {definition.name: definition for definition in definitions}
        if len(self._definitions) != len(definitions):
            raise ValueError("工具名称不能重复")

    @classmethod
    def default(cls) -> ToolRegistry:
        text_id = {"type": "string", "minLength": 1}
        return cls(
            (
                _read("get_order", "查询当前用户的订单摘要。", {"order_id": text_id}),
                _read("get_shipment", "查询当前用户订单的物流摘要。", {"order_id": text_id}),
                _read("get_case", "查询售后案件状态。", {"case_id": text_id}),
                _read("get_operation_status", "查询业务操作状态。", {"operation_id": text_id}),
                _read(
                    "search_policy_evidence",
                    "搜索当前适用的政策证据，只返回可引用背景，不决定业务资格。",
                    {"query": text_id},
                ),
                _read(
                    "check_after_sales_eligibility",
                    "根据订单和确定性业务规则检查售后资格。",
                    {"order_id": text_id, "requested_action": text_id},
                ),
                _read("estimate_refund", "读取订单实付金额作为退款估算。", {"order_id": text_id}),
                _write("cancel_order", "取消已付款但尚未发货的订单。", {"order_id": text_id}),
                _write(
                    "create_return_request",
                    "创建退货咨询工单，等待人工处理。",
                    {"order_id": text_id},
                ),
                _write(
                    "create_exchange_request",
                    "申请换货；需用户明确质量问题，按确定性政策检查资格。",
                    {
                        "order_id": text_id,
                        "issue_type": {"type": "string", "enum": ["quality", "none"]},
                    },
                ),
                _write(
                    "request_refund",
                    "提出退款操作。高风险场景会要求确认或审批。",
                    {"order_id": text_id},
                ),
                _write("create_compensation_request", "提出补偿申请。", {"order_id": text_id}),
                _write(
                    "create_support_ticket",
                    "创建售后支持工单。",
                    {"order_id": text_id, "summary": text_id},
                ),
                _write("request_handoff", "请求人工接管。", {"reason": text_id}),
                _read(
                    "poll_provider_operation",
                    "查询外部操作的当前状态。",
                    {"operation_id": text_id},
                ),
            )
        )

    def discover(self) -> tuple[ToolDefinition, ...]:
        return tuple(self._definitions.values())

    def get(self, name: str) -> ToolDefinition:
        try:
            return self._definitions[name]
        except KeyError as error:
            raise KeyError(f"未知工具: {name}") from error


def _read(name: str, description: str, properties: dict[str, object]) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=description,
        parameters={"type": "object", "properties": properties, "required": list(properties)},
        read_only=True,
        side_effect=False,
        risk_level="low",
        idempotent=True,
        requires_confirmation=False,
        requires_approval=False,
        allowed_scene=("after_sales",),
        timeout_seconds=5.0,
        audit_fields=tuple(properties),
    )


def _write(name: str, description: str, properties: dict[str, object]) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=description,
        parameters={"type": "object", "properties": properties, "required": list(properties)},
        read_only=False,
        side_effect=True,
        risk_level=(
            "high" if name in {"request_refund", "create_compensation_request"} else "medium"
        ),
        idempotent=False,
        requires_confirmation=True,
        requires_approval=name in {"request_refund", "create_compensation_request"},
        allowed_scene=("after_sales",),
        timeout_seconds=10.0,
        audit_fields=tuple(properties),
    )
