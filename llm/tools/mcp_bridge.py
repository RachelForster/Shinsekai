"""MCP 客户端桥接：SSE 与 stdio 传输，基于官方 ``mcp`` Python SDK。"""

from __future__ import annotations

import json
import logging
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client

logger = logging.getLogger(__name__)


class MCPBridge:
    """
    包装 MCP ClientSession，并在连接时正确挂接传输层的异步上下文管理器。

    用法（协程内）::

        bridge = MCPBridge()
        await bridge.connect_sse("https://example.com/sse")
        tools = await bridge.list_tools()
        out = await bridge.call_tool(tools[0].name, {})
        await bridge.close()
    """

    def __init__(self) -> None:
        self.session: ClientSession | None = None
        self._stack: AsyncExitStack | None = None

    async def _ensure_fresh_stack(self) -> AsyncExitStack:
        await self.close()
        stack = AsyncExitStack()
        await stack.__aenter__()
        self._stack = stack
        return stack

    async def connect_sse(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """连接基于 SSE 的 MCP 服务（``headers`` 与额外参数透传给 :func:`sse_client`）。"""
        stack = await self._ensure_fresh_stack()
        try:
            transport = sse_client(url=url, headers=headers, **kwargs)
            read, write = await stack.enter_async_context(transport)
            session_cm = ClientSession(read, write)
            self.session = await stack.enter_async_context(session_cm)
            await self.session.initialize()
        except Exception:
            await self.close()
            raise

    async def connect_stdio(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        """连接本地子进程 stdio MCP 服务。"""
        stack = await self._ensure_fresh_stack()
        try:
            params = StdioServerParameters(
                command=command, args=list(args or []), env=env
            )
            transport = stdio_client(params)
            read, write = await stack.enter_async_context(transport)
            session_cm = ClientSession(read, write)
            self.session = await stack.enter_async_context(session_cm)
            await self.session.initialize()
        except Exception:
            await self.close()
            raise

    async def list_tools(self) -> list[Any]:
        if self.session is None:
            raise RuntimeError("MCPBridge is not connected")
        tools_res = await self.session.list_tools()
        return list(tools_res.tools)

    @staticmethod
    def _text_from_tool_result(result: Any) -> str:
        parts: list[str] = []
        for block in result.content or []:
            btype = getattr(block, "type", None)
            if btype == "text":
                text = getattr(block, "text", None)
                if text is not None:
                    parts.append(str(text))
        return "\n".join(parts)

    async def call_tool(self, tool_name: str, arguments: dict[str, Any] | None) -> str:
        if self.session is None:
            raise RuntimeError("MCPBridge is not connected")
        result = await self.session.call_tool(tool_name, arguments or {})
        text = MCPBridge._text_from_tool_result(result)
        if text:
            return text
        if getattr(result, "is_error", False):
            try:
                return json.dumps(
                    result.model_dump(mode="json"),
                    ensure_ascii=False,
                )
            except Exception:
                logger.exception("call_tool: failed to serialize error result")
                return str(result)
        return ""

    async def close(self) -> None:
        """关闭传输与 session，可重复调用。"""
        self.session = None
        stack = self._stack
        self._stack = None
        if stack is not None:
            try:
                await stack.__aexit__(None, None, None)
            except Exception:  # pragma: no cover - defensive cleanup
                logger.exception("MCPBridge.close")

    async def __aenter__(self) -> MCPBridge:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()
