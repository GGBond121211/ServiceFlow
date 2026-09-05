from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from openai import AsyncOpenAI

from serviceflow.agent.model import OpenAICompatibleModel

TOOL = {
    "type": "function",
    "function": {
        "name": "get_order",
        "description": "查询当前用户的订单摘要。",
        "parameters": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    },
}


def _load_local_env(root: Path) -> None:
    for line in (root / ".env").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            os.environ.setdefault(name, value)


async def _probe(model_name: str) -> dict[str, object]:
    client = AsyncOpenAI(
        api_key=os.environ["SERVICEFLOW_API_KEY"],
        base_url=os.environ["SERVICEFLOW_BASE_URL"],
    )
    model = OpenAICompatibleModel(client=client, model=model_name)
    structured = await model.complete_json(
        system="只返回 JSON 对象，字段 language 和 next_action。",
        user="用户说：刚收到的耳机坏了，但没给订单号。下一步应该做什么？",
    )
    native = await model.complete_with_tools(
        messages=[
            {"role": "system", "content": "需要订单事实时必须调用工具，不要编造。"},
            {"role": "user", "content": "查询 ORDER-001 的订单状态。"},
        ],
        tools=[TOOL],
    )
    return {
        "requested_model": model_name,
        "structured_output": isinstance(structured.content, dict),
        "chinese_next_action_present": bool(structured.content.get("next_action")),
        "native_tool_calling": bool(native.tool_calls),
        "tool_names": [call.name for call in native.tool_calls],
        "response_models": [structured.model, native.model],
        "input_tokens": structured.input_tokens + native.input_tokens,
        "output_tokens": structured.output_tokens + native.output_tokens,
    }


async def run(output: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    _load_local_env(root)
    probes = []
    for model in ("deepseek-v4-flash", "gpt-5.6-luna"):
        try:
            probes.append({"status": "success", **await _probe(model)})
        except Exception as error:
            probes.append(
                {
                    "status": "failed",
                    "requested_model": model,
                    "error_type": type(error).__name__,
                }
            )
    result = {
        "run_date": "2026-09-05",
        "scope": "two_models_x_json_and_native_tool_calling",
        "provider": "Frontier Intelligence shared base URL and credential",
        "provider_independence": False,
        "price_unit": "Frontier diamond",
        "price_status": "not exposed by GET /v1/models; no cost estimate recorded",
        "probes": probes,
        "boundary": (
            "Connectivity and capability smoke only; does not prove best quality, "
            "production readiness, or independent provider disaster recovery."
        ),
    }
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    asyncio.run(
        run(root / "experiments/results/step8-frontier-model-capability-smoke-2026-09-05.json")
    )


if __name__ == "__main__":
    main()
