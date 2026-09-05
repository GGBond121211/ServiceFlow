from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from itertools import count


class StdioMCPClient:
    def __init__(self, command: Sequence[str]) -> None:
        self._command = tuple(command)
        self._process: asyncio.subprocess.Process | None = None
        self._ids = count(1)
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._process is not None:
            return
        self._process = await asyncio.create_subprocess_exec(
            *self._command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    async def close(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        if process.stdin is not None:
            process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), timeout=2)
        except TimeoutError:
            process.kill()
            await process.wait()

    async def _request(self, method: str, params: dict[str, object] | None = None) -> object:
        await self.start()
        process = self._process
        if process is None or process.stdin is None or process.stdout is None:
            raise RuntimeError("MCP stdio 进程未启动")
        async with self._lock:
            request_id = next(self._ids)
            process.stdin.write(
                (json.dumps(
                    {"id": request_id, "method": method, "params": params or {}},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ) + "\n").encode()
            )
            await process.stdin.drain()
            line = await process.stdout.readline()
        if not line:
            raise RuntimeError("MCP stdio 进程提前退出")
        response = json.loads(line)
        if not isinstance(response, Mapping) or response.get("id") != request_id:
            raise ValueError("MCP stdio 响应 id 错误")
        if "error" in response:
            raise ValueError(f"MCP stdio 请求失败: {response['error']}")
        return response.get("result")

    async def list_tools(self) -> tuple[dict[str, object], ...]:
        response = await self._request("tools/list")
        return _list_response(response, "tools")

    async def call_tool(
        self,
        *,
        call_id: str,
        name: str,
        arguments: dict[str, object],
        context: dict[str, object],
    ) -> dict[str, object]:
        response = await self._request(
            "tools/call",
            {"call_id": call_id, "name": name, "arguments": arguments, "context": context},
        )
        if not isinstance(response, dict):
            raise ValueError("MCP stdio tools/call 响应格式错误")
        return response

    async def list_resources(self) -> tuple[dict[str, object], ...]:
        response = await self._request("resources/list")
        return _list_response(response, "resources")

    async def list_prompts(self) -> tuple[dict[str, object], ...]:
        response = await self._request("prompts/list")
        return _list_response(response, "prompts")


def _list_response(response: object, key: str) -> tuple[dict[str, object], ...]:
    if not isinstance(response, dict) or not isinstance(response.get(key), list):
        raise ValueError(f"MCP stdio {key} 响应格式错误")
    return tuple(item for item in response[key] if isinstance(item, dict))
