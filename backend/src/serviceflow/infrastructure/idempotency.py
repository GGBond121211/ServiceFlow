from hashlib import sha256


def stable_action_id(*, request_id: str, operation: str, subject_id: str) -> str:
    if not request_id or not operation or not subject_id:
        raise ValueError("幂等键组成字段不能为空")
    source = f"{request_id}\x1f{operation}\x1f{subject_id}"
    return f"ACT-{sha256(source.encode('utf-8')).hexdigest()[:32].upper()}"
