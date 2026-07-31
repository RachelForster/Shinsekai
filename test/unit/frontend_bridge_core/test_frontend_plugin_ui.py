from types import SimpleNamespace

import pytest

from frontend_bridge_core import plugin_ui
from frontend_bridge_core.plugin_ui import (
    _frontend_config_page_payload,
    _frontend_chat_ui_contribution_payloads,
    _frontend_page_payload,
    _plugin_config_file,
    _plugin_config_field,
    _plugin_data_root,
    _resolve_plugin_frontend_file,
    _run_frontend_chat_ui_contribution,
    _run_plugin_ui_action,
    _stored_plugin_cache_path,
)


def test_plugin_data_root_preserves_exact_safe_ids_and_rejects_aliases(tmp_path):
    assert _plugin_data_root("com.example_demo", project_root=tmp_path) == (
        tmp_path / "data" / "plugins" / "com.example_demo"
    )
    for plugin_id in (" com.example ", "com.example/demo", "com.example\\demo", ""):
        with pytest.raises(ValueError):
            _plugin_data_root(plugin_id, project_root=tmp_path)


def test_plugin_data_root_uses_explicit_project_root_when_cwd_changes(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    unrelated = tmp_path / "unrelated"
    project_root.mkdir()
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)

    path = _plugin_data_root("demo.plugin", project_root=project_root)

    assert path == project_root / "data" / "plugins" / "demo.plugin"


def test_plugin_data_root_rejects_symlinked_project_root(tmp_path):
    project = tmp_path / "project"
    alias = tmp_path / "project-alias"
    project.mkdir()
    try:
        alias.symlink_to(project, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(PermissionError, match="symbolic link"):
        _plugin_data_root("demo.plugin", project_root=alias)


def test_plugin_data_root_rejects_portable_collision_and_symlink_storage(tmp_path):
    plugins = tmp_path / "data" / "plugins"
    plugins.mkdir(parents=True)
    (plugins / "Demo.Plugin").mkdir()

    with pytest.raises(FileExistsError, match="portable filename collision"):
        _plugin_data_root("demo.plugin", project_root=tmp_path)

    symlink_project = tmp_path / "symlink-project"
    symlink_data = symlink_project / "data"
    symlink_data.mkdir(parents=True)
    external = tmp_path / "other-storage"
    external.mkdir()
    try:
        (symlink_data / "plugins").symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(PermissionError, match="symbolic links"):
        _plugin_data_root("safe.plugin", project_root=symlink_project)


def test_plugin_config_file_is_a_direct_managed_leaf(tmp_path):
    project = tmp_path / "project"
    root = project / "data" / "plugins" / "demo.plugin"
    root.mkdir(parents=True)

    assert _plugin_config_file(
        root,
        root / "config.json",
        project_root=project,
    ) == root / "config.json"

    with pytest.raises(PermissionError, match="outside the plugin data root"):
        _plugin_config_file(
            root,
            project / "data" / "plugins" / "other" / "config.json",
            project_root=project,
        )


def test_plugin_config_file_rejects_a_linked_leaf(tmp_path):
    project = tmp_path / "project"
    root = project / "data" / "plugins" / "demo.plugin"
    external = tmp_path / "external.json"
    root.mkdir(parents=True)
    external.write_text("{}", encoding="utf-8")
    try:
        (root / "config.json").symlink_to(external)
    except (NotImplementedError, OSError):
        pytest.skip("file symlinks are unavailable")

    with pytest.raises(PermissionError, match="symbolic links"):
        _plugin_config_file(
            root,
            root / "config.json",
            project_root=project,
        )


def test_plugin_cache_path_does_not_repeat_legacy_recovery_and_ignores_cwd(
    tmp_path,
    monkeypatch,
):
    project = tmp_path / "current-project"
    unrelated = tmp_path / "launcher"
    project.mkdir()
    unrelated.mkdir()
    stale = tmp_path / "old-project" / "data" / "cache" / "moondream"
    monkeypatch.chdir(unrelated)

    assert _stored_plugin_cache_path(
        stale.as_posix(),
        project_root=project,
    ) == stale.as_posix()
    assert _stored_plugin_cache_path(
        r"data\cache\moondream",
        project_root=project,
    ) == "data/cache/moondream"


def test_plugin_cache_path_preserves_existing_external_storage_and_rejects_aliases(
    tmp_path,
):
    project = tmp_path / "project"
    external = tmp_path / "external-cache"
    project.mkdir()
    external.mkdir()

    assert _stored_plugin_cache_path(
        external.as_posix(),
        project_root=project,
    ) == external.as_posix()
    for invalid in (" data/cache/moondream", "data/cache/../outside"):
        with pytest.raises(ValueError):
            _stored_plugin_cache_path(invalid, project_root=project)


def test_plugin_cache_path_rejects_linked_external_parent(tmp_path):
    project = tmp_path / "project"
    external = tmp_path / "external"
    alias = tmp_path / "alias"
    project.mkdir()
    external.mkdir()
    try:
        alias.symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(PermissionError, match="symbolic link"):
        _stored_plugin_cache_path(
            (alias / "moondream").as_posix(),
            project_root=project,
        )


def test_plugin_frontend_relative_entry_cannot_escape_project_root(tmp_path, monkeypatch):
    contribution = SimpleNamespace(entry="../external/index.html")
    monkeypatch.setattr(
        plugin_ui,
        "_detail_for_project_root",
        lambda *_args: {"plugin": {"id": "demo.plugin"}, "pages": []},
    )
    monkeypatch.setattr(
        plugin_ui,
        "_frontend_page_contribution",
        lambda *_args: contribution,
    )

    with pytest.raises(PermissionError, match="escapes project root"):
        _resolve_plugin_frontend_file(
            "demo.plugin",
            "page",
            "",
            project_root=tmp_path,
        )


def test_plugin_frontend_asset_path_is_exact_and_relative(tmp_path, monkeypatch):
    frontend = tmp_path / "plugins/demo/frontend"
    frontend.mkdir(parents=True)
    entry = frontend / "index.html"
    asset = frontend / "assets/app.js"
    asset.parent.mkdir()
    entry.write_text("index", encoding="utf-8")
    asset.write_text("app", encoding="utf-8")
    contribution = SimpleNamespace(entry=entry.as_posix())
    monkeypatch.setattr(
        plugin_ui,
        "_detail_for_project_root",
        lambda *_args: {"plugin": {"id": "demo.plugin"}, "pages": []},
    )
    monkeypatch.setattr(
        plugin_ui,
        "_frontend_page_contribution",
        lambda *_args: contribution,
    )

    assert _resolve_plugin_frontend_file(
        "demo.plugin",
        "page",
        "assets/app.js",
        project_root=tmp_path,
    ) == asset
    for raw in (
        " assets/app.js",
        "assets/app.js ",
        "/assets/app.js",
        "assets\\app.js",
        "assets/./app.js",
        "assets//app.js",
        "assets/../index.html",
    ):
        with pytest.raises((PermissionError, ValueError)):
            _resolve_plugin_frontend_file(
                "demo.plugin",
                "page",
                raw,
                project_root=tmp_path,
            )


def test_plugin_frontend_does_not_serve_symlinked_asset(tmp_path, monkeypatch):
    frontend = tmp_path / "plugins/demo/frontend"
    external = tmp_path / "secret.js"
    frontend.mkdir(parents=True)
    entry = frontend / "index.html"
    entry.write_text("index", encoding="utf-8")
    external.write_text("secret", encoding="utf-8")
    try:
        (frontend / "app.js").symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable")
    contribution = SimpleNamespace(entry=entry.as_posix())
    monkeypatch.setattr(
        plugin_ui,
        "_detail_for_project_root",
        lambda *_args: {"plugin": {"id": "demo.plugin"}, "pages": []},
    )
    monkeypatch.setattr(
        plugin_ui,
        "_frontend_page_contribution",
        lambda *_args: contribution,
    )

    with pytest.raises(PermissionError, match="symbolic link"):
        _resolve_plugin_frontend_file(
            "demo.plugin",
            "page",
            "app.js",
            project_root=tmp_path,
        )


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
            "actionType": "callback",
            "actionable": True,
            "description": "Host rendered",
            "icon": "sparkles",
            "id": "demo.action",
            "order": 12.0,
            "pageId": "",
            "pageMode": "navigate",
            "pluginId": "demo.plugin",
            "pluginVersion": "1.0",
            "presentation": "button",
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


def test_frontend_chat_ui_contribution_serializes_phone_page_navigation(monkeypatch):
    monkeypatch.setattr(
        plugin_ui,
        "_frontend_chat_ui_contributions",
        lambda: [
            SimpleNamespace(
                action={"type": "open-plugin-page", "page_id": " phone ", "mode": "overlay"},
                contribution_id="demo.phone",
                description="Open phone",
                icon="smartphone",
                order=30,
                plugin_id="demo.plugin",
                plugin_version="1.0",
                presentation="button",
                slot="chat-top-toolbar",
                title="Phone",
                variant="ghost",
            )
        ],
    )

    assert _frontend_chat_ui_contribution_payloads() == [
        {
            "actionLabel": "Phone",
            "actionType": "open-plugin-page",
            "actionable": True,
            "description": "Open phone",
            "icon": "smartphone",
            "id": "demo.phone",
            "order": 30.0,
            "pageId": "phone",
            "pageMode": "overlay",
            "pluginId": "demo.plugin",
            "pluginVersion": "1.0",
            "presentation": "icon-only",
            "slot": "chat-top-toolbar",
            "title": "Phone",
            "variant": "ghost",
        }
    ]


def test_frontend_chat_ui_payload_does_not_truncate_lookup_identifiers(monkeypatch):
    long_contribution_id = "c" * 129
    long_page_id = "p" * 129
    long_plugin_id = "g" * 129
    monkeypatch.setattr(
        plugin_ui,
        "_frontend_chat_ui_contributions",
        lambda: [
            SimpleNamespace(
                action={"type": "open-plugin-page", "page_id": long_page_id},
                contribution_id=long_contribution_id,
                description="",
                icon="puzzle",
                order=1,
                plugin_id=long_plugin_id,
                plugin_version="1.0",
                presentation="button",
                slot="chat-output",
                title="Long identifiers",
                variant="ghost",
            )
        ],
    )

    payload = _frontend_chat_ui_contribution_payloads()[0]

    assert payload["id"] == long_contribution_id
    assert payload["pageId"] == long_page_id
    assert payload["pluginId"] == long_plugin_id


def test_frontend_config_page_payload_preserves_exact_ids_and_normalizes_kind():
    contribution = SimpleNamespace(
        description="Config page",
        kind="invalid",
        load_values=lambda: {"enabled": True},
        order=12.5,
        page_id="settings",
        plugin_id="demo.plugin",
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
        "pluginId": "demo.plugin",
        "pluginVersion": "1.0",
        "restartHint": "Restart required",
        "schema": [{"id": "main", "fields": []}],
        "title": "settings",
        "values": {"enabled": True},
    }


def test_frontend_config_page_payload_rejects_whitespace_retargeted_id():
    contribution = SimpleNamespace(
        kind="settings",
        load_values=lambda: {},
        page_id=" settings ",
        plugin_id="demo.plugin",
        title="Settings",
    )

    with pytest.raises(ValueError, match="portable path component"):
        _frontend_config_page_payload(contribution)


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
        plugin_id="demo.plugin",
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
            plugin_id="demo.plugin",
            plugin_version="2.0",
            title="Browser",
        )
    )

    assert payload["frontendUrl"] == (
        "/api/plugins/demo.plugin/frontend/browser%20page/?pluginId=demo.plugin&pageId=browser%20page"
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
