import re

_TRACEPARENT = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")


def validate_traceparent(value: str) -> str:
    if not _TRACEPARENT.fullmatch(value):
        raise ValueError("traceparent 格式无效")
    return value


def trace_id_from_traceparent(value: str) -> str:
    match = _TRACEPARENT.fullmatch(value)
    if match is None:
        raise ValueError("traceparent 格式无效")
    return match.group(1)
