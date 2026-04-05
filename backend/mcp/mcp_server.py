from __future__ import annotations

from typing import Any, Awaitable, Callable

from core.exceptions import MCPToolError
from mcp.tools.citation_tool import citation_tool
from mcp.tools.search_tool import search_tool

ToolHandler = Callable[[dict[str, Any]], Any | Awaitable[Any]]


class MCPServer:
    def __init__(self):
        self._tools: dict[str, ToolHandler] = {}

    def register_tool(self, name: str, handler: ToolHandler) -> None:
        self._tools[name] = handler

    async def call_tool(self, name: str, payload: dict[str, Any]) -> Any:
        handler = self._tools.get(name)
        if handler is None:
            raise MCPToolError(name)

        try:
            result = handler(payload)
            if hasattr(result, "__await__"):
                return await result
            return result
        except MCPToolError:
            raise
        except Exception as exc:
            raise MCPToolError(name) from exc


def build_default_mcp_server() -> MCPServer:
    server = MCPServer()
    server.register_tool("search_tool", search_tool)
    server.register_tool("citation_tool", citation_tool)
    return server
