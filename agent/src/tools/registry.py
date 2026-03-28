"""
Tool registry: unified source-of-truth for all tool definitions and
the routing layer for tool invocations.

Currently backed by MCP; can be extended with native Python tools.
"""

from __future__ import annotations

import logging
from typing import Any

from .base import ToolDefinition, ToolCall, ToolResult
from .mcp_client import MCPManager

logger = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self, mcp_manager: MCPManager) -> None:
        self._mcp = mcp_manager

    # ------------------------------------------------------------------
    # Definitions (OpenAI format)
    # ------------------------------------------------------------------

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return tool definitions in OpenAI /v1/chat/completions format."""
        defs = [t.model_dump() for t in self._mcp.list_tools()]
        logger.debug("Returning %d tool definition(s)", len(defs))
        return defs

    # ------------------------------------------------------------------
    # Invocation
    # ------------------------------------------------------------------

    async def call(self, tool_call: ToolCall) -> ToolResult:
        """Dispatch a tool call and return the result."""
        args_preview = tool_call.arguments[:120] + ("…" if len(tool_call.arguments) > 120 else "")
        logger.info("Executing tool: %s(%s)", tool_call.name, args_preview)
        if self._mcp.has_tool(tool_call.name):
            result = await self._mcp.call_tool(tool_call)
        else:
            logger.warning("Unknown tool requested: '%s'", tool_call.name)
            result = ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=f"[error] Unknown tool '{tool_call.name}'",
            )
        content_preview = result.content[:200] + ("…" if len(result.content) > 200 else "")
        logger.info("Tool '%s' result: %s", tool_call.name, content_preview)
        return result

    async def call_all(self, tool_calls: list[ToolCall]) -> list[ToolResult]:
        """Execute multiple tool calls concurrently."""
        import asyncio
        results = list(await asyncio.gather(*[self.call(tc) for tc in tool_calls]))
        logger.debug(
            "Executed %d tool call(s) concurrently",
            len(results),
        )
        return results
