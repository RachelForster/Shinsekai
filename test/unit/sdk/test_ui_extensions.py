"""Unit tests for workspace UI extension SDK contracts and locale loading."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sdk.manager import PluginManager
from sdk.register import PluginCapabilityRegistry
from sdk.types import (
    FrontendChatUIContribution,
    FrontendConfigAction,
    FrontendPageContribution,
    FrontendSectionContribution,
)
from sdk.ui_extensions import (
    PLUGIN_UI_ICONS,
    PLUGIN_WORKSPACE_ACTION_SLOTS,
    load_plugin_locales,
    validate_frontend_action_contribution,
    validate_frontend_page_contribution,
    validate_frontend_section_contribution,
)


def _registry(plugin_id: str = "demo.plugin") -> PluginCapabilityRegistry:
    reg = PluginCapabilityRegistry(SimpleNamespace(id=plugin_id, version="1.2.0"))
    reg.set_settings_ui_plugin_context(plugin_id, "1.2.0")
    return reg


def test_load_plugin_locales_reads_supported_json_files(tmp_path: Path) -> None:
    locales_dir = tmp_path / "locales"
    locales_dir.mkdir()
    (locales_dir / "zh_CN.json").write_text(json.dumps({"title": "狼人杀"}), encoding="utf-8")
    (locales_dir / "en.json").write_text(json.dumps({"title": "Werewolf"}), encoding="utf-8")
    (locales_dir / "fr.json").write_text(json.dumps({"title": "Ignored"}), encoding="utf-8")

    loaded = load_plugin_locales(locales_dir)

    assert loaded == {
        "zh_CN": {"title": "狼人杀"},
        "en": {"title": "Werewolf"},
    }
    assert load_plugin_locales(tmp_path / "missing") == {}


def test_validate_frontend_page_normalizes_unknown_icon() -> None:
    page = FrontendPageContribution(
        page_id="board",
        title="Game Board",
        entry="frontend/index.html",
        show_in_sidebar=True,
        nav_label="Board",
        nav_icon="unknown-icon",
    )
    normalized = validate_frontend_page_contribution(page, max_id_len=80)
    assert normalized.nav_icon == "puzzle"
    assert normalized.show_in_sidebar is True
    assert normalized.nav_label == "Board"

    gamepad = validate_frontend_page_contribution(
        FrontendPageContribution(page_id="board", title="Board", entry="frontend/index.html", nav_icon="gamepad"),
        max_id_len=80,
    )
    assert gamepad.nav_icon == "gamepad"


def test_workspace_action_slots_and_register_frontend_action() -> None:
    reg = _registry()
    for slot in sorted(PLUGIN_WORKSPACE_ACTION_SLOTS):
        reg.register_frontend_action(
            FrontendChatUIContribution(
                contribution_id=f"btn-{slot}",
                slot=slot,  # type: ignore[arg-type]
                title=f"Action {slot}",
                icon="wand",
                action=lambda ctx: {"message": ctx.page},
            )
        )
    assert len(reg.frontend_chat_ui_contributions) == len(PLUGIN_WORKSPACE_ACTION_SLOTS)

    with pytest.raises(ValueError, match="Unsupported frontend UI slot"):
        validate_frontend_action_contribution(
            FrontendChatUIContribution(contribution_id="x", slot="invalid-slot", title="Bad"),  # type: ignore[arg-type]
            max_id_len=80,
        )


def test_frontend_section_validation_and_collection() -> None:
    assert "gamepad" in PLUGIN_UI_ICONS
    reg = _registry()

    # Template body defaults cleanly to main, and preserves explicit sidebar slot
    reg.register_frontend_section(
        FrontendSectionContribution(
            section_id="werewolf-roles",
            page="template",
            slot="sidebar",
            title="Werewolf Roles",
            renderer="schema",
            schema=[{"id": "g", "title": "Group", "fields": []}],
            load_values=lambda ctx: {"enabled": True, "entity": ctx.entity_id},
            save_values=lambda vals, ctx: {"kind": "success", "message": "saved"},
            actions=[FrontendConfigAction(id="sync", label="Sync", run=lambda vals, ctx: "ok")],
        )
    )
    reg.register_frontend_section(
        FrontendSectionContribution(
            section_id="werewolf-panel",
            page="template",
            slot="body",
            title="Embedded Board",
            renderer="iframe",
            page_id="board",
            min_height=40,
            max_height=2000,
        )
    )

    sections = reg.frontend_section_contributions
    assert sections[0].slot == "sidebar"
    assert sections[1].slot == "main"
    assert sections[1].min_height == 80
    assert sections[1].max_height == 1600

    with pytest.raises(ValueError, match="Unsupported slot"):
        validate_frontend_section_contribution(
            FrontendSectionContribution(
                section_id="bad",
                page="api",
                slot="sidebar",
                title="Bad",
                load_values=lambda: {},
            ),
            max_id_len=80,
        )

    with pytest.raises(ValueError, match="callable load_values"):
        validate_frontend_section_contribution(
            FrontendSectionContribution(section_id="missing-loader", page="api", title="Bad"),
            max_id_len=80,
        )

    with pytest.raises(ValueError, match="page_id"):
        validate_frontend_section_contribution(
            FrontendSectionContribution(section_id="missing-page", page="character", title="Bad", renderer="iframe"),
            max_id_len=80,
        )

    manager = PluginManager()
    manager._capabilities = reg
    manager._instantiated = True
    manager._initialized = True
    collected = manager.collect_frontend_section_contributions()
    assert len(collected) == 2
    assert collected[0].plugin_id == "demo.plugin"
    assert collected[0].plugin_version == "1.2.0"
