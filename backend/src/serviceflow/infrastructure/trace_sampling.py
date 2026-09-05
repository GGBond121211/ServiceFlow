from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased


def parent_consistent_sampler(sample_ratio: float):
    if not 0.0 <= sample_ratio <= 1.0:
        raise ValueError("Trace 采样率必须在 0 到 1 之间")
    return ParentBased(TraceIdRatioBased(sample_ratio))
