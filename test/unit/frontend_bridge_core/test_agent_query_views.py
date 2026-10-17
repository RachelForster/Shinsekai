"""Agent HTTP projections stay small while frontend responses retain their fields."""

from __future__ import annotations

import http.client
import json
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from config.schema import ApiConfig, AppConfig, Character, SystemConfig
from frontend_bridge_core.routes.api import FrontendBridgeHandler
from frontend_bridge_core.transport.agent_http_tools import (
    BridgeHttpClient,
    build_bridge_http_tools,
)
from sdk.agent import AgentHostToolCall


@pytest.fixture
def query_views(tmp_path, monkeypatch):
    name = "目标/角色 &?#+ 甲"
    config = AppConfig(
        characters=[
            Character(
                name=name,
                color="#ffffff",
                sprite_prefix="target",
                character_setting="target-setting",
                refer_audio_path="target.wav",
            ),
            Character(
                name="其他人物",
                color="#ffffff",
                sprite_prefix="other",
                character_setting="unrequested-setting-" * 40000,
            ),
        ],
        background_list=[],
        api_config=ApiConfig(llm_api_key={"Deepseek": "private-provider-key"}),
        system_config=SystemConfig(),
    )
    installed = [
        {
            "id": "demo.browser",
            "title": "浏览器",
            "enabled": True,
            "loaded": False,
            "description": "unrequested-description-" * 40000,
            "settingsPages": [{"id": "settings", "schema": {"secret": "details"}}],
            "futureMetadata": "unrequested-field",
        }
    ]
    registry = [
        {
            "id": "demo.browser",
            "displayName": "浏览器",
            "installed": True,
            "description": "unrequested-registry-description-" * 40000,
            "securityScan": {"reviews": ["unrequested-review"]},
            "downloadUrl": "https://example.com/plugin.zip",
        }
    ]
    inspected = []
    monkeypatch.setattr(
        "frontend_bridge_core.routes.plugin_routes.plugin_load_snapshot", lambda _: {}
    )
    monkeypatch.setattr(
        "frontend_bridge_core.routes.plugin_routes._plugin_rows", lambda _: installed
    )
    monkeypatch.setattr(
        "frontend_bridge_core.routes.plugin_routes._plugin_registry_rows",
        lambda: registry,
    )

    def inspect(plugin_id):
        inspected.append(plugin_id)
        return {
            "plugin": {"id": plugin_id},
            "pages": [{"id": "settings", "config": {"browser_type": "msedge"}}],
        }

    monkeypatch.setattr(
        "frontend_bridge_core.routes.plugin_routes._plugin_ui_detail", inspect
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), FrontendBridgeHandler)
    server.state = SimpleNamespace(
        auth_token="query-view-token",
        config_manager=SimpleNamespace(config=config),
        project_root_dir=str(tmp_path),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    read = build_bridge_http_tools(*server.server_address, "query-view-token")[0]

    def invoke(operation, **params):
        return read.execute(
            None,
            AgentHostToolCall(
                call_id="query-call",
                name=read.definition.name,
                arguments={"operation": operation, "params": params},
            ),
        )

    def frontend(path):
        connection = http.client.HTTPConnection(*server.server_address, timeout=8)
        try:
            connection.request(
                "GET", path, headers={"X-Shinsekai-Bridge-Token": "query-view-token"}
            )
            response = connection.getresponse()
            assert response.status == 200
            return json.loads(response.read())
        finally:
            connection.close()

    try:
        yield SimpleNamespace(
            name=name,
            config=config,
            installed=installed,
            registry=registry,
            inspected=inspected,
            invoke=invoke,
            frontend=frontend,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


def test_character_names_are_projected_before_the_response_limit(query_views):
    full = query_views.frontend("/api/characters")
    assert full == [
        character.model_dump(mode="json") for character in query_views.config.characters
    ]
    assert len(json.dumps(full).encode()) > BridgeHttpClient.MAX_RESPONSE_BYTES

    result = query_views.invoke("characters.list")
    assert result.ok
    assert result.data["data"] == [query_views.name, "其他人物"]
    assert "unrequested-setting" not in result.model_dump_json()
    assert "target-setting" not in result.model_dump_json()


def test_character_detail_only_returns_the_named_target(query_views):
    result = query_views.invoke("characters.get", name=query_views.name)
    assert result.ok
    assert result.data["data"] == query_views.config.characters[0].model_dump(
        mode="json"
    )
    assert "unrequested-setting" not in result.model_dump_json()


@pytest.mark.parametrize("name", ["不存在的人物", "   "])
def test_missing_character_does_not_fall_back_to_the_full_list(query_views, name):
    result = query_views.invoke("characters.get", name=name)
    assert not result.ok
    assert result.error.code == "INVALID_REQUEST"
    assert "unrequested-setting" not in result.model_dump_json()


@pytest.mark.parametrize(
    "operation,path,collection,keys",
    [
        (
            "plugins.list",
            "/api/plugins",
            "installed",
            ("id", "title", "enabled", "loaded"),
        ),
        (
            "plugins.registry",
            "/api/plugins/registry",
            "registry",
            ("id", "displayName", "installed"),
        ),
    ],
)
def test_plugin_summaries_leave_frontend_details_intact(
    query_views, operation, path, collection, keys
):
    rows = getattr(query_views, collection)
    assert query_views.frontend(path) == rows
    assert len(json.dumps(rows).encode()) > BridgeHttpClient.MAX_RESPONSE_BYTES

    result = query_views.invoke(operation)
    assert result.ok
    assert result.data["data"] == [{key: row[key] for key in keys} for row in rows]
    assert "unrequested-" not in result.model_dump_json()
    assert not query_views.inspected

    detail = query_views.invoke("plugins.inspect", plugin_id=rows[0]["id"])
    assert detail.ok
    assert detail.data["data"]["pages"][0]["config"] == {"browser_type": "msedge"}
    assert query_views.inspected == [rows[0]["id"]]


def test_agent_config_does_not_serialize_character_or_resource_collections(
    query_views, monkeypatch
):
    full = query_views.frontend("/api/config")
    assert full["characters"][1]["character_setting"].startswith("unrequested-setting")
    assert "background_list" in full and "effect_list" in full

    def forbid_full_dump(*args, **kwargs):
        raise AssertionError("Agent config must not serialize all application data")

    monkeypatch.setattr(AppConfig, "model_dump", forbid_full_dump)
    result = query_views.invoke("app.config")
    assert result.ok
    assert set(result.data["data"]) == {"api_config", "system_config"}
    assert (
        result.data["data"]["api_config"]["llm_base_url"]
        == "https://api.deepseek.com/v1"
    )
    wire = result.model_dump_json()
    assert "unrequested-setting" not in wire
    assert "private-provider-key" not in wire
