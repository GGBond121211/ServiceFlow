from enum import StrEnum


class GatewayErrorClass(StrEnum):
    RATE_LIMIT = "rate_limit"
    SERVER_ERROR = "server_error"
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    INVALID_RESPONSE = "invalid_response"
    BAD_REQUEST = "bad_request"
    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    POLICY = "policy"
    SAFETY = "safety"
    CONFIRMATION = "confirmation"
    APPROVAL = "approval"
    IDEMPOTENCY = "idempotency"
    BUSINESS_VALIDATION = "business_validation"
    CAPABILITY = "capability"
    DEADLINE = "deadline"
    QUOTA = "quota"
    CIRCUIT_OPEN = "circuit_open"
    BACKPRESSURE = "backpressure"

    @property
    def fallback_allowed(self) -> bool:
        return self in {
            GatewayErrorClass.RATE_LIMIT,
            GatewayErrorClass.SERVER_ERROR,
            GatewayErrorClass.TIMEOUT,
            GatewayErrorClass.CONNECTION,
            GatewayErrorClass.INVALID_RESPONSE,
        }


class GatewayFailure(Exception):
    def __init__(
        self,
        error_class: GatewayErrorClass,
        message: str,
        *,
        manual_required: bool = False,
    ) -> None:
        super().__init__(message)
        self.error_class = error_class
        self.manual_required = manual_required
