from __future__ import annotations

from pathlib import Path

from sdk.manager import PluginManager
from sdk.plugin import PluginBase
from sdk.plugin_host_context import PluginHostContext
from sdk.register import PluginCapabilityRegistry
from sdk.types import ChatUIContribution, FrontendConfigContribution, FrontendPageContribution


def test_frontend_config_contribution_gets_plugin_context() -> None:
    registry = PluginCapabilityRegistry()
    registry.set_settings_ui_plugin_context("demo.plugin", "1.2.3")

    registry.register_frontend_config_page(
        FrontendConfigContribution(
            page_id="demo",
            title="Demo",
            schema=[],
            load_values=lambda: {"enabled": True},
            save_values=lambda values: None,
        )
    )

    contribution = registry.frontend_config_contributions[0]
    assert contribution.plugin_id == "demo.plugin"
    assert contribution.plugin_version == "1.2.3"
    assert contribution.load_values() == {"enabled": True}


def test_chat_ui_contribution_gets_plugin_context() -> None:
    registry = PluginCapabilityRegistry()
    registry.set_settings_ui_plugin_context("demo.plugin", "1.2.3")

    registry.register_chat_ui_widget(
        ChatUIContribution(
            widget_id="demo.chat",
            placement="toolbar",
            build=lambda ctx: object(),
        )
    )

    contribution = registry.chat_ui_contributions[0]
    assert contribution.plugin_id == "demo.plugin"
    assert contribution.plugin_version == "1.2.3"


def test_frontend_page_contribution_gets_plugin_context() -> None:
    registry = PluginCapabilityRegistry()
    registry.set_settings_ui_plugin_context("demo.plugin", "1.2.3")

    registry.register_frontend_page(
        FrontendPageContribution(
            page_id="demo.frontend",
            title="Demo Frontend",
            entry="plugins/demo/frontend/dist/index.html",
        )
    )

    contribution = registry.frontend_page_contributions[0]
    assert contribution.plugin_id == "demo.plugin"
    assert contribution.plugin_version == "1.2.3"


def test_plugin_manager_collects_frontend_config_contributions(tmp_path: Path) -> None:
    saved: list[dict[str, object]] = []

    class DemoPlugin(PluginBase):
        @property
        def plugin_id(self) -> str:
            return "demo.plugin"

        @property
        def plugin_version(self) -> str:
            return "1.0.0"

        def initialize(
            self,
            register: PluginCapabilityRegistry,
            plugin_root: Path,
            host: PluginHostContext,
        ) -> None:
            _ = plugin_root, host
            register.register_frontend_config_page(
                FrontendConfigContribution(
                    page_id="demo",
                    title="Demo",
                    schema=[{"id": "main", "title": "Main", "fields": []}],
                    load_values=lambda: {"value": 1},
                    save_values=lambda values: saved.append(dict(values)),
                )
            )
            register.register_frontend_page(
                FrontendPageContribution(
                    page_id="demo.frontend",
                    title="Demo Frontend",
                    entry="plugins/demo/frontend/dist/index.html",
                )
            )

    manager = PluginManager(plugin_data_root=tmp_path)
    manager.register_plugin_class(DemoPlugin)
    manager.instantiate_all()
    manager.load_own_config_all()

    contributions = manager.collect_frontend_config_contributions()
    assert len(contributions) == 1
    assert contributions[0].plugin_id == "demo.plugin"
    assert contributions[0].plugin_version == "1.0.0"
    assert contributions[0].schema == [{"id": "main", "title": "Main", "fields": []}]

    contributions[0].save_values({"value": 2})
    assert saved == [{"value": 2}]

    frontend_pages = manager.collect_frontend_page_contributions()
    assert len(frontend_pages) == 1
    assert frontend_pages[0].plugin_id == "demo.plugin"
    assert frontend_pages[0].plugin_version == "1.0.0"
