from __future__ import annotations

from typing import Protocol


class MCPTransport(Protocol):
    async def list_tools(self) -> tuple[dict[str, object], ...]: ...

    async def call_tool(
        self,
        *,
        call_id: str,
        name: str,
        arguments: dict[str, object],
        context: dict[str, object],
    ) -> dict[str, object]: ...

    async def list_resources(self) -> tuple[dict[str, object], ...]: ...

    async def list_prompts(self) -> tuple[dict[str, object], ...]: ...


class MCPHost:
    def __init__(self, client: MCPTransport) -> None:
        self._client = client

    async def discover_tools(self) -> tuple[dict[str, object], ...]:
        return await self._client.list_tools()

    async def call_tool(
        self,
        *,
        call_id: str,
        name: str,
        arguments: dict[str, object],
        context: dict[str, object],
    ) -> dict[str, object]:
        return await self._client.call_tool(
            call_id=call_id,
            name=name,
            arguments=arguments,
            context=context,
        )

    async def discover_resources(self) -> tuple[dict[str, object], ...]:
        return await self._client.list_resources()

    async def discover_prompts(self) -> tuple[dict[str, object], ...]:
        return await self._client.list_prompts()
