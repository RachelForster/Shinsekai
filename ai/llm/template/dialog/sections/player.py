"""Rules for a user-controlled cast member using the normal dialog schema."""

from collections.abc import Iterable
from dataclasses import dataclass
import re

from config.schema import (
    SELF_PERSONA_NAME,
    find_self_persona,
    is_self_persona,
    is_self_persona_id,
    is_self_persona_name,
)
from core.messaging.formats.registry import resolve_dialog_format
from sdk.adapters.dialog_format import (
    DEFAULT_DIALOG_FORMAT_ID,
    DialogPlayerHintContext,
    XML_DIALOG_FORMAT_ID,
)

from ...core import PROMPT_CATALOG, Section
from ...integrations.localization import (
    _target_voice_display_name,
    resolve_template_locale,
    translate_template,
)
from ..context import DialogTemplateContext


_SELF_PERSONA_SENTINEL = "__SELF_PERSONA_SETTING_PLACEHOLDER__"
_SELF_PERSONA_NAME_SENTINEL = "__SELF_PERSONA_NAME_PLACEHOLDER__"


def format_self_persona_prompt(
    setting: str,
    *,
    locale: str = "zh_CN",
    name: str = "",
) -> str:
    cleaned = str(setting or "").strip()
    if not cleaned:
        return ""
    cleaned_name = str(name or "").strip()
    if cleaned_name and not is_self_persona_name(cleaned_name):
        return PROMPT_CATALOG.translate(
            "dialog.self_persona_block_named",
            locale=locale,
            name=cleaned_name,
            setting=cleaned,
        )
    return PROMPT_CATALOG.translate(
        "dialog.self_persona_block",
        locale=locale,
        setting=cleaned,
    )


def strip_self_persona_block(text: str) -> str:
    """Remove persisted background-only self-persona prohibitions from legacy prompts."""
    if not text:
        return text
    cleaned = text
    changed = False
    for key in ("dialog.self_persona_block", "dialog.self_persona_block_named"):
        for locale in ("zh_CN", "en", "ja"):
            kwargs = {"setting": _SELF_PERSONA_SENTINEL}
            if key == "dialog.self_persona_block_named":
                kwargs["name"] = _SELF_PERSONA_NAME_SENTINEL
            sample = PROMPT_CATALOG.translate(key, locale=locale, **kwargs)
            prefix, sep, suffix = sample.partition(_SELF_PERSONA_SENTINEL)
            if not sep:
                continue
            head = prefix.strip()
            tail = suffix.strip()
            if not head or not tail:
                continue
            head_re = re.escape(head).replace(re.escape(_SELF_PERSONA_NAME_SENTINEL), r"[^\n]+?")
            tail_re = re.escape(tail).replace(re.escape(_SELF_PERSONA_NAME_SENTINEL), r"[^\n]+?")
            pattern = re.compile(
                rf"[ \t]*{head_re}[\s\S]*?{tail_re}[ \t]*(?:\r?\n)*"
            )
            updated = pattern.sub("\n", cleaned)
            if updated != cleaned:
                cleaned = updated
                changed = True
    if not changed:
        return text
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip("\n")


def _resolve_self_persona(config) -> object | None:
    getter_self = getattr(config, "get_self_persona", None)
    if callable(getter_self):
        found = getter_self()
        if found is not None:
            return found
    characters = getattr(getattr(config, "config", None), "characters", None)
    if characters is not None:
        found = find_self_persona(characters)
        if found is not None:
            return found
    getter = getattr(config, "get_character_by_name", None)
    return getter(SELF_PERSONA_NAME) if callable(getter) else None


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
                name=context.self_persona_name,
            )

        raw_setting = str(getattr(character, "character_setting", "") or "").strip()
        if is_self_persona(character):
            note = context.translate("self_persona_identity_note").strip()
            setting = f"{note}\n{raw_setting}" if (note and raw_setting) else (raw_setting or note)
        else:
            setting = raw_setting
        format_id = (
            str(context.output_format_id or DEFAULT_DIALOG_FORMAT_ID).strip().lower()
        )
        is_xml = format_id == XML_DIALOG_FORMAT_ID
        if context.uses_vibe:
            portrait_field = "vibe"
            portrait_value = context.translate("player_portrait_vibe_value")
            speech_media = 'vibe=""' if is_xml else '"vibe":""'
        else:
            portrait_field = "sprite"
            portrait_value = "01"
            speech_media = 'sprite="-1"' if is_xml else '"sprite":"-1"'

        if format_id not in (DEFAULT_DIALOG_FORMAT_ID, XML_DIALOG_FORMAT_ID):
            fmt = resolve_dialog_format(format_id)
            custom_hint = fmt.render_player_hint(
                DialogPlayerHintContext(
                    locale=str(context.locale or "zh_CN"),
                    name=name,
                    setting=setting,
                    uses_vibe=bool(context.uses_vibe),
                    allow_player_dialogue=bool(context.allow_player_dialogue),
                    read_player_speech=bool(context.read_player_speech),
                    target_voice_name=str(context.target_voice_name or ""),
                    portrait_field=portrait_field,
                    portrait_value=portrait_value,
                )
            )
            if isinstance(custom_hint, str) and custom_hint.strip():
                return custom_hint

        if context.allow_player_dialogue:
            return context.translate(
                "xml_player_ai_control" if is_xml else "player_ai_control",
                name=name,
                setting=setting,
                portrait_field=portrait_field,
                portrait_value=portrait_value,
            )

        speech_contract = (
            context.translate(
                "xml_player_speech_contract" if is_xml else "player_speech_contract",
                name=name,
                speech_media=speech_media,
                target_voice_name=context.target_voice_name,
            )
            if context.read_player_speech
            else context.translate("player_speech_disabled", name=name)
        )
        return context.translate(
            "xml_player_control" if is_xml else "player_control",
            name=name,
            setting=setting,
            portrait_field=portrait_field,
            portrait_value=portrait_value,
            speech_contract=speech_contract,
        )


def player_runtime_prompt(
    config, name: str, *, allow_dialogue: bool, read_speech: bool,
    media_selection_mode: str, character_names: Iterable[str] | None = None,
    output_format: str = DEFAULT_DIALOG_FORMAT_ID,
) -> str:
    """Apply current player options without rewriting an older authored template."""
    locale = resolve_template_locale(config)
    self_char = _resolve_self_persona(config)
    self_char_name = str(getattr(self_char, "name", "") or "").strip()
    self_label = self_char_name or SELF_PERSONA_NAME

    def _is_self_ref(raw_name: str) -> bool:
        cleaned = str(raw_name or "").strip()
        if not cleaned:
            return False
        if is_self_persona_name(cleaned) or is_self_persona_id(cleaned):
            return True
        if self_char_name and cleaned.casefold() == self_char_name.casefold():
            return True
        getter = getattr(config, "get_character_by_name", None)
        resolved = getter(cleaned) if callable(getter) else None
        return resolved is not None and is_self_persona(resolved)

    has_self_in_cast = any(_is_self_ref(ch) for ch in (character_names or ()))
    if not name:
        if has_self_in_cast:
            return translate_template(
                "self_persona_cast_runtime_override",
                locale=locale,
                name=self_label,
            )
        if self_char is not None and is_self_persona(self_char):
            setting = str(getattr(self_char, "character_setting", "") or "").strip()
            if setting:
                return format_self_persona_prompt(
                    setting,
                    locale=locale,
                    name=self_label,
                )
        return ""
    getter = getattr(config, "get_character_by_name", None)
    character = getter(name) if callable(getter) else None
    player_block = ""
    if character is not None:
        canonical_player_name = str(getattr(character, "name", "") or name).strip() or name

        def _translate(key: str, **kwargs) -> str:
            return translate_template(key, locale=locale, **kwargs)

        context = DialogTemplateContext(
            characters=(),
            translate=_translate,
            target_voice_name=_target_voice_display_name(
                config,
                _translate,
                characters=[(canonical_player_name, character)],
            ),
            json_reminder="",
            locale=locale,
            player_name=canonical_player_name,
            player_character=character,
            allow_player_dialogue=allow_dialogue,
            read_player_speech=read_speech,
            media_selection_mode=media_selection_mode,
            output_format_id=output_format,
        )
        player_block = _translate("player_runtime_override") + PlayerSection().render(context)

    player_is_self = (character is not None and is_self_persona(character)) or _is_self_ref(name)
    if has_self_in_cast and not player_is_self:
        cast_override = translate_template(
            "self_persona_cast_runtime_override",
            locale=locale,
            name=self_label,
        )
        if player_block:
            return f"{player_block.rstrip()}{cast_override}"
        return cast_override
    return player_block
