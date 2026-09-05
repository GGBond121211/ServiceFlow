from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Sequence
from typing import Any

from serviceflow.mcp.server import MCPServer


async def serve_stdio(server: MCPServer) -> None:
    while True:
        line = await asyncio.to_thread(sys.stdin.buffer.readline)
        if not line:
            return
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("request must be an object")
            request_id = request.get("id")
            method = request.get("method")
            params = request.get("params")
            if not isinstance(method, str) or not isinstance(params, (dict, type(None))):
                raise ValueError("invalid request")
            result = await server.handle(method, params)
            response = {"id": request_id, "result": result}
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            response = {"id": locals().get("request_id"), "error": str(error)}
        payload = json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n"
        sys.stdout.buffer.write(payload.encode("utf-8"))
        sys.stdout.buffer.flush()


class EchoExecutor:
    async def execute(
        self,
        *,
        call_id: str,
        name: str,
        arguments: dict[str, object],
        context: Any,
    ) -> Any:
        from serviceflow.infrastructure.tool_executor import ToolResult

        return ToolResult(call_id, name, True, "ok", {"echo": arguments})


def fake_server() -> MCPServer:
    from serviceflow.agent.tool_registry import ToolRegistry

    return MCPServer(EchoExecutor(), ToolRegistry.default())


def command_for_fake_server() -> Sequence[str]:
    return (sys.executable, "-m", "serviceflow.mcp.stdio_server", "--fake")
