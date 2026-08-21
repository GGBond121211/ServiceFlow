"""直连模型 API，测量响应头、首 Token 和完整生成耗时。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

import httpx

from serviceflow.agent.intent import PROMPT_PATH

DEFAULT_MESSAGE = "ORDER-001 还没发货，帮我取消"
DEFAULT_OUTPUT_DIR = Path(__file__).parents[4] / "outputs" / "evaluation"


async def run_model_latency_probe(
    *,
    base_url: str,
    api_key: str,
    model: str,
    message: str = DEFAULT_MESSAGE,
    iterations: int = 5,
    concurrency: int = 1,
    thinking_mode: str | None = None,
    reasoning_effort: str | None = None,
) -> dict[str, object]:
    if iterations < 1:
        raise ValueError("iterations 必须大于等于 1")
    if concurrency < 1:
        raise ValueError("concurrency 必须大于等于 1")

    endpoint = f"{base_url.rstrip('/')}/chat/completions"
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    semaphore = asyncio.Semaphore(concurrency)
    timeout = httpx.Timeout(180.0, connect=30.0, pool=180.0)
    limits = httpx.Limits(
        max_connections=max(20, concurrency + 5),
        max_keepalive_connections=max(10, concurrency),
    )

    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        tasks = []
        for iteration in range(iterations):
            tasks.append(
                _probe_once(
                    client=client,
                    semaphore=semaphore,
                    endpoint=endpoint,
                    api_key=api_key,
                    model=model,
                    prompt=prompt,
                    message=message,
                    iteration=iteration,
                    thinking_mode=thinking_mode,
                    reasoning_effort=reasoning_effort,
                )
            )
        samples = await asyncio.gather(*tasks)

    successful_samples = []
    for sample in samples:
        if sample.get("error") is None:
            successful_samples.append(sample)

    return {
        "run_at": datetime.now(UTC).isoformat(),
        "base_url": base_url,
        "model": model,
        "iterations": iterations,
        "concurrency": concurrency,
        "message": message,
        "thinking_mode": thinking_mode,
        "reasoning_effort": reasoning_effort,
        "successful": len(successful_samples),
        "failed": len(samples) - len(successful_samples),
        "summary_ms": _summarize_samples(successful_samples),
        "samples": samples,
    }


async def _probe_once(
    *,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    endpoint: str,
    api_key: str,
    model: str,
    prompt: str,
    message: str,
    iteration: int,
    thinking_mode: str | None,
    reasoning_effort: str | None,
) -> dict[str, object]:
    async with semaphore:
        started_at = perf_counter()
        first_token_ms: float | None = None
        response_headers_ms: float | None = None
        content_parts = []
        usage: dict[str, object] = {}
        error = None
        status_code = None
        try:
            request_body: dict[str, object] = {
                "model": model,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": message},
                ],
                "response_format": {"type": "json_object"},
                "stream": True,
                "stream_options": {"include_usage": True},
            }
            if thinking_mode is not None:
                request_body["thinking"] = {"type": thinking_mode}
            if reasoning_effort is not None:
                request_body["reasoning_effort"] = reasoning_effort
            async with client.stream(
                "POST",
                endpoint,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body,
            ) as response:
                status_code = response.status_code
                response_headers_ms = (perf_counter() - started_at) * 1000
                response.raise_for_status()
                async for line in response.aiter_lines():
                    payload = _parse_sse_line(line)
                    if payload is None:
                        continue
                    chunk_usage = payload.get("usage")
                    if isinstance(chunk_usage, dict):
                        usage = chunk_usage
                    content = _stream_content(payload)
                    if content:
                        if first_token_ms is None:
                            first_token_ms = (perf_counter() - started_at) * 1000
                        content_parts.append(content)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        total_ms = (perf_counter() - started_at) * 1000
        generation_ms = None
        if first_token_ms is not None:
            generation_ms = max(total_ms - first_token_ms, 0.0)
        return {
            "iteration": iteration,
            "status_code": status_code,
            "response_headers_ms": _round_optional(response_headers_ms),
            "time_to_first_token_ms": _round_optional(first_token_ms),
            "generation_ms": _round_optional(generation_ms),
            "total_ms": round(total_ms, 2),
            "content_characters": len("".join(content_parts)),
            "prompt_tokens": _usage_int(usage, "prompt_tokens"),
            "completion_tokens": _usage_int(usage, "completion_tokens"),
            "prompt_cache_hit_tokens": _usage_int(usage, "prompt_cache_hit_tokens"),
            "prompt_cache_miss_tokens": _usage_int(usage, "prompt_cache_miss_tokens"),
            "error": error,
        }


def _parse_sse_line(line: str) -> dict[str, object] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith(":") or not stripped.startswith("data:"):
        return None
    data = stripped.removeprefix("data:").strip()
    if not data or data == "[DONE]":
        return None
    parsed = json.loads(data)
    if not isinstance(parsed, dict):
        return None
    return parsed


def _stream_content(payload: dict[str, object]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    choice = choices[0]
    if not isinstance(choice, dict):
        return ""
    delta = choice.get("delta")
    if not isinstance(delta, dict):
        return ""
    content = delta.get("content")
    if not isinstance(content, str):
        return ""
    return content


def _usage_int(usage: dict[str, object], name: str) -> int:
    value = usage.get(name, 0)
    if isinstance(value, int):
        return value
    return 0


def _round_optional(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 2)


def _summarize_samples(samples: list[dict[str, object]]) -> dict[str, dict[str, float]]:
    names = (
        "response_headers_ms",
        "time_to_first_token_ms",
        "generation_ms",
        "total_ms",
    )
    summary: dict[str, dict[str, float]] = {}
    for name in names:
        values = []
        for sample in samples:
            value = sample.get(name)
            if isinstance(value, int | float):
                values.append(float(value))
        if not values:
            continue
        summary[name] = {
            "average": round(sum(values) / len(values), 2),
            "p50": round(_percentile(values, 50), 2),
            "p95": round(_percentile(values, 95), 2),
            "max": round(max(values), 2),
        }
    return summary


def _percentile(values: list[float], percentile: int) -> float:
    ordered = sorted(values)
    rank = int((percentile / 100) * len(ordered))
    rank = max(1, min(rank, len(ordered)))
    return ordered[rank - 1]


def write_model_latency_outputs(
    report: dict[str, object],
    output_dir: Path,
    stem: str,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{stem}.json"
    markdown_path = output_dir / f"{stem}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_markdown_report(report), encoding="utf-8")
    return json_path, markdown_path


def _markdown_report(report: dict[str, object]) -> str:
    lines = [
        "# ServiceFlow 模型流式延迟探针",
        "",
        f"- 运行时间：`{report['run_at']}`",
        f"- Base URL：`{report['base_url']}`",
        f"- 模型：`{report['model']}`",
        f"- 思考模式：`{report['thinking_mode']}`",
        f"- 思考强度：`{report['reasoning_effort']}`",
        f"- 请求数：`{report['iterations']}`",
        f"- 并发数：`{report['concurrency']}`",
        f"- 成功/失败：`{report['successful']}/{report['failed']}`",
        "",
        "| 指标 | 平均 ms | P50 ms | P95 ms | 最大 ms |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    labels = {
        "response_headers_ms": "收到响应头",
        "time_to_first_token_ms": "首 Token（TTFT）",
        "generation_ms": "首 Token 后生成",
        "total_ms": "完整响应",
    }
    summary = report.get("summary_ms", {})
    if isinstance(summary, dict):
        for name, label in labels.items():
            values = summary.get(name)
            if not isinstance(values, dict):
                continue
            lines.append(
                f"| {label} | {values.get('average')} | {values.get('p50')} | "
                f"{values.get('p95')} | {values.get('max')} |"
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="测量模型响应头、首 Token 和完整生成耗时")
    parser.add_argument("--base-url", default=os.getenv("SERVICEFLOW_BASE_URL"))
    parser.add_argument("--api-key", default=os.getenv("SERVICEFLOW_API_KEY"))
    parser.add_argument("--model", default=os.getenv("SERVICEFLOW_MODEL"))
    parser.add_argument(
        "--thinking-mode",
        choices=("enabled", "disabled"),
        default=os.getenv("SERVICEFLOW_THINKING_MODE"),
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=("low", "high", "max"),
        default=os.getenv("SERVICEFLOW_REASONING_EFFORT") or None,
    )
    parser.add_argument("--message", default=DEFAULT_MESSAGE)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--output-stem", default="serviceflow-model-latency")
    args = parser.parse_args()

    missing = []
    for name, value in (
        ("SERVICEFLOW_BASE_URL", args.base_url),
        ("SERVICEFLOW_API_KEY", args.api_key),
        ("SERVICEFLOW_MODEL", args.model),
    ):
        if not value:
            missing.append(name)
    if missing:
        raise SystemExit(f"模型配置缺失：{', '.join(missing)}")

    report = asyncio.run(
        run_model_latency_probe(
            base_url=args.base_url,
            api_key=args.api_key,
            model=args.model,
            message=args.message,
            iterations=args.iterations,
            concurrency=args.concurrency,
            thinking_mode=args.thinking_mode,
            reasoning_effort=args.reasoning_effort,
        )
    )
    json_path, markdown_path = write_model_latency_outputs(
        report,
        args.output,
        args.output_stem,
    )
    print(
        json.dumps(
            {"results": str(json_path), "report": str(markdown_path)},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
