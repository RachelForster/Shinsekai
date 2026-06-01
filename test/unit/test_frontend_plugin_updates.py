from types import SimpleNamespace

from frontend_bridge_core.plugin_updates import (
    _infer_plugin_entry,
    _is_repo_source,
    _plugin_class_from_file,
    _repo_slug_from_source,
    _synthetic_plugin_result,
)


def test_repo_slug_from_source_accepts_common_github_forms():
    assert _repo_slug_from_source("owner/repo") == "owner/repo"
    assert _repo_slug_from_source("https://github.com/owner/repo.git") == "owner/repo"
    assert _repo_slug_from_source("http://github.com/owner/repo/tree/main?x=1#readme") == "owner/repo"
    assert _repo_slug_from_source("owner") == ""


def test_repo_source_rejects_manifest_entries():
    assert _is_repo_source("owner/repo") is True
    assert _is_repo_source("plugins.demo.plugin:DemoPlugin") is False
    assert _is_repo_source("not-enough") is False


def test_plugin_class_from_file_detects_pluginbase_subclasses(tmp_path):
    plugin_py = tmp_path / "plugin.py"
    plugin_py.write_text(
        "\n".join(
            [
                "class Helper:",
                "    pass",
                "class DemoPlugin(PluginBase):",
                "    pass",
            ]
        ),
        encoding="utf-8",
    )

    assert _plugin_class_from_file(plugin_py) == "DemoPlugin"

    plugin_py.write_text("class Broken(:\n", encoding="utf-8")
    assert _plugin_class_from_file(plugin_py) == ""


def test_infer_plugin_entry_uses_top_level_or_nested_plugin_file(tmp_path):
    plugin_root = tmp_path / "demo_plugin"
    plugin_root.mkdir()
    (plugin_root / "plugin.py").write_text("class DemoPlugin(PluginBase):\n    pass\n", encoding="utf-8")

    assert _infer_plugin_entry(plugin_root) == "plugins.demo_plugin.plugin:DemoPlugin"

    nested_root = tmp_path / "nested_plugin"
    nested = nested_root / "package"
    nested.mkdir(parents=True)
    (nested / "plugin.py").write_text("class NestedPlugin(shin.PluginBase):\n    pass\n", encoding="utf-8")

    assert _infer_plugin_entry(nested_root) == "plugins.nested_plugin.package.plugin:NestedPlugin"


def test_synthetic_plugin_result_uses_safe_defaults():
    assert _synthetic_plugin_result(
        description="Downloaded but not enabled",
        enabled=False,
        plugin_id="plugins.demo.plugin:Demo",
        title="Demo",
        version="1.0",
    ) == {
        "author": "",
        "description": "Downloaded but not enabled",
        "directory": "",
        "enabled": False,
        "entry": "plugins.demo.plugin:Demo",
        "id": "plugins.demo.plugin:Demo",
        "loadError": "",
        "loaded": False,
        "permissions": [],
        "settingsPages": [],
        "slots": ["settings-extension"],
        "title": "Demo",
        "toolsTabs": [],
        "version": "1.0",
    }


def test_infer_plugin_entry_ignores_non_identifier_module_parts(tmp_path):
    plugin_root = tmp_path / "bad-name"
    plugin_root.mkdir()
    (plugin_root / "plugin.py").write_text("class DemoPlugin(PluginBase):\n    pass\n", encoding="utf-8")

    assert _infer_plugin_entry(plugin_root) == ""
