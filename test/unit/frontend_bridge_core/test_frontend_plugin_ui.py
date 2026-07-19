from types import SimpleNamespace

import pytest

from frontend_bridge_core import plugin_ui
from frontend_bridge_core.plugin_ui import (
    _frontend_config_page_payload,
    _frontend_chat_ui_contribution_payloads,
    _frontend_page_payload,
    _plugin_config_field,
    _plugin_data_root,
    _run_plugin_ui_action,
    _run_frontend_chat_ui_contribution,
)


def test_plugin_data_root_sanitizes_plugin_ids():
    assert _plugin_data_root(" com.example/demo ") == _plugin_data_root("com.example_demo")
    assert _plugin_data_root(" / ").as_posix() == "data/plugins/_"
    assert _plugin_data_root("  ").as_posix() == "data/plugins/unknown"


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


def test_plugin_config_field_includes_path_kind_for_file_type():
    """_plugin_config_field serializes pathKind when provided (e.g., for file picker)."""
    field = _plugin_config_field(
        "ref_audio",
        "Reference Audio",
        "file",
        path_kind="file",
        placeholder="Choose a WAV file...",
    )
    assert field["pathKind"] == "file"
    assert field["placeholder"] == "Choose a WAV file..."
    assert field["type"] == "file"


def test_plugin_config_field_omits_path_kind_when_not_set():
    """_plugin_config_field omits pathKind when not provided."""
    field = _plugin_config_field("output_dir", "Output Directory", "text")
    assert "pathKind" not in field


def test_frontend_chat_ui_contributions_are_serialized_without_callbacks(monkeypatch):
    action = lambda: {"kind": "info", "message": "done"}
    monkeypatch.setattr(
        plugin_ui,
        "_frontend_chat_ui_contributions",
        lambda: [
            SimpleNamespace(
                action=action,
                action_label="Run",
                contribution_id=" demo.action ",
                description="Host rendered",
                icon="sparkles",
                order=12,
                plugin_id="demo.plugin",
                plugin_version="1.0",
                slot="chat-dialog-actions",
                title=" Demo action ",
                variant="primary",
            )
        ],
    )

    payload = _frontend_chat_ui_contribution_payloads()

    assert payload == [
        {
            "actionLabel": "Run",
            "actionable": True,
            "description": "Host rendered",
            "icon": "sparkles",
            "id": "demo.action",
            "order": 12.0,
            "pluginId": "demo.plugin",
            "pluginVersion": "1.0",
            "slot": "chat-dialog-actions",
            "title": "Demo action",
            "variant": "primary",
        }
    ]
    assert "action" not in payload[0]

    assert _run_frontend_chat_ui_contribution("demo.plugin", "demo.action") == {
        "id": "demo.action",
        "kind": "info",
        "message": "done",
        "pluginId": "demo.plugin",
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
        "i18n": {},
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


# ── Actions ──


def test_frontend_config_page_payload_serializes_actions_sorted():
    """Actions from contribution are serialized as sorted metadata dicts (no callbacks)."""
    from sdk.types import FrontendConfigAction

    action_primary = FrontendConfigAction(
        id="validate",
        label="Validate",
        description="Check config",
        variant="primary",
        confirm="Proceed?",
        order=50.0,
    )
    action_ghost = FrontendConfigAction(
        id="reset",
        label="Reset",
        variant="ghost",
        order=200.0,
    )
    action_danger = FrontendConfigAction(
        id="delete",
        label="Delete All",
        variant="danger",
        order=10.0,
    )

    contribution = SimpleNamespace(
        actions=[action_primary, action_ghost, action_danger],
        description="",
        kind="settings",
        load_values=lambda: {},
        order=10.0,
        page_id="demo",
        plugin_id="demo.plugin",
        plugin_version="1.0",
        restart_hint="",
        schema=[],
        title="Demo",
    )

    payload = _frontend_config_page_payload(contribution)

    assert "actions" in payload
    assert len(payload["actions"]) == 3
    # sorted by order
    assert payload["actions"][0]["id"] == "delete"
    assert payload["actions"][1]["id"] == "validate"
    assert payload["actions"][2]["id"] == "reset"

    validate = payload["actions"][1]
    assert validate["id"] == "validate"
    assert validate["label"] == "Validate"
    assert validate["description"] == "Check config"
    assert validate["variant"] == "primary"
    assert validate["confirm"] == "Proceed?"
    assert validate["order"] == 50.0
    # callable is not serialized
    assert "run" not in validate


def test_frontend_config_page_payload_omits_actions_when_empty():
    """Payload excludes actions key when contribution has no actions."""
    contribution = SimpleNamespace(
        actions=[],
        description="",
        kind="settings",
        load_values=lambda: {},
        order=10.0,
        page_id="demo",
        plugin_id="demo.plugin",
        plugin_version="1.0",
        restart_hint="",
        schema=[],
        title="Demo",
    )

    payload = _frontend_config_page_payload(contribution)
    assert "actions" not in payload


def test_frontend_config_page_payload_omits_actions_when_none():
    """Payload excludes actions key when contribution has actions=None."""
    contribution = SimpleNamespace(
        actions=None,
        description="",
        kind="settings",
        load_values=lambda: {},
        order=10.0,
        page_id="demo",
        plugin_id="demo.plugin",
        plugin_version="1.0",
        restart_hint="",
        schema=[],
        title="Demo",
    )

    payload = _frontend_config_page_payload(contribution)
    assert "actions" not in payload


def test_run_plugin_ui_action_invokes_callback_and_returns_result(monkeypatch):
    """_run_plugin_ui_action finds the action and calls its run callback."""
    call_args: list[object] = []

    def _reload(values: object) -> dict[str, object]:
        call_args.append(values)
        return {"reloaded": True}

    from sdk.types import FrontendConfigAction

    action = FrontendConfigAction(
        id="reload",
        label="Reload",
        run=_reload,
    )
    contribution = SimpleNamespace(
        actions=[action],
        page_id="demo",
    )
    monkeypatch.setattr(plugin_ui, "_frontend_config_contributions_for", lambda plugin_id: [contribution])
    monkeypatch.setattr(
        plugin_ui,
        "_plugin_ui_detail",
        lambda plugin_id: {
            "pages": [
                {
                    "id": "demo",
                    "title": "Demo",
                    "kind": "settings",
                    "pluginId": "demo.plugin",
                    "pluginVersion": "1.0",
                }
            ],
            "plugin": {"id": "demo.plugin"},
        },
    )

    result = _run_plugin_ui_action("demo.plugin", "demo", "reload", {"values": {"enabled": True}})

    assert call_args == [{"enabled": True}]
    assert "Reload" in result["message"]
    assert "已完成" in result["message"]
    assert result["result"] == {"reloaded": True}
    assert result["page"]["id"] == "demo"
    assert result["plugin"]["id"] == "demo.plugin"


def test_run_plugin_ui_action_accepts_flat_payload_without_values_key(monkeypatch):
    """Action values can be passed as a flat dict without wrapping in 'values'."""
    call_args: list[object] = []

    def _action(values: object) -> None:
        call_args.append(values)

    from sdk.types import FrontendConfigAction

    contribution = SimpleNamespace(
        actions=[FrontendConfigAction(id="ping", label="Ping", run=_action)],
        page_id="demo",
    )
    monkeypatch.setattr(plugin_ui, "_frontend_config_contributions_for", lambda plugin_id: [contribution])
    monkeypatch.setattr(
        plugin_ui,
        "_plugin_ui_detail",
        lambda plugin_id: {
            "pages": [{"id": "demo", "pluginId": "demo.plugin"}],
            "plugin": {"id": "demo.plugin"},
        },
    )

    _run_plugin_ui_action("demo.plugin", "demo", "ping", {"enabled": False})
    assert call_args == [{"enabled": False}]


def test_run_plugin_ui_action_raises_for_unknown_action(monkeypatch):
    """_run_plugin_ui_action raises KeyError when the action_id doesn't match."""
    monkeypatch.setattr(plugin_ui, "_frontend_config_contributions_for", lambda plugin_id: [])
    monkeypatch.setattr(
        plugin_ui,
        "_plugin_ui_detail",
        lambda plugin_id: {
            "pages": [],
            "plugin": {"id": "demo.plugin"},
        },
    )

    with pytest.raises(KeyError, match="action not found"):
        _run_plugin_ui_action("demo.plugin", "demo", "nonexistent", {"values": {}})


def test_run_plugin_ui_action_handles_none_result(monkeypatch):
    """Action run returning None yields an empty result dict."""
    from sdk.types import FrontendConfigAction

    contribution = SimpleNamespace(
        actions=[FrontendConfigAction(id="noop", label="Noop", run=lambda values: None)],
        page_id="demo",
    )
    monkeypatch.setattr(plugin_ui, "_frontend_config_contributions_for", lambda plugin_id: [contribution])
    monkeypatch.setattr(
        plugin_ui,
        "_plugin_ui_detail",
        lambda plugin_id: {
            "pages": [{"id": "demo", "pluginId": "demo.plugin"}],
            "plugin": {"id": "demo.plugin"},
        },
    )

    result = _run_plugin_ui_action("demo.plugin", "demo", "noop", {"values": {}})
    assert result["result"] == {}
