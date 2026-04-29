"""
Curated, read-only surfaces for third-party plugins.

Plugins run in-process and are not a security boundary; the goal is to avoid
handing out :class:`~config.config_manager.ConfigManager` or full
:class:`~ui.settings_ui.context.SettingsUIContext`, which allow mutating API keys,
saving YAML, and accessing every manager.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config.config_manager import ConfigManager
    from ui.settings_ui.context import SettingsUIContext


@dataclass(frozen=True)
class PluginHostContext:
    """
    Snapshot-safe view of app state for :meth:`sdk.plugin.PluginBase.initialize`.

    Contains **no** secrets (no API keys, tokens, or base URLs) and **no** handles
    to save/load global config.
    """

    ui_language: str
    voice_language: str
    base_font_size_px: int
    theme_color: str
    selected_llm_provider: str
    tts_provider: str
    live_room_id: str
    project_data_dir: Path

    @classmethod
    def from_config_manager(cls, cm: ConfigManager | None) -> PluginHostContext:
        if cm is None:
            return cls(
                ui_language="zh_CN",
                voice_language="ja",
                base_font_size_px=56,
                theme_color="rgba(50,50,50,200)",
                selected_llm_provider="",
                tts_provider="",
                live_room_id="",
                project_data_dir=Path("data"),
            )
        cfg = cm.config
        sys = cfg.system_config
        api = cfg.api_config
        return cls(
            ui_language=str(sys.ui_language),
            voice_language=str(sys.voice_language),
            base_font_size_px=int(sys.base_font_size_px),
            theme_color=str(sys.theme_color),
            selected_llm_provider=str(api.llm_provider),
            tts_provider=str(api.tts_provider),
            live_room_id=str(sys.live_room_id),
            project_data_dir=Path("data"),
        )


@dataclass(frozen=True)
class PluginSettingsUIContext:
    """
    What plugin-built Settings / Tools tabs may see: read-only host snapshot plus
    a few path and listing fields. No config managers or save APIs.
    """

    host: PluginHostContext
    template_dir_path: str
    history_dir: str
    character_names: tuple[str, ...]
    background_names: tuple[str, ...]

    @classmethod
    def from_settings_ui_context(cls, ctx: SettingsUIContext) -> PluginSettingsUIContext:
        host = PluginHostContext.from_config_manager(ctx.config_manager)
        cfg = ctx.config_manager.config
        characters = tuple(str(c.name) for c in cfg.characters)
        backgrounds = tuple(str(b.name) for b in cfg.background_list)
        return cls(
            host=host,
            template_dir_path=str(ctx.template_dir_path),
            history_dir=str(ctx.history_dir),
            character_names=characters,
            background_names=backgrounds,
        )
