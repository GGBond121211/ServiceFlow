_ALLOWED = frozenset(
    {
        "model",
        "provider",
        "route",
        "scene",
        "tool",
        "status",
        "risk_level",
        "error_class",
        "environment",
        "prompt_version",
        "index_version",
    }
)


def metric_labels(**labels: str) -> dict[str, str]:
    forbidden = set(labels) - _ALLOWED
    if forbidden:
        raise ValueError(f"Metrics 禁止高基数或敏感标签: {sorted(forbidden)}")
    return labels
