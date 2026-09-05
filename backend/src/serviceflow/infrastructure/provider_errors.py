from enum import StrEnum


class ProviderErrorClass(StrEnum):
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    SERVER_ERROR = "server_error"
    AUTHENTICATION = "authentication"
    VALIDATION = "validation"
    POLICY = "policy"
    PERMISSION = "permission"
    SAFETY = "safety"

    @property
    def retryable(self) -> bool:
        return self in {
            ProviderErrorClass.TIMEOUT,
            ProviderErrorClass.RATE_LIMIT,
            ProviderErrorClass.SERVER_ERROR,
        }


class ProviderFailure(Exception):
    def __init__(
        self,
        error_class: ProviderErrorClass,
        message: str,
        *,
        outcome_unknown: bool = False,
    ) -> None:
        super().__init__(message)
        self.error_class = error_class
        self.outcome_unknown = outcome_unknown
