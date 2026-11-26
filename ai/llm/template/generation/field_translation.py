"""Pure Composite prompt sections for character and background field translation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import json

from sdk.lang import normalize_lang

from ..core.context import TemplateContext
from ..core.prompt_spec import PromptLanguagePolicy, PromptSpec
from ..core.section import I18nSection, Section, TextSection


@dataclass(frozen=True)
class FieldTranslationPromptContext(TemplateContext):
    """Context for structured JSON field translation into the active UI locale."""

    payload_json: str = ""


def _target_params(ctx: FieldTranslationPromptContext) -> dict[str, str]:
    return {"target": ctx.tr("generation.field_translation_target_lang")}


def build_character_field_translation_system_section() -> (
    Section[FieldTranslationPromptContext]
):
    return I18nSection(
        "character_field_translation_system",
        key="generation.field_translation_character_system",
        params=_target_params,
    )


def build_background_field_translation_system_section() -> (
    Section[FieldTranslationPromptContext]
):
    return I18nSection(
        "background_field_translation_system",
        key="generation.field_translation_background_system",
        params=_target_params,
    )


def build_field_translation_user_section() -> Section[FieldTranslationPromptContext]:
    return TextSection(
        "field_translation_user",
        text=lambda ctx: ctx.payload_json,
    )


CHARACTER_FIELD_TRANSLATION_SPEC: PromptSpec[
    FieldTranslationPromptContext, FieldTranslationPromptContext
] = PromptSpec(
    id="generation.character_field_translation",
    language_policy=PromptLanguagePolicy.FOLLOW_UI,
    system_builder=build_character_field_translation_system_section,
    user_builder=build_field_translation_user_section,
)

BACKGROUND_FIELD_TRANSLATION_SPEC: PromptSpec[
    FieldTranslationPromptContext, FieldTranslationPromptContext
] = PromptSpec(
    id="generation.background_field_translation",
    language_policy=PromptLanguagePolicy.FOLLOW_UI,
    system_builder=build_background_field_translation_system_section,
    user_builder=build_field_translation_user_section,
)


def render_character_field_translation_prompts(
    *,
    ui_lang_code: str,
    name: str,
    emotion_block: str,
    character_setting: str,
) -> tuple[str, str]:
    payload_json = json.dumps(
        {
            "name": name,
            "emotion_block": emotion_block,
            "character_setting": character_setting,
        },
        ensure_ascii=False,
    )
    ctx = FieldTranslationPromptContext(
        locale=normalize_lang(ui_lang_code),
        payload_json=payload_json,
    )
    return (
        CHARACTER_FIELD_TRANSLATION_SPEC.render_system(ctx),
        CHARACTER_FIELD_TRANSLATION_SPEC.render_user(ctx),
    )


def render_background_field_translation_prompts(
    *,
    ui_lang_code: str,
    bg_name: str,
    bg_info: str,
    bgm_info: str,
    bgm_row_tags: Sequence[str],
) -> tuple[str, str]:
    payload_json = json.dumps(
        {
            "bg_name": bg_name,
            "bg_info": bg_info,
            "bgm_info": bgm_info,
            "bgm_row_tags": list(bgm_row_tags),
        },
        ensure_ascii=False,
    )
    ctx = FieldTranslationPromptContext(
        locale=normalize_lang(ui_lang_code),
        payload_json=payload_json,
    )
    return (
        BACKGROUND_FIELD_TRANSLATION_SPEC.render_system(ctx),
        BACKGROUND_FIELD_TRANSLATION_SPEC.render_user(ctx),
    )


__all__ = [
    "BACKGROUND_FIELD_TRANSLATION_SPEC",
    "CHARACTER_FIELD_TRANSLATION_SPEC",
    "FieldTranslationPromptContext",
    "build_background_field_translation_system_section",
    "build_character_field_translation_system_section",
    "build_field_translation_user_section",
    "render_background_field_translation_prompts",
    "render_character_field_translation_prompts",
]
