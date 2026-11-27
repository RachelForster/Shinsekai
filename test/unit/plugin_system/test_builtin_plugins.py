from __future__ import annotations

from types import SimpleNamespace

from plugin_system.host import service
from plugin_system.host.builtin_plugins import register_builtin_plugins
from plugin_system.host.service import PluginRuntimeBindings


def test_register_builtin_plugins_deduplicates_extra_plugins() -> None:
    class PluginA:
        pass

    class PluginB:
        pass

    seen: list[type] = []
    manager = SimpleNamespace(register_plugin_class=seen.append)
    register_builtin_plugins(manager, extra_plugins=(PluginA, PluginB, PluginA))
    assert seen == [PluginA, PluginB]


def test_plugin_host_forwards_extra_builtin_plugins_from_runtime_bindings(
    monkeypatch, tmp_path
) -> None:
    class DummyBuiltinPlugin:
        pass

    registered_classes: list[type] = []

    class FakePluginManager:
        capabilities = object()

        def register_plugin_class(self, cls: type) -> None:
            registered_classes.append(cls)

        def instantiate_all(self) -> None:
            return None

        def load_own_config_all(self, *, app_config) -> None:
            del app_config

        def apply_llm_providers(self, _target) -> None:
            return None

        def apply_tts_providers(self, _target) -> None:
            return None

        def apply_asr_providers(self, _target) -> None:
            return None

        def apply_t2i_providers(self, _target) -> None:
            return None

        def collect_vision_fallbacks(self):
            return []

        def apply_llm_tools(self, _tm) -> None:
            return None

        def collect_message_handlers(self):
            return [], []

        def collect_dag_yaml_paths(self):
            return []

        def collect_workflow_contributions(self):
            return []

        def collect_output_contract_patches(self):
            return []

        def collect_avatar_formats(self):
            return []

    monkeypatch.setattr(service, "_loaded", False)
    monkeypatch.setattr(service, "_plugin_manager", None)
    monkeypatch.setattr(service, "_MANIFEST", tmp_path / "missing.yaml")
    monkeypatch.setattr(service, "PluginManager", FakePluginManager)
    monkeypatch.setattr(service, "ensure_plugins_namespace_on_syspath", lambda: None)
    monkeypatch.setattr(service, "ensure_plugin_site_packages_on_syspath", lambda: None)
    monkeypatch.setattr("sdk.tool_registry.apply_registered_tools", lambda _tm: None)

    bindings = PluginRuntimeBindings(
        create_tool_manager=object,
        configure_vision_fallbacks=lambda _v: None,
        configure_avatar_formats=lambda _v: None,
        builtin_plugins=(DummyBuiltinPlugin,),
    )
    service.ensure_plugins_loaded(object(), runtime_bindings=bindings)
    assert registered_classes == [DummyBuiltinPlugin]
