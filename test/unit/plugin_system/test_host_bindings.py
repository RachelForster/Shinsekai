from __future__ import annotations

from plugin_system.host import service
from plugin_system.host.service import PluginRuntimeBindings


def test_plugin_host_never_collects_deprecated_qt_contributions(monkeypatch) -> None:
    class FailIfCollected:
        def collect_settings_contributions(self):
            raise AssertionError("deprecated Qt settings contribution was collected")

        def collect_tools_tab_contributions(self):
            raise AssertionError("deprecated Qt tools contribution was collected")

        def collect_chat_ui_contributions(self):
            raise AssertionError("deprecated Qt chat contribution was collected")

    monkeypatch.setattr(service, "_plugin_manager", FailIfCollected())

    assert service.collect_settings_contributions() == []
    assert service.collect_tools_tab_contributions() == []
    assert service.collect_chat_ui_contributions() == []


def test_plugin_host_applies_application_runtime_bindings(monkeypatch, tmp_path) -> None:
    calls: dict[str, object] = {}

    class FakePluginManager:
        capabilities = object()

        def load_manifest_file(self, _path) -> None:
            raise AssertionError("missing test manifest must not be loaded")

        def instantiate_all(self) -> None:
            calls["instantiate"] = True

        def load_own_config_all(self, *, app_config) -> None:
            calls["config"] = app_config

        def apply_llm_providers(self, adapters) -> None:
            calls["llm"] = adapters

        def apply_tts_providers(self, adapters) -> None:
            calls["tts"] = adapters

        def apply_asr_providers(self, adapters) -> None:
            calls["asr"] = adapters

        def apply_t2i_providers(self, adapters) -> None:
            calls["t2i"] = adapters

        def collect_vision_fallbacks(self):
            return ["vision"]

        def apply_llm_tools(self, manager) -> None:
            calls["plugin_tools"] = manager

        def collect_message_handlers(self):
            return [], []

        def collect_dag_yaml_paths(self):
            return []

        def collect_workflow_contributions(self):
            return []

        def collect_output_contract_patches(self):
            return []

        def collect_avatar_formats(self):
            return ["avatar"]

        def collect_dialog_formats(self):
            return ["dialog-format"]

        def collect_model_assets(self):
            return ["model-asset"]

    manager = FakePluginManager()
    tool_manager = object()
    app_config = object()
    adapters = {
        "llm": {},
        "tts": {},
        "asr": {},
        "t2i": {},
    }

    monkeypatch.setattr(service, "_loaded", False)
    monkeypatch.setattr(service, "_plugin_manager", None)
    monkeypatch.setattr(service, "_MANIFEST", tmp_path / "missing.yaml")
    monkeypatch.setattr(service, "PluginManager", lambda: manager)
    monkeypatch.setattr(service, "ensure_plugins_namespace_on_syspath", lambda: None)
    monkeypatch.setattr(service, "ensure_plugin_site_packages_on_syspath", lambda: None)
    monkeypatch.setattr("sdk.tool_registry.apply_registered_tools", lambda value: calls.setdefault("sdk_tools", value))

    bindings = PluginRuntimeBindings(
        llm_adapters=adapters["llm"],
        tts_adapters=adapters["tts"],
        asr_adapters=adapters["asr"],
        t2i_adapters=adapters["t2i"],
        create_tool_manager=lambda: tool_manager,
        configure_vision_fallbacks=lambda values: calls.setdefault("vision", values),
        configure_avatar_formats=lambda values: calls.setdefault("avatar", values),
        configure_dialog_formats=lambda values: calls.setdefault("dialog_formats", values),
        register_mcp_tools=lambda value: calls.setdefault("mcp", value),
        configure_model_assets=lambda values: calls.setdefault("model_assets", values),
    )

    assert service.ensure_plugins_loaded(app_config, runtime_bindings=bindings) is manager
    assert calls == {
        "instantiate": True,
        "config": app_config,
        "llm": adapters["llm"],
        "tts": adapters["tts"],
        "asr": adapters["asr"],
        "t2i": adapters["t2i"],
        "vision": ["vision"],
        "avatar": ["avatar"],
        "dialog_formats": ["dialog-format"],
        "model_assets": ["model-asset"],
        "sdk_tools": tool_manager,
        "plugin_tools": tool_manager,
        "mcp": tool_manager,
    }


def test_frontend_bridge_wires_dialog_format_bindings() -> None:
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parents[3] / "frontend_bridge.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    has_builtin_call = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "configure_builtin_dialog_formats"
        for node in ast.walk(tree)
    )
    has_runtime_binding = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "PluginRuntimeBindings"
        and any(
            kw.arg == "configure_dialog_formats"
            and isinstance(kw.value, ast.Name)
            and kw.value.id == "configure_registered_dialog_formats"
            for kw in node.keywords
        )
        for node in ast.walk(tree)
    )
    assert has_builtin_call
    assert has_runtime_binding


def test_bind_model_assets_runtime_wires_and_unwires_sdk_dispatcher() -> None:
    import pytest
    from sdk.model_assets import inspect_huggingface_model

    received: list[dict[str, object]] = []
    service.bind_model_assets_runtime(
        lambda command: (received.append(command) or {"cached": True, "repoId": command["repoId"]})
    )
    try:
        status = inspect_huggingface_model("BAAI/bge-m3", revision="main")
        assert status == {"cached": True, "repoId": "BAAI/bge-m3"}
        assert received == [{"action": "status", "repoId": "BAAI/bge-m3", "revision": "main"}]
    finally:
        service.bind_model_assets_runtime(None)

    with pytest.raises(RuntimeError, match="Model assets runtime is not bound"):
        inspect_huggingface_model("BAAI/bge-m3")

