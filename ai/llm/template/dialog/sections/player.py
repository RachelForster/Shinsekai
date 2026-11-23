"""Rules for a user-controlled cast member using the normal dialog schema."""

from collections.abc import Iterable
from dataclasses import dataclass

from config.schema import SELF_PERSONA_NAME, is_self_persona_name

from ...core import PROMPT_CATALOG, Section
from ...integrations.localization import (
    _target_voice_display_name,
    resolve_template_locale,
    translate_template,
)
from ..context import DialogTemplateContext


def format_self_persona_prompt(setting: str, *, locale: str = "zh_CN") -> str:
    cleaned = str(setting or "").strip()
    if not cleaned:
        return ""
    return PROMPT_CATALOG.translate(
        "dialog.self_persona_block",
        locale=locale,
        setting=cleaned,
    )


@dataclass(frozen=True)
class PlayerSection(Section[DialogTemplateContext]):
    id: str = "player"

    def _render_self(self, context: DialogTemplateContext) -> str:
        name = str(context.player_name or "").strip()
        character = context.player_character
        if not name or character is None:
            return format_self_persona_prompt(
                context.self_persona_setting,
                locale=context.locale,
            )

        setting = str(getattr(character, "character_setting", "") or "").strip()
        if context.uses_vibe:
            portrait_field = "vibe"
            portrait_value = context.translate("player_portrait_vibe_value")
            speech_media = '"vibe":""'
        else:
            portrait_field = "sprite"
            portrait_value = "01"
            speech_media = '"sprite":"-1"'

        if context.allow_player_dialogue:
            return context.translate(
                "player_ai_control",
                name=name,
                setting=setting,
                portrait_field=portrait_field,
                portrait_value=portrait_value,
            )

        speech_contract = (
            context.translate(
                "player_speech_contract",
                name=name,
                speech_media=speech_media,
                target_voice_name=context.target_voice_name,
            )
            if context.read_player_speech
            else context.translate("player_speech_disabled", name=name)
        )
        return context.translate(
            "player_control",
            name=name,
            setting=setting,
            portrait_field=portrait_field,
            portrait_value=portrait_value,
            speech_contract=speech_contract,
        )


def player_runtime_prompt(
    config, name: str, *, allow_dialogue: bool, read_speech: bool,
    media_selection_mode: str, character_names: Iterable[str] | None = None,
) -> str:
    """Apply current player options without rewriting an older authored template."""
    locale = resolve_template_locale(config)
    if not name:
        if any(is_self_persona_name(ch) for ch in (character_names or ())):
            return ""
        getter = getattr(config, "get_character_by_name", None)
        self_char = getter(SELF_PERSONA_NAME) if callable(getter) else None
        if self_char is not None and is_self_persona_name(getattr(self_char, "name", "")):
            setting = str(getattr(self_char, "character_setting", "") or "").strip()
            if setting:
                return format_self_persona_prompt(setting, locale=locale)
        return ""
    character = config.get_character_by_name(name)
    if character is None:
        return ""

    def _translate(key: str, **kwargs) -> str:
        return translate_template(key, locale=locale, **kwargs)

    context = DialogTemplateContext(
        characters=(),
        translate=_translate,
        target_voice_name=_target_voice_display_name(config, _translate),
        json_reminder="",
        locale=locale,
        player_name=name,
        player_character=character,
        allow_player_dialogue=allow_dialogue,
        read_player_speech=read_speech,
        media_selection_mode=media_selection_mode,
    )
    return _translate("player_runtime_override") + PlayerSection().render(context)
