"""Backward-compatible application facade for Composite dialog templates.

Configuration and plugin discovery stay at this boundary; rendering lives in
``ai.llm.template`` and receives an explicit context. Existing import paths,
method signatures and the ``(template, warning)`` result remain supported.
"""

from typing import Any

from config.config_manager import ConfigManager
from i18n import tr as tr_i18n
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
)
from .template.integrations.tools import format_llm_tools_block


config_manager = ConfigManager()
DEFAULT_DIALOG_CONTRACT_ID = "default.dialog.v1"


def _T(key: str, **kwargs) -> str:
    return tr_i18n(f"template_gen.{key}", **kwargs)


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


def json_format_reminder() -> str:
    """Localized reminder that must close every runtime system prompt."""
    return _T("closing_json_reminder").strip()


def _format_llm_tools_block() -> str:
    return format_llm_tools_block(_T)


def _ui_voice_same_lang() -> bool:
    return _same_voice_language(config_manager)


def _target_voice_display_name() -> str:
    return _voice_display_name(config_manager, _T)


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
    ):
        if not selected_characters:
            raise NoValidCharactersError()
        characters = self.resolve_chat_template_characters(selected_characters)
        if not characters:
            raise NoValidCharactersError()
        has_background = bool(bg_name) and not is_transparent_background(bg_name)
        context = DialogTemplateContext(
            characters=tuple(characters),
            translate=_T,
            target_voice_name=_target_voice_display_name(),
            json_reminder=json_format_reminder(),
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
            tools_block=_format_llm_tools_block(),
            background=(
                config_manager.get_background_by_name(bg_name)
                if has_background
                else None
            ),
            has_real_background=has_background,
            output_contract_patches=tuple(self._get_output_contract_patches()),
            use_effect=use_effect,
            use_cg=use_cg,
            use_llm_translation=bool(use_llm_translation and not _ui_voice_same_lang()),
            use_cot=use_cot,
            use_choice=use_choice,
            use_narration=use_narration,
            use_stat=use_stat,
            max_speech_chars=max_speech_chars,
            max_dialog_items=max_dialog_items,
        )
        return DialogTemplateSection().render(context), ""
