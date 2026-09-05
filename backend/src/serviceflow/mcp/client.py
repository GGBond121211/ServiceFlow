from __future__ import annotations

from serviceflow.mcp.server import MCPServer


class MCPClient:
    def __init__(self, server: MCPServer) -> None:
        self._server = server

    async def list_tools(self) -> tuple[dict[str, object], ...]:
        response = await self._server.handle("tools/list")
        if not isinstance(response, dict) or not isinstance(response.get("tools"), list):
            raise ValueError("MCP tools/list 响应格式错误")
        return tuple(item for item in response["tools"] if isinstance(item, dict))

    async def call_tool(
        self,
        *,
        call_id: str,
        name: str,
        arguments: dict[str, object],
        context: dict[str, object],
    ) -> dict[str, object]:
        response = await self._server.handle(
            "tools/call",
            {
                "call_id": call_id,
                "name": name,
                "arguments": arguments,
                "context": context,
            },
        )
        if not isinstance(response, dict):
            raise ValueError("MCP tools/call 响应格式错误")
        return response

    async def list_resources(self) -> tuple[dict[str, object], ...]:
        response = await self._server.handle("resources/list")
        if not isinstance(response, dict) or not isinstance(response.get("resources"), list):
            raise ValueError("MCP resources/list 响应格式错误")
        return tuple(item for item in response["resources"] if isinstance(item, dict))

    async def list_prompts(self) -> tuple[dict[str, object], ...]:
        response = await self._server.handle("prompts/list")
        if not isinstance(response, dict) or not isinstance(response.get("prompts"), list):
            raise ValueError("MCP prompts/list 响应格式错误")
        return tuple(item for item in response["prompts"] if isinstance(item, dict))
