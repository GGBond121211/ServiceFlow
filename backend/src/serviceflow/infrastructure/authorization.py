from dataclasses import dataclass

from serviceflow.domain.cases import AfterSalesCase
from serviceflow.domain.models import Order


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: str
    tenant_id: str
    roles: tuple[str, ...] = ("customer",)


class Authorization:
    def __init__(self, tenant_id: str) -> None:
        self._tenant_id = tenant_id

    def tenant_allowed(self, principal: Principal) -> bool:
        return bool(principal.user_id) and principal.tenant_id == self._tenant_id

    def order_allowed(self, principal: Principal, order: Order) -> bool:
        return self.tenant_allowed(principal) and order.user_id == principal.user_id

    def case_allowed(self, principal: Principal, case: AfterSalesCase) -> bool:
        return (
            self.tenant_allowed(principal)
            and case.tenant_id == principal.tenant_id
            and case.user_id == principal.user_id
        )

    def can_approve(self, principal: Principal) -> bool:
        return self.tenant_allowed(principal) and "approver" in principal.roles
