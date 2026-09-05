from __future__ import annotations

import asyncio
import json
from pathlib import Path

from serviceflow.agent.model import NativeToolCallingUnavailable, OpenAICompatibleModel


TOOL = {
    "type": "function",
    "function": {
        "name": "get_order",
        "description": "查询用户订单摘要。",
        "parameters": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    },
}


async def run(output: Path | None) -> None:
    model = OpenAICompatibleModel.from_env()
    result = {
        "scope": "one_request_native_tool_call_smoke",
        "model": "deepseek-v4-flash",
        "tool_execution": False,
    }
    try:
        response = await model.complete_with_tools(
            messages=[
                {
                    "role": "system",
                    "content": "如果需要订单事实，请调用 get_order；不要输出 JSON 模拟工具调用。",
                },
                {"role": "user", "content": "帮我查询订单 ORDER-001 的状态。"},
            ],
            tools=[TOOL],
        )
        result.update(
            {
                "status": "success",
                "native_tool_call": bool(response.tool_calls),
                "tool_calls": [
                    {"name": call.name, "argument_keys": sorted(call.arguments)}
                    for call in response.tool_calls
                ],
                "response_content_present": bool(response.content),
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
            }
        )
    except NativeToolCallingUnavailable as error:
        result.update({"status": "unavailable", "error_type": type(error).__name__})
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        print(f"result_written={output}")
    else:
        print(rendered)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    asyncio.run(run(root / "experiments/results/step5-native-tool-call-live-2026-09-04.json"))


if __name__ == "__main__":
    main()
