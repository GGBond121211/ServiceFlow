from __future__ import annotations

from datetime import date

from serviceflow.agent.tool_registry import ToolRegistry
from serviceflow.infrastructure.tool_executor import ToolExecutionContext, ToolExecutor, ToolResult


class MCPServer:
    def __init__(self, executor: ToolExecutor, registry: ToolRegistry | None = None) -> None:
        self._executor = executor
        self._registry = registry or ToolRegistry.default()

    async def handle(self, method: str, params: dict[str, object] | None = None) -> object:
        params = params or {}
        if method == "tools/list":
            return {"tools": [item.as_openai_tool() for item in self._registry.discover()]}
        if method == "resources/list":
            return {
                "resources": [
                    {
                        "uri": "serviceflow://policy/current",
                        "name": "当前租户政策 release",
                        "description": "当前有效政策版本的脱敏索引。",
                    },
                    {
                        "uri": "serviceflow://case/schema",
                        "name": "案件与操作 schema",
                        "description": "业务案件和操作的字段说明。",
                    },
                    {
                        "uri": "serviceflow://case/status-timeline",
                        "name": "状态时间线",
                        "description": "售后案件状态的脱敏说明。",
                    },
                ]
            }
        if method == "prompts/list":
            return {
                "prompts": [
                    {"name": "intent_extraction", "description": "意图提取模板。"},
                    {"name": "policy_answer", "description": "政策证据解释模板。"},
                    {"name": "operation_planning", "description": "业务操作规划模板。"},
                ]
            }
        if method == "tools/call":
            call_id = str(params["call_id"])
            name = str(params["name"])
            arguments = params["arguments"]
            context = params["context"]
            if not isinstance(arguments, dict) or not isinstance(context, dict):
                raise ValueError("tools/call 参数格式错误")
            result = await self._executor.execute(
                call_id=call_id,
                name=name,
                arguments=arguments,
                context=ToolExecutionContext(
                    user_id=str(context["user_id"]),
                    tenant_id=str(context["tenant_id"]),
                    scene=str(context.get("scene", "after_sales")),
                    confirmed=bool(context.get("confirmed", False)),
                    approval_granted=bool(context.get("approval_granted", False)),
                    roles=tuple(str(role) for role in context.get("roles", ("customer",))),
                    session_id=_optional_text(context.get("session_id")),
                    case_id=_optional_text(context.get("case_id")),
                    trace_id=_optional_text(context.get("trace_id")),
                    reference_date=date.fromisoformat(
                        str(context.get("reference_date", "2026-08-01"))
                    ),
                ),
            )
            return _result_mapping(result)
        raise ValueError(f"未知 MCP 方法: {method}")


def _result_mapping(result: ToolResult) -> dict[str, object]:
    return {
        "tool_call_id": result.tool_call_id,
        "tool_name": result.tool_name,
        "ok": result.ok,
        "code": result.code,
        "data": result.data,
        "retryable": result.retryable,
    }


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
