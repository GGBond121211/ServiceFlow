from enum import StrEnum


class AgentRole(StrEnum):
    ORDER = "order_specialist"
    SHIPMENT = "shipment_specialist"
    POLICY = "policy_specialist"
    OPERATION = "operation_specialist"
    HANDOFF = "handoff_specialist"


def role_for_tool(tool_name: str) -> AgentRole:
    if tool_name == "get_shipment":
        return AgentRole.SHIPMENT
    if tool_name in {"search_policy_evidence", "check_after_sales_eligibility"}:
        return AgentRole.POLICY
    if tool_name == "request_handoff":
        return AgentRole.HANDOFF
    if tool_name in {"get_order", "estimate_refund"}:
        return AgentRole.ORDER
    return AgentRole.OPERATION
