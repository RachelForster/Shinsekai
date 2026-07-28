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
        register_mcp_tools=lambda value: calls.setdefault("mcp", value),
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
        "sdk_tools": tool_manager,
        "plugin_tools": tool_manager,
        "mcp": tool_manager,
    }
