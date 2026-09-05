from __future__ import annotations

import argparse
import asyncio

from serviceflow.mcp.server import MCPServer
from serviceflow.mcp.stdio import serve_stdio


class _DatabaseExecutor:
    async def execute(self, **kwargs):
        from serviceflow.api.dependencies import SessionFactory
        from serviceflow.config import get_policy_retriever
        from serviceflow.infrastructure.tool_executor import ToolExecutor

        async with SessionFactory() as session:
            executor = ToolExecutor(
                session,
                policy_retriever=get_policy_retriever(),
                tenant_id="default",
            )
            return await executor.execute(**kwargs)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fake", action="store_true")
    args = parser.parse_args()
    server = _fake_or_database_server(args.fake)
    asyncio.run(serve_stdio(server))


def _fake_or_database_server(fake: bool) -> MCPServer:
    if fake:
        from serviceflow.mcp.stdio import fake_server

        return fake_server()
    from serviceflow.agent.tool_registry import ToolRegistry

    return MCPServer(_DatabaseExecutor(), ToolRegistry.default())


if __name__ == "__main__":
    main()
