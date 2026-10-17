"""Discover and execute loaded plugin tools without a roleplay runtime."""

from __future__ import annotations

import copy
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

from pydantic import ConfigDict, create_model

from ai.tools.tool_manager import ToolManager
from application.plugins.catalog import _plugin_rows
from core.agent.ipc import fault
from plugin_system.host import get_plugin_manager
from sdk.tool_registry import ToolNotReady


def _validate_arguments(schema: dict, arguments: dict) -> None:
    # ToolManager generates primitive parameter schemas for Python callables.
    types = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "object": dict,
        "array": list,
    }
    required = set(schema.get("required", []))
    fields = {}
    for name, parameter in schema.get("properties", {}).items():
        kind = types.get(parameter.get("type"))
        if kind is None:
            raise ValueError("Unsupported plugin tool parameter schema")
        fields[name] = (kind, ... if name in required else None)
    model = create_model(
        "PluginToolArguments",
        __config__=ConfigDict(extra="forbid", strict=True),
        **fields,
    )
    model.model_validate(arguments)


class PluginToolService:
    """One application-owned execution thread preserves browser thread affinity."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._closed = False
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="plugin-tools"
        )
        self._used_plugins = {}

    def _catalog(self, plugin_id: str):
        if self._closed:
            raise fault("BACKEND_UNAVAILABLE", "Plugin tool service is closed")
        manager = get_plugin_manager()
        if manager is None:
            raise fault("BACKEND_UNAVAILABLE", "Plugins have not finished loading")
        plugin = next((p for p in manager.plugins if p.plugin_id == plugin_id), None)
        if plugin is None:
            raise FileNotFoundError(f"Plugin is not loaded: {plugin_id}")
        row = next((row for row in _plugin_rows() if row["id"] == plugin_id), None)
        if row is None or not row.get("enabled") or not plugin.enabled:
            raise PermissionError(f"Plugin is disabled: {plugin_id}")
        module_name = type(plugin).__module__
        module = sys.modules.get(module_name)
        package = str(getattr(module, "__package__", "") or "")
        if module is None:
            package = module_name.rpartition(".")[0] or module_name
        elif hasattr(module, "__path__") or package in {"", "plugins"}:
            package = module_name
        tools = ToolManager()
        definitions = []
        for definition in tools.get_definitions():
            function = definition["function"]
            provenance = tools.get_tool_module(function["name"])
            if provenance == package or provenance.startswith(package + "."):
                definitions.append(
                    {
                        "name": function["name"],
                        "description": function.get("description", ""),
                        "inputSchema": copy.deepcopy(function["parameters"]),
                        "group": tools.get_tool_group(function["name"]),
                        "risk": tools.get_tool_risk(function["name"]),
                    }
                )
        return plugin, tools, definitions

    def list_tools(self, plugin_id: str) -> dict:
        with self._lock:
            _, _, definitions = self._catalog(plugin_id)
            return {"pluginId": plugin_id, "tools": definitions}

    def invoke(self, plugin_id: str, tool_name: str, arguments: dict) -> dict:
        with self._lock:
            if self._closed:
                raise fault("BACKEND_UNAVAILABLE", "Plugin tool service is closed")
            future = self._executor.submit(
                self._invoke, plugin_id, tool_name, arguments
            )
        return future.result()

    def _invoke(self, plugin_id: str, tool_name: str, arguments: dict) -> dict:
        # Recheck availability after queueing; never execute another plugin's tool.
        with self._lock:
            plugin, tools, definitions = self._catalog(plugin_id)
            definition = next((d for d in definitions if d["name"] == tool_name), None)
            if definition is None:
                raise PermissionError(
                    f"Tool does not belong to this loaded plugin: {tool_name}"
                )
            _validate_arguments(definition["inputSchema"], arguments)
            self._used_plugins[plugin_id] = plugin
        try:
            result = json.loads(
                tools.execute(tool_name, json.dumps(arguments, ensure_ascii=False))
            )
        except ToolNotReady as exc:
            raise fault(
                "BACKEND_UNAVAILABLE", exc.message or "Plugin tool is loading"
            ) from None
        if isinstance(result, dict) and (
            result.get("error") or result.get("ok") is False
        ):
            raise ValueError(str(result.get("error") or "Plugin tool failed"))
        return {"pluginId": plugin_id, "tool": tool_name, "result": result}

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            # Shutdown on the same thread that owns the plugin's browser handles.
            cleanup = self._executor.submit(self._shutdown_plugins)
        try:
            cleanup.result()
        finally:
            self._executor.shutdown(wait=True, cancel_futures=True)

    def _shutdown_plugins(self) -> None:
        for plugin in reversed(tuple(self._used_plugins.values())):
            plugin.shutdown()
