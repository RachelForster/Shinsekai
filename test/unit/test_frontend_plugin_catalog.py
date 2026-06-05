from types import SimpleNamespace

from frontend_bridge_core.plugin_catalog import (
    _display_title_for_offline_plugin_entry,
    _resolve_loaded_plugin_for_manifest_entry,
)


class DemoPlugin:
    pass


def test_display_title_for_offline_plugin_entry_uses_class_or_module_tail():
    assert _display_title_for_offline_plugin_entry("plugins.demo.plugin:DemoPlugin") == "DemoPlugin"
    assert _display_title_for_offline_plugin_entry("plugins.demo.plugin") == "plugin"
    assert _display_title_for_offline_plugin_entry("Demo") == "Demo"


def test_resolve_loaded_plugin_for_manifest_entry_matches_full_entry_or_module():
    plugin = DemoPlugin()
    manager = SimpleNamespace(plugins=[plugin])
    full_entry = f"{DemoPlugin.__module__}:{DemoPlugin.__qualname__}"

    assert _resolve_loaded_plugin_for_manifest_entry(full_entry, manager) is plugin
    assert _resolve_loaded_plugin_for_manifest_entry(DemoPlugin.__module__, manager) is plugin
    assert _resolve_loaded_plugin_for_manifest_entry("missing.module:Plugin", manager) is None
    assert _resolve_loaded_plugin_for_manifest_entry(full_entry, None) is None


def test_resolve_loaded_plugin_for_manifest_entry_handles_manager_errors():
    class BrokenManager:
        @property
        def plugins(self):
            raise RuntimeError("unavailable")

    assert _resolve_loaded_plugin_for_manifest_entry("anything", BrokenManager()) is None
