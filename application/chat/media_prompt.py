"""Keep a restored generated prompt compatible with the selected media lookup."""

from __future__ import annotations

from typing import Any


_START = "\n\n<shinsekai_runtime_media_selection>\n"
_END = "\n</shinsekai_runtime_media_selection>"


def align_history_media_prompt(
    messages: list[Any],
    *,
    config: Any,
    character_names: list[str],
    mode: str,
    background_name: str = "",
) -> list[Any]:
    """Override only a mismatched generated media contract, without losing history."""
    result = messages
    for index, message in enumerate(result):
        if not isinstance(message, dict) or message.get("role") != "system":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        # A saved override belongs to the previous runtime. Rebuild it instead
        # of accumulating conflicting rules when the mode changes again.
        if _START in content and content.endswith(_END):
            content = content.rsplit(_START, 1)[0]
        conflicting_field = "sprite" if mode == "semantic" else "vibe"
        if f"- {conflicting_field} (string, required):" in content:
            from ai.llm.template.dialog.context import DialogTemplateContext
            from ai.llm.template.dialog.media_selection import (
                build_media_selection_section,
            )
            from ai.llm.template.integrations.localization import (
                is_transparent_background,
                translate_template,
            )

            characters = tuple(
                (name, character)
                for name in character_names
                if (character := config.get_character_by_name(name)) is not None
            )
            real_background = not is_transparent_background(background_name)
            context = DialogTemplateContext(
                characters=characters,
                translate=translate_template,
                target_voice_name="",
                json_reminder="",
                media_selection_mode=mode,
                has_real_background=real_background,
                background=(
                    config.get_background_by_name(background_name)
                    if real_background
                    else None
                ),
            )
            content += (
                _START + build_media_selection_section(context).render(context) + _END
            )
        if content != message.get("content"):
            if result is messages:
                result = list(messages)
            result[index] = {**message, "content": content}
    return result
