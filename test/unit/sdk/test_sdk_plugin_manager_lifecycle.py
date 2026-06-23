from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from sdk.manager import PluginManager
from sdk.plugin import PluginBase
from sdk.plugin_host_context import PluginHostContext
from sdk.register import PluginCapabilityRegistry, PluginDiscoveryRegistry
from sdk.types import (
    ChatUIContribution,
    FrontendConfigContribution,
    FrontendPageContribution,
    OutputContractPatch,
    SettingsUIContribution,
    ToolsTabContribution,
    WorkflowContribution,
)


class _BasePlugin(PluginBase):
    @property
    def plugin_id(self) -> str:
        return "demo.base"

    def initialize(
        self,
        register: PluginCapabilityRegistry,
        plugin_root: Path,
        host: PluginHostContext,
    ) -> None:
        _ = register, plugin_root, host


class _DemoPlugin(_BasePlugin):
    @property
    def plugin_id(self) -> str:
        return "demo.lifecycle"

    @property
    def plugin_version(self) -> str:
        return "2.0.0"

    @property
    def priority(self) -> int:
        return 10

    def initialize(
        self,
        register: PluginCapabilityRegistry,
        plugin_root: Path,
        host: PluginHostContext,
    ) -> None:
        assert plugin_root.name == "demo.lifecycle"
        assert isinstance(host, PluginHostContext)
        register.register_llm_adapter("demo-llm", object)  # type: ignore[arg-type]
        register.register_tts_adapter("demo-tts", object)  # type: ignore[arg-type]
        register.register_asr_adapter("demo-asr", object)  # type: ignore[arg-type]
        register.register_t2i_adapter("DEMO-T2I", object)  # type: ignore[arg-type]
        register.register_message_handler(tts_handler="tts", ui_handler="ui")  # type: ignore[arg-type]
        register.register_user_input_trigger(lambda emit: emit("triggered"))
        register.register_user_input_processor(lambda text: text.upper())
        register.register_llm_tool(lambda tool_manager: tool_manager.register("demo"))
        register.register_settings_ui(
            SettingsUIContribution(
                page_id="settings",
                nav_label="Settings",
                build=lambda context: object(),
                order=20,
            )
        )
        register.register_tools_tab(
            ToolsTabContribution(
                tab_id="tools",
                title="Tools",
                build=lambda context: object(),
                order=30,
            )
        )
        register.register_frontend_config_page(
            FrontendConfigContribution(
                page_id="frontend-config",
                title="Frontend Config",
                schema=[],
                load_values=lambda: {"enabled": True},
                save_values=lambda values: None,
                order=40,
            )
        )
        register.register_frontend_page(
            FrontendPageContribution(
                page_id="frontend-page",
                title="Frontend Page",
                entry="plugin/index.html",
                order=50,
            )
        )
        register.register_chat_ui_widget(
            ChatUIContribution(
                widget_id="chat",
                placement="toolbar",
                build=lambda context: object(),
                order=60,
            )
        )
        register.register_dag_yaml("workflows/demo.yaml")
        register.register_workflow(
            WorkflowContribution(
                id="workflow",
                name="Workflow",
                yaml_path="workflows/other.yaml",
            )
        )
        register.register_output_contract_patch(
            OutputContractPatch(
                id="patch",
                target_contract="contract",
                priority=70,
            )
        )


def test_plugin_manager_collects_every_registered_capability(tmp_path: Path) -> None:
    manager = PluginManager(plugin_data_root=tmp_path)
    manager.register_plugin_class(_DemoPlugin)

    target: dict[str, object] = {}
    manager.apply_llm_providers(target)
    assert target["demo-llm"] is object

    target.clear()
    manager.apply_tts_providers(target)
    assert target["demo-tts"] is object

    target.clear()
    manager.apply_asr_providers(target)
    assert target["demo-asr"] is object

    target.clear()
    manager.apply_t2i_providers(target)
    assert target["demo-t2i"] is object

    tts_handlers, ui_handlers = manager.collect_message_handlers()
    assert tts_handlers == ["tts"]
    assert ui_handlers == ["ui"]

    emitted: list[str] = []
    processors: list[object] = []
    manager.wire_user_input(emitted.append, processors)  # type: ignore[arg-type]
    assert emitted == ["triggered"]
    assert processors[0]("abc") == "ABC"  # type: ignore[index,operator]

    class _ToolManager:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def register(self, name: str) -> None:
            self.calls.append(name)

    tools = _ToolManager()
    manager.apply_llm_tools(tools)  # type: ignore[arg-type]
    assert tools.calls == ["demo"]

    assert manager.collect_settings_contributions()[0].plugin_id == "demo.lifecycle"
    assert manager.collect_tools_tab_contributions()[0].plugin_version == "2.0.0"
    assert manager.collect_frontend_config_contributions()[0].page_id == "frontend-config"
    assert manager.collect_frontend_page_contributions()[0].page_id == "frontend-page"
    assert manager.collect_chat_ui_contributions()[0].widget_id == "chat"
    assert manager.collect_dag_yaml_paths() == [
        "workflows/demo.yaml",
        "workflows/other.yaml",
    ]
    assert manager.collect_workflow_contributions()[1].id == "workflow"
    assert manager.collect_output_contract_patches()[0].id == "patch"
    assert tuple(manager.plugins)[0].plugin_id == "demo.lifecycle"
    assert list(manager.iter_plugin_ids()) == ["demo.lifecycle"]


def test_plugin_manager_isolates_plugin_failures(tmp_path: Path, caplog) -> None:
    calls: list[str] = []

    class BrokenInitPlugin(_BasePlugin):
        @property
        def plugin_id(self) -> str:
            return "demo.broken-init"

        def initialize(
            self,
            register: PluginCapabilityRegistry,
            plugin_root: Path,
            host: PluginHostContext,
        ) -> None:
            _ = register, plugin_root, host
            raise RuntimeError("init failed")

    class BrokenShutdownPlugin(_BasePlugin):
        @property
        def plugin_id(self) -> str:
            return "demo.broken-shutdown"

        def shutdown(self) -> None:
            calls.append("shutdown")
            raise RuntimeError("shutdown failed")

    class GoodPlugin(_BasePlugin):
        @property
        def plugin_id(self) -> str:
            return "demo.good"

        def initialize(
            self,
            register: PluginCapabilityRegistry,
            plugin_root: Path,
            host: PluginHostContext,
        ) -> None:
            _ = plugin_root, host
            register.register_llm_adapter("good", object)  # type: ignore[arg-type]

    manager = PluginManager(plugin_data_root=tmp_path)
    manager.register_plugin_class(BrokenInitPlugin)
    manager.register_plugin_class(BrokenShutdownPlugin)
    manager.register_plugin_class(GoodPlugin)

    with caplog.at_level(logging.ERROR):
        target: dict[str, object] = {}
        manager.apply_llm_providers(target)
        manager.shutdown_all()

    assert target == {"good": object}
    assert calls == ["shutdown"]
    assert "initialize failed for demo.broken-init" in caplog.text
    assert "shutdown failed for demo.broken-shutdown" in caplog.text


def test_apply_llm_tools_logs_registrar_failures(tmp_path: Path, caplog) -> None:
    class ToolPlugin(_BasePlugin):
        def initialize(
            self,
            register: PluginCapabilityRegistry,
            plugin_root: Path,
            host: PluginHostContext,
        ) -> None:
            _ = plugin_root, host

            def broken(_tool_manager) -> None:
                raise RuntimeError("tool failed")

            register.register_llm_tool(broken)

    manager = PluginManager(plugin_data_root=tmp_path)
    manager.register_plugin_class(ToolPlugin)

    with caplog.at_level(logging.ERROR):
        manager.apply_llm_tools(object())  # type: ignore[arg-type]

    assert "apply_llm_tools failed" in caplog.text


def test_load_manifest_file_accepts_json_and_yaml(tmp_path: Path) -> None:
    manager = PluginManager(plugin_data_root=tmp_path)
    json_path = tmp_path / "plugins.json"
    yaml_path = tmp_path / "plugins.yaml"
    json_path.write_text(
        json.dumps(
            [
                {
                    "entry": "sdk.plugin:PluginBase",
                    "enabled": False,
                    "note": "kept as descriptor extra",
                }
            ]
        ),
        encoding="utf-8",
    )
    yaml_path.write_text("- entry: sdk.plugin:PluginBase\n  enabled: false\n", encoding="utf-8")

    manager.load_manifest_file(json_path)
    manager.load_manifest_file(yaml_path)

    assert list(manager.iter_plugin_ids()) == []


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ('{"entry": "not-a-list"}', "Plugin manifest must be a list"),
        ("[42]", "Each manifest item must be a mapping"),
        ('[{"enabled": true}]', "Manifest item missing string 'entry'"),
    ],
)
def test_load_manifest_file_rejects_invalid_shapes(
    tmp_path: Path, content: str, message: str
) -> None:
    manager = PluginManager(plugin_data_root=tmp_path)
    path = tmp_path / "plugins.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        manager.load_manifest_file(path)


def test_discovery_registry_validates_entries_and_deduplicates(caplog) -> None:
    registry = PluginDiscoveryRegistry()
    registry.register_class(_DemoPlugin)
    registry.register_class(_DemoPlugin)
    registry.register_class(_DemoPlugin, enabled=False)
    registry.register_entry("missing.module:Plugin")

    with caplog.at_level(logging.ERROR):
        classes = list(registry.iter_enabled_classes())

    assert classes == [_DemoPlugin]
    assert "Skipping plugin manifest entry" in caplog.text

    with pytest.raises(TypeError):
        registry.register_class(object)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        registry.register_entry("   ")
