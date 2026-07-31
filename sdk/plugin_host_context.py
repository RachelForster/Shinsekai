"""
Curated, read-only surfaces for third-party plugins.

Plugins run in-process and are not a security boundary; the goal is to avoid
handing out :class:`~config.config_manager.ConfigManager` or full
:class:`~ui.settings_ui.context.SettingsUIContext`, which allow mutating API keys,
saving YAML, and accessing every manager.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

from sdk.path_contract import (
    project_root,
    resolve_managed_project_path,
    resolve_project_output_path,
    validate_exact_path_text,
)


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
    huggingface_cache_dir: Path

    @classmethod
    def from_config_manager(
        cls,
        cm: Any | None,
        *,
        project_data_dir: str | os.PathLike[str] | None = None,
    ) -> PluginHostContext:
        configured_value = os.fspath(
            project_root() / "data"
            if project_data_dir is None
            else project_data_dir
        )
        validate_exact_path_text(
            configured_value,
            field="project_data_dir",
        )
        configured_data_dir = Path(configured_value)
        if not configured_data_dir.is_absolute():
            raise ValueError("project_data_dir must be absolute")
        data_dir = resolve_managed_project_path(
            configured_value,
            root=configured_data_dir.parent,
        )
        if cm is None:
            return cls(
                ui_language="zh_CN",
                voice_language="ja",
                base_font_size_px=56,
                theme_color="rgba(50,50,50,200)",
                selected_llm_provider="",
                tts_provider="",
                live_room_id="",
                project_data_dir=data_dir,
                huggingface_cache_dir=resolve_managed_project_path(
                    data_dir / "cache" / "huggingface",
                    root=data_dir.parent,
                ),
            )
        cfg = cm.config
        sys = cfg.system_config
        api = cfg.api_config
        raw_hf_cache = str(
            getattr(sys, "huggingface_cache_dir", "")
            or "data/cache/huggingface"
        )
        hf_cache = resolve_project_output_path(
            raw_hf_cache,
            root=data_dir.parent,
        )
        return cls(
            ui_language=str(sys.ui_language),
            voice_language=str(sys.voice_language),
            base_font_size_px=int(sys.base_font_size_px),
            theme_color=str(sys.theme_color),
            selected_llm_provider=str(api.llm_provider),
            tts_provider=str(api.tts_provider),
            live_room_id=str(sys.live_room_id),
            project_data_dir=data_dir,
            huggingface_cache_dir=hf_cache,
        )


@dataclass(frozen=True)
class PluginSettingsUIContext:
    """Deprecated context retained only for old Qt contribution imports.

    The current host does not construct this context or invoke legacy Qt
    contribution builders. It remains importable so older plugins can load.
    """

    host: PluginHostContext
    template_dir_path: str
    history_dir: str
    character_names: tuple[str, ...]
    background_names: tuple[str, ...]

    @classmethod
    def from_settings_ui_context(cls, ctx: Any) -> PluginSettingsUIContext:
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
