from time import sleep

from serviceflow.evaluation.model_latency import (
    _parse_sse_line,
    _stream_content,
    _summarize_samples,
)
from serviceflow.evaluation.real_stress import _parse_server_timing
from serviceflow.infrastructure.timing import (
    collect_request_timings,
    measure_timing,
    server_timing_header,
    timing_snapshot,
)


def test_request_timing_collects_and_formats_accumulated_values() -> None:
    with collect_request_timings():
        with measure_timing("model_call_ms"):
            sleep(0.001)
        with measure_timing("model_call_ms"):
            sleep(0.001)

        snapshot = timing_snapshot()
        header = server_timing_header()

    assert snapshot["model_call_ms"] >= 2
    assert "model_call_ms;dur=" in header


def test_server_timing_parser_ignores_invalid_fields() -> None:
    parsed = _parse_server_timing(
        "model_call_ms;dur=123.45, database_phase_ms;dur=6.7, invalid;dur=nope"
    )

    assert parsed == {
        "model_call_ms": 123.45,
        "database_phase_ms": 6.7,
    }


def test_streaming_probe_parses_sse_content_and_summarizes_latency() -> None:
    payload = _parse_sse_line('data: {"choices":[{"delta":{"content":"{\\"order_id\\":null}"}}]}')

    assert payload is not None
    assert _stream_content(payload) == '{"order_id":null}'
    assert _parse_sse_line(": keep-alive") is None
    assert _parse_sse_line("data: [DONE]") is None

    summary = _summarize_samples(
        [
            {
                "response_headers_ms": 10.0,
                "time_to_first_token_ms": 100.0,
                "generation_ms": 50.0,
                "total_ms": 150.0,
            },
            {
                "response_headers_ms": 20.0,
                "time_to_first_token_ms": 200.0,
                "generation_ms": 60.0,
                "total_ms": 260.0,
            },
        ]
    )

    assert summary["time_to_first_token_ms"]["average"] == 150.0
    assert summary["total_ms"]["max"] == 260.0
