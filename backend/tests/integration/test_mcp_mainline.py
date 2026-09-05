import pytest

from serviceflow.agent.tool_registry import ToolRegistry
from serviceflow.infrastructure.tool_executor import ToolResult
from serviceflow.mcp.client import MCPClient
from serviceflow.mcp.host import MCPHost
from serviceflow.mcp.server import MCPServer
from serviceflow.mcp.stdio import command_for_fake_server
from serviceflow.mcp.stdio_client import StdioMCPClient


class FakeExecutor:
    async def execute(self, *, call_id, name, arguments, context):
        return ToolResult(call_id, name, True, "ok", {"echo": arguments})


@pytest.mark.asyncio
async def test_mcp_tools_list_and_tools_call_use_discovered_catalog() -> None:
    host = MCPHost(MCPClient(MCPServer(FakeExecutor(), ToolRegistry.default())))

    tools = await host.discover_tools()
    resources = await host.discover_resources()
    prompts = await host.discover_prompts()
    result = await host.call_tool(
        call_id="call-1",
        name="get_order",
        arguments={"order_id": "ORDER-001"},
        context={"user_id": "USER-001", "tenant_id": "tenant-a"},
    )

    names = {tool["function"]["name"] for tool in tools}
    assert {"get_order", "request_refund", "search_policy_evidence"} <= names
    assert result["ok"] is True
    assert result["data"] == {"echo": {"order_id": "ORDER-001"}}
    assert "approve" not in names
    assert "serviceflow://policy/current" in {item["uri"] for item in resources}
    assert "operation_planning" in {item["name"] for item in prompts}


@pytest.mark.asyncio
async def test_mcp_stdio_client_uses_a_real_child_process() -> None:
    client = StdioMCPClient(command_for_fake_server())
    try:
        tools = await client.list_tools()
        result = await client.call_tool(
            call_id="stdio-call-1",
            name="get_order",
            arguments={"order_id": "ORDER-001"},
            context={"user_id": "USER-001", "tenant_id": "tenant-a"},
        )
    finally:
        await client.close()

    assert "get_order" in {tool["function"]["name"] for tool in tools}
    assert result["data"] == {"echo": {"order_id": "ORDER-001"}}
