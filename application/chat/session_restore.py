"""Restore the last persisted scene into the framework-neutral presentation pipeline."""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

from config.config_manager import ConfigManager
from core.messaging.dialog_tokens import is_option_history_name
from application.chat.history_state import extract_valid_dialog_from_messages
from sdk.messages import PresentationMessage


def restore_session_presentation(
    messages: list,
    *,
    presentation_queue: Any,
    presenter: Any,
    config: ConfigManager,
    tr_i18n: Callable[..., str],
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
            presentation_queue.put(
                PresentationMessage(
                    audio_path="",
                    character_name=last.get("character_name", ""),
                    speech=last.get("speech", ""),
                    sprite=last.get("sprite", "-1"),
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
