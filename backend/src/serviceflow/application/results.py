from dataclasses import dataclass

from serviceflow.domain.models import Approval, Order, Refund, Ticket

CaseEntity = Refund | Ticket | Approval


@dataclass(frozen=True, slots=True)
class CaseResult:
    ok: bool
    code: str
    order: Order | None = None
    case: CaseEntity | None = None
