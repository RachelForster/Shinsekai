from __future__ import annotations

import http.client
import json
import sys
import threading
from http.server import ThreadingHTTPServer
from types import ModuleType, SimpleNamespace

import pytest
from pydantic import ValidationError

from ai.tools.tool_manager import ToolManager
from application.plugins import tools as plugin_tools
from application.runtime.services import ApplicationServices
from frontend_bridge_core.routes.api import FrontendBridgeHandler
from frontend_bridge_core.transport.agent_http_tools import build_bridge_http_tools
from sdk.agent import AgentHostToolCall, AgentRequestError


PLUGIN_ID = "fixture.browser"


@pytest.fixture
def loaded_tools(monkeypatch):
    calls = []

    class Plugin:
        __module__ = "fixture.browser.plugin"
        plugin_id = PLUGIN_ID
        enabled = True

        def shutdown(self):
            calls.append(("shutdown", threading.get_ident()))

    def search(query: str):
        calls.append((query, threading.get_ident()))
        if query == "fail":
            return {"error": "Search provider unavailable"}
        return {
            "query": query,
            "results": [{"url": "https://example.com/wiki", "title": "Character"}],
        }

    def get_text():
        calls.append(("text", threading.get_ident()))
        return {"text": "Verified character biography"}

    def other_tool():
        calls.append(("wrong-plugin", threading.get_ident()))
        return {"ok": True}

    search.__module__ = get_text.__module__ = "fixture.browser.llm_tool"
    other_tool.__module__ = "fixture.other.tools"
    monkeypatch.setattr(ToolManager, "_instance", None)
    registry = ToolManager()
    registry.register_function(search, name="playwright_search_web", group="browser")
    registry.register_function(get_text, name="playwright_get_text", group="browser")
    registry.register_function(other_tool, name="another_plugin_tool", group="browser")
    plugin = Plugin()
    rows = [{"id": PLUGIN_ID, "enabled": True, "loaded": True}]
    monkeypatch.setattr(
        plugin_tools, "get_plugin_manager", lambda: SimpleNamespace(plugins=(plugin,))
    )
    monkeypatch.setattr(plugin_tools, "_plugin_rows", lambda: rows)
    yield registry, calls, rows, plugin


def test_tools_are_discovered_per_loaded_plugin_and_execute_on_one_thread(loaded_tools):
    _, calls, _, _ = loaded_tools
    service = plugin_tools.PluginToolService()
    try:
        catalog = service.list_tools(PLUGIN_ID)
        assert [tool["name"] for tool in catalog["tools"]] == [
            "playwright_search_web",
            "playwright_get_text",
        ]
        assert catalog["tools"][0]["inputSchema"]["required"] == ["query"]
        first = service.invoke(
            PLUGIN_ID, "playwright_search_web", {"query": "人物 作品"}
        )
        second = service.invoke(PLUGIN_ID, "playwright_get_text", {})
        assert first["result"]["results"][0]["title"] == "Character"
        assert second["result"]["text"] == "Verified character biography"
    finally:
        service.close()
    assert [name for name, _ in calls] == ["人物 作品", "text", "shutdown"]
    assert len({thread for _, thread in calls}) == 1
    assert calls[0][1] != threading.get_ident()
    service.close()
    with pytest.raises(AgentRequestError):
        service.invoke(PLUGIN_ID, "playwright_get_text", {})


@pytest.mark.parametrize(
    "arguments", [{}, {"query": 42}, {"query": "ok", "extra": True}]
)
def test_invalid_plugin_arguments_do_not_execute(loaded_tools, arguments):
    _, calls, _, _ = loaded_tools
    service = plugin_tools.PluginToolService()
    try:
        with pytest.raises(ValidationError):
            service.invoke(PLUGIN_ID, "playwright_search_web", arguments)
        assert not calls
    finally:
        service.close()


def test_disabled_missing_or_other_plugin_tools_are_not_invoked(
    loaded_tools, monkeypatch
):
    _, calls, rows, _ = loaded_tools
    service = plugin_tools.PluginToolService()
    try:
        with pytest.raises(PermissionError):
            service.invoke(PLUGIN_ID, "another_plugin_tool", {})
        with pytest.raises(FileNotFoundError):
            service.list_tools("missing.plugin")
        rows[0]["enabled"] = False
        with pytest.raises(PermissionError):
            service.invoke(PLUGIN_ID, "playwright_get_text", {})
        monkeypatch.setattr(plugin_tools, "get_plugin_manager", lambda: None)
        with pytest.raises(AgentRequestError) as error:
            service.list_tools(PLUGIN_ID)
        assert error.value.error.code == "BACKEND_UNAVAILABLE"
        assert not calls
    finally:
        service.close()


def test_plugin_class_in_package_does_not_expose_other_plugins(
    loaded_tools, monkeypatch
):
    _, _, _, plugin = loaded_tools
    module = ModuleType("fixture.browser")
    module.__package__ = "fixture.browser"
    module.__path__ = []
    monkeypatch.setitem(sys.modules, "fixture.browser", module)
    monkeypatch.setattr(type(plugin), "__module__", "fixture.browser")
    service = plugin_tools.PluginToolService()
    try:
        assert [tool["name"] for tool in service.list_tools(PLUGIN_ID)["tools"]] == [
            "playwright_search_web",
            "playwright_get_text",
        ]
    finally:
        service.close()


def test_plugin_error_is_reported_as_failure(loaded_tools):
    service = plugin_tools.PluginToolService()
    try:
        with pytest.raises(ValueError, match="Search provider unavailable"):
            service.invoke(PLUGIN_ID, "playwright_search_web", {"query": "fail"})
    finally:
        service.close()


def test_application_close_releases_registry_lock_before_waiting_for_tools(
    loaded_tools,
):
    services = ApplicationServices()
    service = services.get_plugin_tools()
    finished = threading.Event()

    def close_agent():
        def callback():
            with services._lock:
                finished.set()

        thread = threading.Thread(target=callback, daemon=True)
        thread.start()
        assert finished.wait(2), "Application close blocked an in-flight tool callback"
        thread.join(2)

    services.agent = SimpleNamespace(close=close_agent)
    services.close()
    assert service._closed
    with pytest.raises(RuntimeError):
        services.get_plugin_tools()


def test_agent_http_tools_reach_plugin_search_and_read_without_roleplay(loaded_tools):
    _, calls, _, _ = loaded_tools
    services = ApplicationServices()
    server = ThreadingHTTPServer(("127.0.0.1", 0), FrontendBridgeHandler)
    server.state = SimpleNamespace(services=services, auth_token="fixture-token")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    read, write = build_bridge_http_tools(*server.server_address, "fixture-token")

    def invoke(tool, operation, *, name=None, arguments=None, call_id="call"):
        params = {"plugin_id": PLUGIN_ID}
        if name:
            params["tool_name"] = name
        return tool.execute(
            None,
            AgentHostToolCall(
                call_id=call_id,
                name=tool.definition.name,
                arguments={
                    "operation": operation,
                    "params": params,
                    "body": {"arguments": arguments} if arguments is not None else {},
                },
            ),
        )

    try:
        connection = http.client.HTTPConnection(*server.server_address)
        connection.request("GET", f"/api/plugins/{PLUGIN_ID}/tools")
        response = connection.getresponse()
        assert response.status == 403
        response.read()
        connection.close()
        catalog = invoke(read, "plugins.tools")
        assert catalog.ok
        assert len(catalog.data["data"]["tools"]) == 2
        search = invoke(
            write,
            "plugins.tools.invoke",
            name="playwright_search_web",
            arguments={"query": "character"},
        )
        assert search.ok
        assert search.effects[0].state == "applied"
        assert search.data["data"]["result"]["query"] == "character"
        text = invoke(
            write, "plugins.tools.invoke", name="playwright_get_text", arguments={}
        )
        assert text.ok
        assert "biography" in text.data["data"]["result"]["text"]
        failed = invoke(
            write,
            "plugins.tools.invoke",
            name="playwright_search_web",
            arguments={"query": "fail"},
        )
        assert not failed.ok
        assert "Search provider unavailable" in failed.error.message
        assert failed.effects[0].state != "applied"
        assert len({owner for _, owner in calls}) == 1
    finally:
        server.shutdown()
        server.server_close()
        services.close()
        thread.join(3)
