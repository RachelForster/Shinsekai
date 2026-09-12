from ai.llm.template.integrations import tools
from ai.tools.tool_manager import ToolManager


def function(module):
    def run():
        return "ok"
    run.__module__ = module
    return run


def translate(key, **values):
    return f"{key}: {values}"


def test_disabled_plugin_tools_and_groups_are_absent_without_losing_shared_groups(monkeypatch):
    monkeypatch.setattr(ToolManager, "_instance", None)
    monkeypatch.setattr(tools, "read_plugin_manifest_items", lambda: [
        {"entry": "plugins.off.plugin:Plugin", "enabled": False},
        {"entry": "plugins.on.plugin:Plugin", "enabled": True},
    ])
    entries = [
        (function("ai.tools.chat_ui_tools"), "builtin", "builtin description", "default", "low"),
        (function("plugins.off.tools"), "disabled_default", "disabled description", "default", "low"),
        (function("plugins.on.tools"), "enabled_default", "enabled description", "default", "low"),
    ]
    monkeypatch.setattr(tools, "iter_registered_tools", lambda: iter(entries))
    manager = ToolManager()
    for module, name, group in [
        ("plugins.off.tools", "stale", "default"),
        ("plugins.off.tools", "off_only", "disabled_group"),
        ("plugins.off.tools", "off_shared", "shared"),
        ("plugins.on.tools", "on_shared", "shared"),
        ("plugins.removed.tools", "removed_tool", "removed_group"),
    ]:
        manager.register_function(function(module), name=name, group=group)
    prompt = tools.format_llm_tools_block(translate)
    assert "builtin description" in prompt
    assert "enabled description" in prompt
    assert "shared" in prompt
    for hidden in ("disabled description", "stale", "disabled_group", "removed_tool", "removed_group"):
        assert hidden not in prompt
    assert not any(item["function"]["name"] == "disabled_default" for item in manager.get_definitions())


def test_next_render_observes_manifest_toggle_for_external_plugin_package(monkeypatch):
    monkeypatch.setattr(ToolManager, "_instance", None)
    manifest = [{"entry": "external.feature.plugin:Plugin", "enabled": True}]
    monkeypatch.setattr(tools, "read_plugin_manifest_items", lambda: manifest)
    entries = [(function("external.feature.tools"), "external_tool", "external description", "default", "low")]
    monkeypatch.setattr(tools, "iter_registered_tools", lambda: iter(entries))
    assert "external_tool" in tools.format_llm_tools_block(translate)
    manifest[0]["enabled"] = False
    assert tools.format_llm_tools_block(translate) == ""
    manifest[0]["enabled"] = True
    assert "external_tool" in tools.format_llm_tools_block(translate)


def test_disabled_entry_is_not_enabled_by_a_sibling_plugin(monkeypatch):
    monkeypatch.setattr(ToolManager, "_instance", None)
    monkeypatch.setattr(tools, "read_plugin_manifest_items", lambda: [
        {"entry": "external.off:Plugin", "enabled": False},
        {"entry": "external.on:Plugin", "enabled": True},
    ])
    monkeypatch.setattr(tools, "iter_registered_tools", lambda: iter([
        (function("external.off"), "off_tool", "off description", "default", "low"),
        (function("external.on"), "on_tool", "on description", "default", "low"),
    ]))
    prompt = tools.format_llm_tools_block(translate)
    assert "on_tool" in prompt
    assert "off_tool" not in prompt
