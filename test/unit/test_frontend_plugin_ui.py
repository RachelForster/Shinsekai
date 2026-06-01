from types import SimpleNamespace

import pytest

from frontend_bridge_core import plugin_ui
from frontend_bridge_core.plugin_ui import (
    _frontend_config_page_payload,
    _frontend_page_payload,
    _plugin_config_field,
    _plugin_data_root,
)


def test_plugin_data_root_sanitizes_plugin_ids():
    assert _plugin_data_root(" com.example/demo ") == _plugin_data_root("com.example_demo")
    assert str(_plugin_data_root(" / ")) == "data/plugins/_"
    assert str(_plugin_data_root("  ")) == "data/plugins/unknown"


def test_plugin_config_field_omits_empty_optional_metadata():
    field = _plugin_config_field(
        "mode",
        "Mode",
        "select",
        default="safe",
        description="Run mode",
        max_value=5,
        min_value=1,
        options=[("Fast", "fast"), ("Safe", "safe")],
        placeholder="safe",
        span="full",
        step=1,
    )

    assert field == {
        "defaultValue": "safe",
        "description": "Run mode",
        "key": "mode",
        "label": "Mode",
        "max": 5,
        "min": 1,
        "options": [{"label": "Fast", "value": "fast"}, {"label": "Safe", "value": "safe"}],
        "placeholder": "safe",
        "span": "full",
        "step": 1,
        "type": "select",
    }
    assert _plugin_config_field("enabled", "Enabled", "boolean") == {
        "defaultValue": None,
        "key": "enabled",
        "label": "Enabled",
        "type": "boolean",
    }


def test_frontend_config_page_payload_normalizes_kind_and_values():
    contribution = SimpleNamespace(
        description="Config page",
        kind="invalid",
        load_values=lambda: {"enabled": True},
        order=12.5,
        page_id=" settings ",
        plugin_id="demo/plugin",
        plugin_version="1.0",
        restart_hint="Restart required",
        schema=[{"id": "main", "fields": []}],
        title="",
    )

    payload = _frontend_config_page_payload(contribution)

    assert payload == {
        "description": "Config page",
        "id": "settings",
        "kind": "settings",
        "order": 12.5,
        "pluginId": "demo/plugin",
        "pluginVersion": "1.0",
        "restartHint": "Restart required",
        "schema": [{"id": "main", "fields": []}],
        "title": "settings",
        "values": {"enabled": True},
    }


def test_frontend_config_page_payload_requires_mapping_values():
    contribution = SimpleNamespace(
        kind="settings",
        load_values=lambda: ["not", "a", "mapping"],
        page_id="settings",
        title="Settings",
    )

    with pytest.raises(ValueError, match="load_values must return a mapping"):
        _frontend_config_page_payload(contribution)


def test_frontend_page_payload_builds_encoded_url_and_merges_matching_config(monkeypatch):
    config_contribution = SimpleNamespace(
        description="Config description",
        kind="tools",
        load_values=lambda: {"headless": False},
        order=8,
        page_id="browser page",
        plugin_id="demo/plugin",
        plugin_version="2.0",
        restart_hint="Restart browser",
        schema=[{"id": "browser", "fields": []}],
        title="Browser Settings",
    )
    monkeypatch.setattr(plugin_ui, "_frontend_config_contributions_for", lambda plugin_id: [config_contribution])

    payload = _frontend_page_payload(
        SimpleNamespace(
            description="",
            kind="tools",
            order=8,
            page_id="browser page",
            plugin_id="demo/plugin",
            plugin_version="2.0",
            title="Browser",
        )
    )

    assert payload["frontendUrl"] == (
        "/api/plugins/demo%2Fplugin/frontend/browser%20page/?pluginId=demo%2Fplugin&pageId=browser%20page"
    )
    assert payload["description"] == "Config description"
    assert payload["restartHint"] == "Restart browser"
    assert payload["schema"] == [{"id": "browser", "fields": []}]
    assert payload["values"] == {"headless": False}
