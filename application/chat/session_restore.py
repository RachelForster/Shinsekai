"""Restore the last persisted scene into the framework-neutral presentation pipeline."""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

from application.chat.dialog_media import SpriteLookupRequest, SpriteLookupStrategy
from application.chat.history_state import extract_valid_dialog_from_messages
from config.config_manager import ConfigManager
from core.messaging.dialog_tokens import is_option_history_name
from sdk.messages import LLMDialogMessage, PresentationMessage


def _last_character_dialog(messages: list) -> dict[str, Any] | None:
    dialog = list(extract_valid_dialog_from_messages(messages))
    if dialog and is_option_history_name(dialog[-1].get("character_name", "")):
        dialog.pop()
    while dialog and dialog[-1].get("sprite", "-1") in {"-1", -1}:
        if is_option_history_name(dialog[-1].get("character_name", "")):
            break
        dialog.pop()
    return dialog[-1] if dialog else None


def _resolve_dialog_sprite(
    item: dict[str, Any],
    *,
    config: ConfigManager,
    sprite_lookup_strategy: SpriteLookupStrategy | None,
    character_name_converter: Callable[[str], str] | None,
) -> tuple[str, str | int]:
    raw_name = str(item.get("character_name", ""))
    asset_id = item.get("sprite", "-1")
    if sprite_lookup_strategy is None:
        return raw_name, asset_id
    try:
        character_name = (
            character_name_converter(raw_name)
            if character_name_converter is not None
            else raw_name
        )
        character = config.get_character_by_name(character_name)
        if character is None:
            return raw_name, asset_id
        message = LLMDialogMessage.model_validate(item)
        match = sprite_lookup_strategy.lookup(
            SpriteLookupRequest(character=character, message=message)
        )
        return character_name, match.asset_id
    except Exception:
        return raw_name, asset_id


def replay_latest_dialog_sprite(
    messages: list,
    *,
    presentation_queue: Any,
    config: ConfigManager,
    sprite_lookup_strategy: SpriteLookupStrategy | None,
    character_name_converter: Callable[[str], str] | None = None,
) -> bool:
    """Resolve the last character sprite without replaying its text."""
    last = _last_character_dialog(messages)
    if last is None:
        return False
    character_name, asset_id = _resolve_dialog_sprite(
        last,
        config=config,
        sprite_lookup_strategy=sprite_lookup_strategy,
        character_name_converter=character_name_converter,
    )
    presentation_queue.put(
        PresentationMessage(
            audio_path="",
            character_name=character_name,
            speech="",
            sprite=asset_id,
            is_system_message=False,
            timeout=0,
        )
    )
    return True


def restore_session_presentation(
    messages: list,
    *,
    presentation_queue: Any,
    presenter: Any,
    config: ConfigManager,
    tr_i18n: Callable[..., str],
    sprite_lookup_strategy: SpriteLookupStrategy | None = None,
    character_name_converter: Callable[[str], str] | None = None,
) -> bool:
    """Re-queue the last dialog, BGM, and background after loading history."""

    def _tr(key: str, **kwargs: Any) -> str:
        return tr_i18n(key, **kwargs) if kwargs else tr_i18n(key)

    try:
        bgm_path = config.config.system_config.bgm_path
        bg_path = config.config.system_config.background_path
        if bgm_path:
            presentation_queue.put(
                PresentationMessage(
                    audio_path=bgm_path,
                    character_name="bgm",
                    sprite="-1",
                    is_system_message=True,
                )
            )
        if bg_path:
            presenter.setBackgroundImage(bg_path)
    except Exception as exc:
        print(_tr("main.print_bg_fail", e=str(exc)))
        traceback.print_exc()

    if not messages:
        return False

    try:
        dialog = extract_valid_dialog_from_messages(messages)
        if not dialog:
            raise ValueError(_tr("main.err_no_valid_dialog"))

        last_choice: dict | None = None
        if dialog and is_option_history_name(dialog[-1].get("character_name", "")):
            last_choice = dialog.pop()

        trailing_system: list = []
        while dialog and dialog[-1].get("sprite", "-1") in {"-1", -1}:
            if is_option_history_name(dialog[-1].get("character_name", "")):
                break
            trailing_system.append(dialog.pop())

        for item in reversed(trailing_system):
            presentation_queue.put(
                PresentationMessage(
                    audio_path="",
                    character_name=item.get("character_name", ""),
                    speech=item.get("speech"),
                    sprite="-1",
                    is_system_message=True,
                )
            )

        restored_character_sprite = False
        if dialog:
            last = dialog[-1]
            character_name, asset_id = _resolve_dialog_sprite(
                last,
                config=config,
                sprite_lookup_strategy=sprite_lookup_strategy,
                character_name_converter=character_name_converter,
            )
            presentation_queue.put(
                PresentationMessage(
                    audio_path="",
                    character_name=character_name,
                    speech=last.get("speech", ""),
                    sprite=asset_id,
                    is_system_message=False,
                    timeout=0,
                )
            )
            restored_character_sprite = True

        if last_choice is not None:
            presentation_queue.put(
                PresentationMessage(
                    audio_path="",
                    name=last_choice.get("character_name", "CHOICE"),
                    text=last_choice.get("speech", ""),
                    sprite="-1",
                    is_system_message=True,
                )
            )
        return restored_character_sprite
    except Exception as exc:
        traceback.print_exc()
        print(_tr("main.print_restore_fail", e=str(exc)))
        return False
