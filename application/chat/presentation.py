"""Initial chat presentation and persisted scene restoration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ai.llm.template_generator import is_transparent_background
from application.chat.history_state import (
    get_history,
    history_entry_stage_payload,
)
from application.chat.initial_sprite import display_initial_sprite
from application.chat.session_restore import restore_session_presentation
from core.paths import resource_path


@dataclass(frozen=True, slots=True)
class ChatPresentationAssets:
    """Background and music resources selected for one chat session."""

    background_sprites: list[Any]
    bgm_paths: list[str]
    transparent: bool
    background: Any | None = None


class StreamingHistoryPresenter:
    """Adapt persisted history presentation calls to the streaming UI port."""

    def __init__(self, ui_updates: Any) -> None:
        self._ui_updates = ui_updates

    def setBackgroundImage(self, path: str) -> None:
        self._ui_updates.post_background(path)

    def setDisplayWords(self, text: str) -> None:
        post_dialog = getattr(self._ui_updates, "post_dialog_html", None)
        if post_dialog is None:
            return
        payload = history_entry_stage_payload(text)
        post_dialog(
            payload.get("fullHtml", text),
            append_history=False,
            speaker=str(payload.get("speaker") or ""),
            color=str(payload.get("color") or "#84C2D5"),
            is_system=bool(payload.get("isSystem")),
        )

    def setOptions(self, options: Any) -> None:
        self._ui_updates.post_options(list(options or []))


def load_presentation_assets(
    config: Any, background_name: str
) -> ChatPresentationAssets:
    """Resolve selected background media without making it startup-fatal."""

    transparent = is_transparent_background(background_name)
    if transparent:
        return ChatPresentationAssets([], [], True)
    try:
        background = config.get_background_by_name(background_name)
        return ChatPresentationAssets(
            background_sprites=list(getattr(background, "sprites", None) or []),
            bgm_paths=list(getattr(background, "bgm_list", None) or []),
            transparent=False,
            background=background,
        )
    except Exception:
        return ChatPresentationAssets([], [], False)


def prepare_initial_presentation(
    *,
    messages: list[Any],
    config: Any,
    ui_updates: Any,
    presentation_queue: Any | None,
    assets: ChatPresentationAssets,
    initial_sprite_path: str,
    welcome_html: str,
    initial_option: str,
    ready_notification: str,
    publish_branch_tree: Any,
    translate: Any,
) -> None:
    """Restore background, BGM, dialog, options, and initial character sprite."""

    resolved_sprite_path = str(initial_sprite_path or "")
    if not resolved_sprite_path and not assets.transparent:
        resolved_sprite_path = str(resource_path("assets/system/picture/shinsekai.png"))

    _persist_selected_background(config, assets)
    if assets.background_sprites:
        try:
            ui_updates.post_background(_asset_path(assets.background_sprites[0]))
        except Exception:
            pass
    ui_updates.switch_bgm(assets.bgm_paths[0] if assets.bgm_paths else "")

    restored_sprite = False
    if presentation_queue is not None:
        restored_sprite = restore_session_presentation(
            messages,
            presentation_queue=presentation_queue,
            presenter=StreamingHistoryPresenter(ui_updates),
            config=config,
            tr_i18n=translate,
        )

    if not messages:
        ui_updates.post_dialog_html(
            welcome_html,
            is_system=True,
            color="#84C2D5",
        )
        if len(get_history()) <= 1:
            ui_updates.post_options([initial_option])

    publish_branch_tree()
    ui_updates.post_notification(ready_notification)
    if not restored_sprite:
        display_initial_sprite(
            resolved_sprite_path,
            config=config,
            ui_updates=ui_updates,
        )


def _persist_selected_background(
    config: Any,
    assets: ChatPresentationAssets,
) -> None:
    system_config = config.config.system_config.model_copy(deep=True)
    if assets.background_sprites:
        system_config.bgm_path = assets.bgm_paths[0] if assets.bgm_paths else ""
        system_config.background_path = _asset_path(assets.background_sprites[0])
    else:
        system_config.bgm_path = ""
        system_config.background_path = ""
    config.config.system_config = system_config
    config.save_system_config()


def _asset_path(asset: Any) -> str:
    if isinstance(asset, dict):
        return str(asset.get("path") or "")
    return str(getattr(asset, "path", "") or "")
