from serviceflow.agent.roles import AgentRole, role_for_tool
from serviceflow.agent.tool_registry import ToolRegistry
from serviceflow.infrastructure.answerability import (
    AnswerabilityAction,
    AnswerabilityGate,
)
from serviceflow.infrastructure.handoff import redact_text


def test_missing_order_asks_for_verified_identifier() -> None:
    decision = AnswerabilityGate.order(order_exists=False, authorized=True)

    assert decision.action is AnswerabilityAction.ASK_USER
    assert decision.code == "not_found"


def test_unauthorized_resource_is_refused_without_disclosure() -> None:
    decision = AnswerabilityGate.order(order_exists=True, authorized=False)

    assert decision.action is AnswerabilityAction.REFUSE
    assert decision.code == "unauthorized"


def test_missing_policy_evidence_and_unknown_provider_require_handoff() -> None:
    policy = AnswerabilityGate.policy(evidence_count=0, has_conflict=False)
    provider = AnswerabilityGate.provider("unknown")

    assert policy.action is AnswerabilityAction.HANDOFF
    assert policy.code == "policy_evidence_insufficient"
    assert provider.action is AnswerabilityAction.HANDOFF
    assert provider.code == "provider_unknown"


def test_handoff_text_redacts_email_and_phone() -> None:
    redacted = redact_text("联系 alex@example.com 或 13800138000")

    assert "alex@example.com" not in redacted
    assert "13800138000" not in redacted
    assert "[REDACTED_EMAIL]" in redacted
    assert "[REDACTED_PHONE]" in redacted


def test_role_routing_is_finite_and_every_write_tool_requires_confirmation() -> None:
    assert role_for_tool("get_shipment") is AgentRole.SHIPMENT
    assert role_for_tool("search_policy_evidence") is AgentRole.POLICY
    assert role_for_tool("request_refund") is AgentRole.OPERATION
    definitions = ToolRegistry.default().discover()

    assert all(item.requires_confirmation for item in definitions if item.side_effect)
