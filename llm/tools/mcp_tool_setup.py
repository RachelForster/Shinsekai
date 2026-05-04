"""从 ``data/config/mcp.yaml`` 连接 MCP 服务，并把工具注册到 :class:`~llm.tools.tool_manager.ToolManager`。

LLM 通过 :meth:`~llm.tools.tool_manager.ToolManager.execute` 同步调用工具，故在独立线程中运行
``MCPBridge`` 所属的事件循环，并用 :func:`asyncio.run_coroutine_threadsafe` 转发 ``call_tool``。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import concurrent.futures
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any, TypeVar

from llm.tools.mcp_config_file import (
    DEFAULT_MCP_CONFIG_PATH as _DEFAULT_CONFIG_PATH,
    read_mcp_config,
)
from llm.tools.tool_manager import ToolManager

logger = logging.getLogger(__name__)

T = TypeVar("T")

_registered_mcp_full_names: list[str] = []

_mcp_loop: asyncio.AbstractEventLoop | None = None
_mcp_thread: threading.Thread | None = None
_loop_lock = threading.Lock()
_active_bridges: list[Any] = []

# MCPBridge 使用 AsyncExitStack + mcp SSE 内部的 anyio TaskGroup；CancelScope 必须在「进入时的同一
# asyncio 任务」里退出。注册结束后若用 run_coroutine_threadsafe 再起新任务去 close，会触发
# 「Attempted to exit cancel scope in a different task than it was entered in」。因此所有长生命周期
# 连接的建立与关闭都派发到下面这个专用 owner 任务上顺序执行。
_mcp_owner_queue: asyncio.Queue[
    tuple[Callable[[], Coroutine[Any, Any, Any]], concurrent.futures.Future[Any]]
] | None = None
_mcp_owner_task: asyncio.Task[None] | None = None
_owner_lock = threading.Lock()


def _ensure_mcp_loop() -> asyncio.AbstractEventLoop:
    global _mcp_loop, _mcp_thread
    with _loop_lock:
        if _mcp_loop is not None and _mcp_loop.is_running():
            return _mcp_loop

        ready = threading.Event()
        err: list[BaseException] = []

        def _runner() -> None:
            global _mcp_loop
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                _mcp_loop = loop
                ready.set()
                loop.run_forever()
            except BaseException as e:
                err.append(e)
                ready.set()

        t = threading.Thread(target=_runner, name="mcp-asyncio", daemon=True)
        _mcp_thread = t
        t.start()
        ready.wait(timeout=30.0)
        if err:
            raise err[0]
        if _mcp_loop is None:
            raise RuntimeError("MCP event loop failed to start")
        return _mcp_loop


def run_mcp_coro(coro: Coroutine[Any, Any, T], *, timeout: float = 300.0) -> T:
    """在 MCP 专用线程的事件循环上运行协程（供同步代码调用）。"""
    loop = _ensure_mcp_loop()
    fut = asyncio.run_coroutine_threadsafe(coro, loop)
    return fut.result(timeout=timeout)


async def _mcp_owner_worker() -> None:
    assert _mcp_owner_queue is not None
    while True:
        make_coro, cfut = await _mcp_owner_queue.get()
        try:
            val = await make_coro()
            if not cfut.done():
                cfut.set_result(val)
        except BaseException as e:
            if not cfut.done():
                cfut.set_exception(e)


def _ensure_mcp_owner_worker(loop: asyncio.AbstractEventLoop) -> None:
    global _mcp_owner_queue, _mcp_owner_task
    with _owner_lock:
        if _mcp_owner_task is not None and not _mcp_owner_task.done():
            return

        async def _bootstrap() -> None:
            global _mcp_owner_queue, _mcp_owner_task
            _mcp_owner_queue = asyncio.Queue()
            _mcp_owner_task = asyncio.create_task(_mcp_owner_worker())

        # create_task 必须在 loop 线程里执行
        asyncio.run_coroutine_threadsafe(_bootstrap(), loop).result(timeout=30.0)


def run_mcp_coro_on_bridge_owner(
    make_coro: Callable[[], Coroutine[Any, Any, T]],
    *,
    timeout: float = 300.0,
) -> T:
    """在「长连接 owner」任务上运行协程：与 MCPBridge 的 connect/close 成对，避免 anyio cancel scope 跨任务。"""
    loop = _ensure_mcp_loop()
    _ensure_mcp_owner_worker(loop)
    assert _mcp_owner_queue is not None
    cfut: concurrent.futures.Future[T] = concurrent.futures.Future()

    async def _enqueue() -> None:
        await _mcp_owner_queue.put((make_coro, cfut))

    asyncio.run_coroutine_threadsafe(_enqueue(), loop).result(
        timeout=min(60.0, max(1.0, timeout))
    )
    return cfut.result(timeout=timeout)


def _mcp_tool_to_dict(tool_obj: Any) -> dict[str, Any]:
    if isinstance(tool_obj, dict):
        return dict(tool_obj)
    md = getattr(tool_obj, "model_dump", None)
    if callable(md):
        d = md(mode="json", by_alias=True)
        if isinstance(d, dict):
            return d
    name = getattr(tool_obj, "name", None)
    if not isinstance(name, str):
        raise TypeError(f"Cannot serialize MCP tool: {tool_obj!r}")
    desc = getattr(tool_obj, "description", None) or ""
    schema = getattr(tool_obj, "inputSchema", None)
    if schema is None:
        schema = getattr(tool_obj, "input_schema", None)
    out: dict[str, Any] = {"name": name, "description": str(desc) if desc else ""}
    if schema is not None:
        if hasattr(schema, "model_dump"):
            out["inputSchema"] = schema.model_dump(mode="json", by_alias=True)
        elif isinstance(schema, dict):
            out["inputSchema"] = schema
    return out


def _normalize_env(raw: Any) -> dict[str, str] | None:
    if not raw or not isinstance(raw, dict):
        return None
    return {str(k): str(v) for k, v in raw.items()}


async def _async_close_all_bridges() -> None:
    # 后进先关，减轻 anyio CancelScope 在首条连接 teardown 后的栈错位；中间让出事件循环。
    for b in reversed(list(_active_bridges)):
        try:
            await b.close()
        except Exception:
            logger.exception("MCP bridge close")
        await asyncio.sleep(0)
    _active_bridges.clear()


def close_all_mcp_bridges_sync(*, timeout: float = 60.0) -> None:
    if not _active_bridges:
        return
    try:

        def _make_close() -> Coroutine[Any, Any, None]:
            return _async_close_all_bridges()

        run_mcp_coro_on_bridge_owner(_make_close, timeout=timeout)
    except Exception:
        logger.exception("close_all_mcp_bridges_sync")


async def _async_probe_tools(servers: list[Any]) -> list[dict[str, Any]]:
    from llm.tools.mcp_bridge import MCPBridge

    out: list[dict[str, Any]] = []
    for entry in servers:
        if not isinstance(entry, dict) or entry.get("enabled") is False:
            continue
        name_prefix = str(entry.get("name_prefix") or "").strip()
        transport = str(entry.get("transport") or "").strip().lower()
        bridge = None
        try:
            if transport == "sse":
                url = str(entry.get("url") or "").strip()
                if not url:
                    continue
                headers = entry.get("headers")
                if headers is not None and not isinstance(headers, dict):
                    headers = None
                bridge = MCPBridge()
                await bridge.connect_sse(url, headers)
            elif transport == "stdio":
                command = str(entry.get("command") or "").strip()
                if not command:
                    continue
                args_raw = entry.get("args")
                args = [str(x) for x in args_raw] if isinstance(args_raw, list) else []
                env = _normalize_env(entry.get("env"))
                bridge = MCPBridge()
                await bridge.connect_stdio(command, args, env)
            else:
                continue
            for t in await bridge.list_tools():
                try:
                    d = _mcp_tool_to_dict(t)
                except Exception:
                    continue
                n = d.get("name")
                if not isinstance(n, str) or not n.strip():
                    continue
                short = n.strip()
                reg = f"{name_prefix}{short}" if name_prefix else short
                out.append(
                    {
                        "prefix": name_prefix,
                        "registered_name": reg,
                        "name": short,
                        "description": str(d.get("description") or ""),
                    }
                )
        except Exception:
            logger.exception("MCP probe failed for transport=%s", transport)
        finally:
            if bridge is not None:
                try:
                    await bridge.close()
                except Exception:
                    logger.exception("MCP probe bridge close")

    return out


def preview_mcp_tools_from_config(
    path: Path | None = None,
    *,
    timeout: float = 300.0,
) -> list[dict[str, Any]]:
    p = path or _DEFAULT_CONFIG_PATH
    cfg = read_mcp_config(p)
    if cfg.get("enabled") is False:
        return []
    servers = cfg.get("servers") or []
    if not isinstance(servers, list) or not servers:
        return []
    return run_mcp_coro(_async_probe_tools(servers), timeout=timeout)


async def _register_one_server(
    tm: ToolManager,
    entry: dict[str, Any],
    *,
    default_timeout: float,
) -> None:
    from llm.tools.mcp_bridge import MCPBridge

    if entry.get("enabled") is False:
        return
    transport = str(entry.get("transport") or "").strip().lower()
    name_prefix = str(entry.get("name_prefix") or "").strip()
    timeout = float(entry.get("call_timeout", default_timeout))

    bridge = MCPBridge()
    if transport == "sse":
        url = str(entry.get("url") or "").strip()
        if not url:
            raise ValueError("MCP sse server missing 'url'")
        headers = entry.get("headers")
        if headers is not None and not isinstance(headers, dict):
            headers = None
        await bridge.connect_sse(url, headers)
    elif transport == "stdio":
        command = str(entry.get("command") or "").strip()
        if not command:
            raise ValueError("MCP stdio server missing 'command'")
        args_raw = entry.get("args")
        args = [str(x) for x in args_raw] if isinstance(args_raw, list) else []
        env = _normalize_env(entry.get("env"))
        await bridge.connect_stdio(command, args, env)
    else:
        raise ValueError(f"Unknown MCP transport: {transport!r}")

    tools_raw = await bridge.list_tools()
    tool_dicts: list[dict[str, Any]] = []
    for t in tools_raw:
        try:
            tool_dicts.append(_mcp_tool_to_dict(t))
        except Exception:
            logger.exception("Skip MCP tool (serialize failed): %r", t)

    _active_bridges.append(bridge)

    def _invoke(registered_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name_prefix and not registered_name.startswith(name_prefix):
            raise ValueError(
                f"Tool {registered_name!r} does not match prefix {name_prefix!r}"
            )
        short = registered_name[len(name_prefix) :] if name_prefix else registered_name

        def _make_call() -> Coroutine[Any, Any, str]:
            async def _do() -> str:
                return await bridge.call_tool(short, arguments or {})

            return _do()

        try:
            text = run_mcp_coro_on_bridge_owner(_make_call, timeout=timeout)
        except Exception as exc:
            logger.exception("MCP call_tool failed: %s", short)
            return {"error": str(exc), "tool": short}
        return {"result": text}

    tm.register_mcp_tools(
        tool_dicts,
        invoke=_invoke,
        name_prefix=name_prefix,
    )
    for td in tool_dicts:
        n = td.get("name")
        if isinstance(n, str) and n.strip():
            _registered_mcp_full_names.append(f"{name_prefix}{n.strip()}")
    logger.info(
        "Registered %d MCP tools (transport=%s, prefix=%r)",
        len(tool_dicts),
        transport,
        name_prefix,
    )


def register_mcp_tools_from_config(
    tm: ToolManager,
    config_path: Path | None = None,
) -> None:
    path = config_path or _DEFAULT_CONFIG_PATH
    if not path.is_file():
        logger.debug("MCP config not found: %s", path)
        return
    cfg = read_mcp_config(path)
    if cfg.get("enabled") is False:
        return

    servers = cfg.get("servers")
    if not isinstance(servers, list) or not servers:
        logger.debug("MCP config has no servers: %s", path)
        return

    default_timeout = float(cfg.get("default_call_timeout", 300))

    def _make_register() -> Coroutine[Any, Any, None]:
        async def _run_all() -> None:
            for i, entry in enumerate(servers):
                if not isinstance(entry, dict):
                    continue
                if entry.get("enabled") is False:
                    continue
                try:
                    await _register_one_server(
                        tm, entry, default_timeout=default_timeout
                    )
                except Exception:
                    logger.exception("MCP server #%d failed", i)

        return _run_all()

    try:
        run_mcp_coro_on_bridge_owner(
            _make_register,
            timeout=max(600.0, default_timeout * 4),
        )
    except Exception:
        logger.exception("MCP tool registration aborted")


def reload_mcp_tools_from_config(
    tm: ToolManager,
    config_path: Path | None = None,
) -> None:
    global _registered_mcp_full_names
    for name in list(_registered_mcp_full_names):
        tm._drop_tool(name)
    _registered_mcp_full_names.clear()
    try:
        close_all_mcp_bridges_sync()
    except Exception:
        logger.exception("reload_mcp_tools_from_config: bridge close")
    register_mcp_tools_from_config(tm, config_path)
