from datetime import date

from serviceflow.domain.policy_documents import PolicyDocument


def document(**overrides: object) -> PolicyDocument:
    values: dict[str, object] = {
        "policy_id": "POL-1",
        "version": "v1",
        "title": "退款规则",
        "content": "签收后七日内可以申请退货",
        "tenant_id": None,
        "region": "CN",
        "effective_from": "2026-01-01",
        "effective_to": None,
        "source_type": "regulation",
        "source_title": "官方法规",
        "source_url": "https://example.test/policy",
        "source_locator": "第二条",
    }
    values.update(overrides)
    return PolicyDocument.from_mapping(values)


def test_policy_document_requires_current_scope_and_calculates_source_hash() -> None:
    current = document()

    assert current.applies_to(tenant_id="tenant-a", region="CN", at=date(2026, 8, 1))
    assert current.source_hash
    assert not current.applies_to(tenant_id="tenant-a", region="US", at=date(2026, 8, 1))
    assert not current.applies_to(tenant_id="tenant-a", region="CN", at=date(2025, 12, 31))


def test_expired_policy_is_not_current() -> None:
    expired = document(effective_to="2026-06-30")

    assert not expired.applies_to(tenant_id="tenant-a", region="CN", at=date(2026, 8, 1))
