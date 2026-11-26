"""Backward-compatible application facade for Composite dialog templates.

Configuration and plugin discovery stay at this boundary; rendering lives in
``ai.llm.template`` and receives an explicit context. Existing import paths,
method signatures and the ``(template, warning)`` result remain supported.
"""

from typing import Any

from config.config_manager import ConfigManager, character_name_key
from config.schema import (
    SELF_PERSONA_NAME,
    find_self_persona,
    is_self_persona,
    is_self_persona_id,
    is_self_persona_name,
)
from core.messaging.formats.registry import resolve_dialog_format
from sdk.adapters.dialog_format import DEFAULT_DIALOG_FORMAT_ID, XML_DIALOG_FORMAT_ID
from sdk.types import OutputContractPatch

from .template.dialog import DialogTemplateContext, DialogTemplateSection
from .template.integrations.characters import (
    resolve_chat_template_characters as _resolve_characters,
)
from .template.integrations.localization import (
    TRANSPARENT_BG,
    _target_voice_display_name as _voice_display_name,
    _ui_voice_same_lang as _same_voice_language,
    is_transparent_background,
    resolve_template_locale,
    translate_template,
)
from .template.integrations.tools import format_llm_tools_block


config_manager = ConfigManager()
DEFAULT_DIALOG_CONTRACT_ID = "default.dialog.v1"


def _T(key: str, **kwargs) -> str:
    return translate_template(key, config_manager=config_manager, **kwargs)


_DEFAULT_T = _T


def no_valid_characters_message() -> str:
    return _T("err_no_characters")


class NoValidCharactersError(ValueError):
    """Raised when template generation has no resolvable character."""

    error_code = "no_valid_characters"

    def __init__(self) -> None:
        super().__init__(no_valid_characters_message())


def resolve_chat_template_characters(
    selected_characters: Any,
    manager: Any = None,
) -> list[tuple[str, Any]]:
    return _resolve_characters(
        selected_characters,
        config_manager if manager is None else manager,
    )


def _render_template_keys(*keys: str, locale: str | None = None) -> str:
    if locale is not None and _T is _DEFAULT_T:
        return "\n".join(translate_template(key, locale=locale).strip() for key in keys)
    return "\n".join(_T(key).strip() for key in keys)


def format_reminder(
    output_format_id: str = DEFAULT_DIALOG_FORMAT_ID,
    *,
    locale: str | None = None,
) -> str:
    """Close system prompts with the active output-format and tool protocol rules."""
    resolved = resolve_dialog_format(output_format_id)
    fmt_id = resolved.format_id
    if fmt_id not in (DEFAULT_DIALOG_FORMAT_ID, XML_DIALOG_FORMAT_ID):
        resolved_locale = (
            locale if locale is not None else resolve_template_locale(config_manager)
        )
        custom = resolved.render_format_reminder(locale=resolved_locale)
        protocol = _render_template_keys("closing_custom_tool_protocol", locale=locale)
        if isinstance(custom, str) and custom.strip():
            return f"{custom.strip()}\n{protocol}"
        return _render_template_keys(
            "closing_custom_reminder",
            "closing_custom_tool_protocol",
            locale=locale,
        )
    if fmt_id == XML_DIALOG_FORMAT_ID:
        return _render_template_keys(
            "closing_xml_reminder",
            "closing_xml_tool_protocol",
            locale=locale,
        )
    return _render_template_keys(
        "closing_json_reminder",
        "closing_tool_protocol",
        locale=locale,
    )


def json_format_reminder(*, locale: str | None = None) -> str:
    """Close system prompts with the output format and tool protocol rules."""
    return _render_template_keys(
        "closing_json_reminder",
        "closing_tool_protocol",
        locale=locale,
    )


def _format_llm_tools_block() -> str:
    return format_llm_tools_block(_T)


def _format_llm_tools_block_for_format(output_format_id: str) -> str:
    if output_format_id == DEFAULT_DIALOG_FORMAT_ID:
        return _format_llm_tools_block()
    intro_key = (
        "xml_tools_intro"
        if output_format_id == XML_DIALOG_FORMAT_ID
        else "custom_tools_intro"
    )

    def _format_translate(key: str, **kwargs: Any) -> str:
        if key == "tools_intro":
            return _T(intro_key, **kwargs)
        return _T(key, **kwargs)

    return format_llm_tools_block(_format_translate)


def _ui_voice_same_lang(characters=None) -> bool:
    return _same_voice_language(config_manager, characters=characters)


def _target_voice_display_name(characters=None) -> str:
    return _voice_display_name(config_manager, _T, characters=characters)


class TemplateGenerator:
    def __init__(
        self,
        output_contract_patches: list[OutputContractPatch] | None = None,
    ) -> None:
        self._output_contract_patches = output_contract_patches

    def _get_output_contract_patches(self) -> list[OutputContractPatch]:
        if self._output_contract_patches is not None:
            return list(self._output_contract_patches)
        try:
            from plugin_system.host import get_plugin_output_contract_patches

            return get_plugin_output_contract_patches(DEFAULT_DIALOG_CONTRACT_ID)
        except Exception:
            return []

    def resolve_chat_template_characters(
        self,
        selected_characters: Any,
    ) -> list[tuple[str, Any]]:
        return resolve_chat_template_characters(selected_characters)

    def generate_chat_template(
        self,
        selected_characters,
        bg_name,
        use_effect,
        use_cg,
        use_llm_translation,
        use_cot=False,
        use_choice=True,
        use_narration=True,
        use_stat=True,
        max_speech_chars: int = 0,
        max_dialog_items: int = 0,
        primary_characters: Any = None,
        media_selection_mode: str = "indexed",
        player_character: str = "",
        read_player_speech: bool = False,
        allow_player_dialogue: bool = True,
        output_format: str = DEFAULT_DIALOG_FORMAT_ID,
    ):
        if not selected_characters:
            raise NoValidCharactersError()
        characters = self.resolve_chat_template_characters(selected_characters)
        cleaned_player_arg = str(player_character or "").strip()
        player = next(
            (
                character
                for name, character in characters
                if character_name_key(name) == character_name_key(cleaned_player_arg)
                or (
                    (is_self_persona_name(cleaned_player_arg) or is_self_persona_id(cleaned_player_arg))
                    and is_self_persona(character)
                )
            ),
            None,
        )
        if player is None and cleaned_player_arg and (
            is_self_persona_name(cleaned_player_arg) or is_self_persona_id(cleaned_player_arg)
        ):
            getter_self = getattr(config_manager, "get_self_persona", None)
            candidate = getter_self() if callable(getter_self) else None
            if candidate is None:
                getter = getattr(config_manager, "get_character_by_name", None)
                candidate = getter(SELF_PERSONA_NAME) if callable(getter) else None
            if candidate is not None and is_self_persona(candidate):
                player = candidate
        resolved_player_name = (
            str(getattr(player, "name", "") or cleaned_player_arg).strip()
            if player is not None
            else ""
        )
        if player is not None and not allow_player_dialogue:
            player_is_self = is_self_persona(player)
            resolved_player_key = character_name_key(resolved_player_name)
            characters = [
                (name, character)
                for name, character in characters
                if not (
                    is_self_persona(character)
                    if player_is_self
                    else character_name_key(name) == resolved_player_key
                )
            ]
        if not characters and player is None:
            raise NoValidCharactersError()
        has_self_in_cast = any(is_self_persona(character) for _name, character in characters)
        self_persona_setting = ""
        self_persona_name = ""
        if not cleaned_player_arg and player is None and not has_self_in_cast:
            getter_self = getattr(config_manager, "get_self_persona", None)
            self_char = getter_self() if callable(getter_self) else None
            if self_char is None:
                chars = getattr(getattr(config_manager, "config", None), "characters", None)
                if chars is not None:
                    self_char = find_self_persona(chars)
            if self_char is None:
                getter = getattr(config_manager, "get_character_by_name", None)
                self_char = getter(SELF_PERSONA_NAME) if callable(getter) else None
            if self_char is not None and is_self_persona(self_char):
                self_persona_setting = str(getattr(self_char, "character_setting", "") or "").strip()
                self_persona_name = str(getattr(self_char, "name", "") or "").strip()
        has_background = bool(bg_name) and not is_transparent_background(bg_name)
        resolved_locale = resolve_template_locale(config_manager)
        resolved_format = resolve_dialog_format(output_format).format_id
        voice_characters = list(characters)
        if (
            player is not None
            and read_player_speech
            and not any(
                character_name_key(name) == character_name_key(resolved_player_name)
                for name, _character in voice_characters
            )
        ):
            voice_characters.append((resolved_player_name, player))
        context = DialogTemplateContext(
            characters=tuple(characters),
            translate=_T,
            target_voice_name=_target_voice_display_name(characters=voice_characters),
            json_reminder=format_reminder(resolved_format),
            locale=resolved_locale,
            player_name=resolved_player_name,
            player_character=player,
            self_persona_setting=self_persona_setting,
            self_persona_name=self_persona_name,
            read_player_speech=bool(read_player_speech and player is not None),
            allow_player_dialogue=allow_player_dialogue,
            primary_character_names=(
                None
                if primary_characters is None
                else frozenset(
                    name
                    for name, _character in self.resolve_chat_template_characters(
                        primary_characters
                    )
                )
            ),
            tools_block=_format_llm_tools_block_for_format(resolved_format),
            background=(
                config_manager.get_background_by_name(bg_name)
                if has_background
                else None
            ),
            has_real_background=has_background,
            output_contract_patches=tuple(self._get_output_contract_patches()),
            use_effect=use_effect,
            use_cg=use_cg,
            use_llm_translation=bool(use_llm_translation and not _ui_voice_same_lang(characters=voice_characters)),
            use_cot=use_cot,
            use_choice=use_choice,
            use_narration=use_narration,
            use_stat=use_stat,
            max_speech_chars=max_speech_chars,
            max_dialog_items=max_dialog_items,
            media_selection_mode=(
                "semantic" if media_selection_mode == "semantic" else "indexed"
            ),
            output_format_id=resolved_format,
        )
        return DialogTemplateSection().render(context), ""
