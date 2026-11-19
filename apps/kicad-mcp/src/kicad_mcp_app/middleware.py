"""FastMCP middleware enforcing workspace path jailing and read-only policy."""

from __future__ import annotations

from typing import Any

from fastmcp.server.middleware import Middleware, MiddlewareContext

from .security import WorkspacePathGuard, check_read_only_policy


class WorkspaceSecurityMiddleware(Middleware):
    """Applies read-only guards and workspace path validation to every MCP tool call."""

    def __init__(self, guard: WorkspacePathGuard, read_only: bool = False) -> None:
        self._guard = guard
        self._read_only = read_only

    async def on_call_tool(self, context: MiddlewareContext, call_next: Any) -> Any:
        message = context.message
        tool_name = getattr(message, "name", "")
        check_read_only_policy(tool_name, self._read_only)

        raw_args = getattr(message, "arguments", None)
        if isinstance(raw_args, dict) and raw_args:
            sanitized = self._guard.sanitize_arguments(raw_args)
            message.arguments = sanitized

        return await call_next(context)
