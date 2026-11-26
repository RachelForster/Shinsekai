"""Pure Composite prompt sections for sprite and background image auto-annotation."""

from __future__ import annotations

from dataclasses import dataclass
import json

from sdk.lang import normalize_lang

from ..core.context import TemplateContext
from ..core.prompt_spec import PromptLanguagePolicy, PromptSpec
from ..core.section import I18nSection, Section, TextSection


@dataclass(frozen=True)
class MediaAnnotationPromptContext(TemplateContext):
    """Context for VLM asset auto-annotation and single-shot format retries."""

    base_prompt: str = ""
    previous_raw_output: str = ""


def build_sprite_tag_instructions_section() -> Section[MediaAnnotationPromptContext]:
    return I18nSection(
        "sprite_tag_instructions",
        key="generation.sprite_tag_instructions",
    )


def build_character_annotation_section() -> Section[MediaAnnotationPromptContext]:
    return Section(
        "character_annotation",
        separator="",
        children=(
            I18nSection(
                "intro",
                priority=10,
                key="generation.character_annotation_intro",
            ),
            build_sprite_tag_instructions_section(),
        ),
    )


def build_background_annotation_section() -> Section[MediaAnnotationPromptContext]:
    return I18nSection(
        "background_annotation",
        key="generation.background_annotation_prompt",
    )


def build_annotation_retry_section() -> Section[MediaAnnotationPromptContext]:
    return Section(
        "annotation_retry",
        separator="",
        children=(
            TextSection("base_prompt", priority=10, text=lambda ctx: ctx.base_prompt),
            I18nSection(
                "retry_notice",
                priority=20,
                key="generation.annotation_retry_suffix",
            ),
            TextSection(
                "previous_output",
                priority=30,
                text=lambda ctx: json.dumps(ctx.previous_raw_output, ensure_ascii=False),
            ),
        ),
    )


# L3 contract lock: normalize_sprite_tags requires 2-3 Chinese words (r"[\u3400-\u9fff]{1,8}")
SPRITE_TAG_INSTRUCTIONS_SPEC: PromptSpec[
    MediaAnnotationPromptContext, MediaAnnotationPromptContext
] = PromptSpec(
    id="generation.sprite_tag_instructions",
    language_policy=PromptLanguagePolicy.LOCKED_CONTRACT,
    locked_locale="zh_CN",
    user_builder=build_sprite_tag_instructions_section,
)

CHARACTER_ANNOTATION_SPEC: PromptSpec[
    MediaAnnotationPromptContext, MediaAnnotationPromptContext
] = PromptSpec(
    id="generation.character_annotation",
    language_policy=PromptLanguagePolicy.LOCKED_CONTRACT,
    locked_locale="zh_CN",
    user_builder=build_character_annotation_section,
)

# Background annotation instructions follow UI locale while requiring English comma-separated tags
BACKGROUND_ANNOTATION_SPEC: PromptSpec[
    MediaAnnotationPromptContext, MediaAnnotationPromptContext
] = PromptSpec(
    id="generation.background_annotation",
    language_policy=PromptLanguagePolicy.FOLLOW_UI,
    user_builder=build_background_annotation_section,
)

ANNOTATION_RETRY_SPEC: PromptSpec[
    MediaAnnotationPromptContext, MediaAnnotationPromptContext
] = PromptSpec(
    id="generation.annotation_retry",
    language_policy=PromptLanguagePolicy.FOLLOW_UI,
    user_builder=build_annotation_retry_section,
)


def render_sprite_tag_instructions(*, locale: str | None = None) -> str:
    ctx = MediaAnnotationPromptContext(
        locale=normalize_lang(locale) if locale else "zh_CN",
    )
    return SPRITE_TAG_INSTRUCTIONS_SPEC.render_user(ctx)


def render_character_annotation_prompt(*, locale: str | None = None) -> str:
    ctx = MediaAnnotationPromptContext(
        locale=normalize_lang(locale) if locale else "zh_CN",
    )
    return CHARACTER_ANNOTATION_SPEC.render_user(ctx)


def render_background_annotation_prompt(*, locale: str | None = None) -> str:
    ctx = MediaAnnotationPromptContext(
        locale=normalize_lang(locale) if locale else "zh_CN",
    )
    return BACKGROUND_ANNOTATION_SPEC.render_user(ctx)


def render_annotation_retry_prompt(
    base_prompt: str,
    previous_raw_output: str,
    *,
    locale: str | None = None,
) -> str:
    ctx = MediaAnnotationPromptContext(
        locale=normalize_lang(locale) if locale else "zh_CN",
        base_prompt=base_prompt,
        previous_raw_output=previous_raw_output,
    )
    return ANNOTATION_RETRY_SPEC.render_user(ctx)


__all__ = [
    "ANNOTATION_RETRY_SPEC",
    "BACKGROUND_ANNOTATION_SPEC",
    "CHARACTER_ANNOTATION_SPEC",
    "MediaAnnotationPromptContext",
    "SPRITE_TAG_INSTRUCTIONS_SPEC",
    "build_annotation_retry_section",
    "build_background_annotation_section",
    "build_character_annotation_section",
    "build_sprite_tag_instructions_section",
    "render_annotation_retry_prompt",
    "render_background_annotation_prompt",
    "render_character_annotation_prompt",
    "render_sprite_tag_instructions",
]
