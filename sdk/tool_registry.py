"""
LLM 可调用工具的声明式注册（与 :class:`~llm.tools.tool_manager.ToolManager` 解耦）。

开发者只需 ``from sdk.tool_registry import tool`` 并对函数使用 ``@tool``（可选 ``name=`` / ``description=``）；
所有被装饰的函数进入进程内全局列表，由宿主在启动时调用 :func:`apply_registered_tools` 一次性注册到
单例 :class:`~llm.tools.tool_manager.ToolManager`（见 :func:`core.plugins.plugin_host.ensure_plugins_loaded`）。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from llm.tools.tool_manager import ToolManager

F = TypeVar("F", bound=Callable[..., Any])


class ToolNotReady(Exception):
    """工具所需的模型 / 资源尚未就绪，正在后台加载。

    工具函数直接 ``raise ToolNotReady("正在加载...")``，
    由 :class:`~llm.tools.tool_executor.ToolExecutor` 统一捕获，
    转为 ``{"status":"loading","message":"..."}`` 响应并设置冷却期。

    用法::

        from sdk.tool_registry import tool, ToolNotReady

        @tool(name="my_tool", group="vision")
        def my_tool(...):
            if not tool_ready():
                start_loading()
                raise ToolNotReady("视觉模型正在加载，请稍候…")
            ...
    """

    def __init__(self, message: str = "") -> None:
        super().__init__(message)
        self.message = message


# (callable, name_override | None, description_override | None, group | None, risk | None)
_Entries: list[tuple[Callable[..., Any], str | None, str | None, str | None, str | None]] = []


def tool(
    func: F | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    group: str | None = None,
    risk: str = "low",
) -> F | Callable[[F], F]:
    """
    将函数登记到全局表，供宿主注入 ToolManager。

    - ``@tool`` 或 ``@tool()``：使用函数名与 docstring。
    - ``@tool(name=..., description=...)``：覆盖对外暴露的名称与说明。
    - ``group``：工具分组，默认 "default"。
    - ``risk``：风险等级 "low" / "medium" / "high"，默认 "low"。
    """

    def _decorator(fn: F) -> F:
        _Entries.append((fn, name, description, group or "default", risk or "low"))
        return fn

    if func is None:
        return _decorator
    return _decorator(func)


def iter_registered_tools() -> Iterator[tuple[Callable[..., Any], str | None, str | None, str | None, str | None]]:
    """只读遍历已登记的 ``(func, name, description, group, risk)``（注册顺序）。"""
    yield from tuple(_Entries)


def registered_tool_entries() -> Sequence[tuple[Callable[..., Any], str | None, str | None, str | None, str | None]]:
    """返回当前登记快照。"""
    return tuple(_Entries)


def apply_registered_tools(tool_manager: ToolManager) -> None:
    """
    将 :func:`tool` 收集到的函数注册到 ``tool_manager``。
    """
    for fn, nm, desc, group, risk in _Entries:
        tool_manager.register_function(fn, name=nm, description=desc, group=group, risk=risk)


# ── 模型就绪通知（插件 → 宿主）──────────────────────────────────────────

_on_tool_ready: Callable[[str, str], None] | None = None


def set_tool_ready_callback(cb: Callable[[str, str], None]) -> None:
    """宿主在启动时调用，注入模型就绪的处理逻辑（清除冷却、推送聊天通知等）。"""
    global _on_tool_ready
    _on_tool_ready = cb


def notify_tool_ready(group: str, message: str = "") -> None:
    """插件在模型后台加载完成后调用。

    宿主收到后通常会：
    - 清除该 ``group`` 的冷却期
    - 向聊天 UI 推送一条系统通知
    """
    if _on_tool_ready is not None:
        _on_tool_ready(group, message)
