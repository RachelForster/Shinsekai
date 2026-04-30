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

# (callable, openapi_name_override | None, description_override | None)
_Entries: list[tuple[Callable[..., Any], str | None, str | None]] = []


def tool(
    func: F | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
) -> F | Callable[[F], F]:
    """
    将函数登记到全局表，供宿主注入 ToolManager。

    - ``@tool`` 或 ``@tool()``：使用函数名与 docstring。
    - ``@tool(name="my_tool", description="...")``：覆盖对外暴露的名称与说明。
    """

    def _decorator(fn: F) -> F:
        _Entries.append((fn, name, description))
        return fn

    if func is None:
        return _decorator
    return _decorator(func)


def iter_registered_tools() -> Iterator[tuple[Callable[..., Any], str | None, str | None]]:
    """只读遍历已登记的 ``(func, name_override, description_override)``（注册顺序）。"""
    yield from tuple(_Entries)


def registered_tool_entries() -> Sequence[tuple[Callable[..., Any], str | None, str | None]]:
    """返回当前登记快照（元组，避免调用方误改内部列表）。"""
    return tuple(_Entries)


def apply_registered_tools(tool_manager: ToolManager) -> None:
    """
    将 :func:`tool` 收集到的函数注册到 ``tool_manager``。

    应在插件 ``register_llm_tool`` 回调执行之前调用，以便插件仍可通过回调追加工具。
    重复的工具名以后注册者为准（:meth:`ToolManager.register_function` 会先移除同名项）。
    """
    for fn, nm, desc in _Entries:
        tool_manager.register_function(fn, name=nm, description=desc)
