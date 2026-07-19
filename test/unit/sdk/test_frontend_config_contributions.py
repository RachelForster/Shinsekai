from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sdk.manager import PluginManager
from sdk.plugin import PluginBase
from sdk.plugin_host_context import PluginHostContext
from sdk.register import PluginCapabilityRegistry
from sdk.types import (
    ChatUIContribution,
    FrontendChatUIContribution,
    FrontendConfigAction,
    FrontendConfigContribution,
    FrontendPageContribution,
)


def test_plugin_host_context_exposes_huggingface_cache_dir(tmp_path: Path) -> None:
    cache_dir = tmp_path / "hf-cache"
    cm = SimpleNamespace(
        config=SimpleNamespace(
            api_config=SimpleNamespace(llm_provider="Deepseek", tts_provider="gpt-sovits"),
            system_config=SimpleNamespace(
                base_font_size_px=56,
                huggingface_cache_dir=str(cache_dir),
                live_room_id="",
                theme_color="#d4788e",
                ui_language="zh_CN",
                voice_language="ja",
            ),
        )
    )

    host = PluginHostContext.from_config_manager(cm)

    assert host.huggingface_cache_dir == cache_dir.resolve(strict=False)


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


def test_frontend_config_contribution_keeps_i18n_payload() -> None:
    from frontend_bridge_core.plugin_ui import _frontend_config_page_payload

    contribution = FrontendConfigContribution(
        page_id="demo",
        title="Demo",
        description="Default description",
        restart_hint="Restart required",
        schema=[
            {
                "fields": [
                    {
                        "key": "enabled",
                        "label": "Enabled",
                        "options": [{"label": "Yes", "value": "yes"}],
                        "type": "select",
                    }
                ],
                "id": "main",
                "title": "Main",
            }
        ],
        i18n={
            "zh_CN": {
                "description": "默认说明",
                "groups": {
                    "main": {
                        "fields": {
                            "enabled": {
                                "label": "启用",
                                "options": {"yes": "是"},
                            }
                        },
                        "title": "主要",
                    }
                },
                "restartHint": "需要重启",
                "title": "演示",
            }
        },
        load_values=lambda: {"enabled": "yes"},
        save_values=lambda values: None,
    )

    payload = _frontend_config_page_payload(contribution)

    assert payload["i18n"]["zh_CN"]["title"] == "演示"
    assert payload["i18n"]["zh_CN"]["groups"]["main"]["fields"]["enabled"]["label"] == "启用"
    assert payload["values"] == {"enabled": "yes"}


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


def test_frontend_chat_ui_contribution_gets_plugin_context_and_validates_slots() -> None:
    registry = PluginCapabilityRegistry()
    registry.set_settings_ui_plugin_context("demo.plugin", "1.2.3")
    registry.register_frontend_chat_ui(
        FrontendChatUIContribution(
            contribution_id="demo.action",
            slot="chat-dialog-actions",
            title="Demo action",
            action=lambda: "done",
        )
    )

    contribution = registry.frontend_chat_ui_contributions[0]
    assert contribution.plugin_id == "demo.plugin"
    assert contribution.plugin_version == "1.2.3"
    assert contribution.action() == "done"

    with pytest.raises(ValueError, match="requires a non-empty id and title"):
        registry.register_frontend_chat_ui(
            FrontendChatUIContribution(contribution_id="", slot="chat-output", title="Missing")
        )


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


def test_frontend_config_contribution_stores_actions() -> None:
    """FrontendConfigContribution preserves action metadata and callbacks."""
    call_args: list[object] = []

    def _record(values: object) -> None:
        call_args.append(values)

    action = FrontendConfigAction(
        id="refresh",
        label="Refresh",
        description="Reload configuration",
        variant="primary",
        confirm="Are you sure?",
        order=50.0,
        run=_record,
    )

    contribution = FrontendConfigContribution(
        page_id="demo",
        title="Demo",
        schema=[{"id": "main", "title": "Main", "fields": []}],
        load_values=lambda: {"key": "val"},
        save_values=lambda values: None,
        actions=[action],
    )

    assert len(contribution.actions) == 1
    assert contribution.actions[0].id == "refresh"
    assert contribution.actions[0].label == "Refresh"
    assert contribution.actions[0].variant == "primary"
    assert contribution.actions[0].confirm == "Are you sure?"

    contribution.actions[0].run({"key": "test"})
    assert call_args == [{"key": "test"}]


def test_frontend_config_contribution_default_empty_actions() -> None:
    """FrontendConfigContribution has an empty actions list by default."""
    contribution = FrontendConfigContribution(
        page_id="demo",
        title="Demo",
        schema=[],
        load_values=lambda: {},
        save_values=lambda values: None,
    )
    assert contribution.actions == []
