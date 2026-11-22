"""Pure Composite prompt sections for character setting and brief generation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import json
from typing import Any

from sdk.lang import normalize_lang

from ..core.context import TemplateContext
from ..core.prompt_spec import PromptLanguagePolicy, PromptSpec
from ..core.section import I18nSection, Section, TextSection


@dataclass(frozen=True)
class CharacterSettingPromptContext(TemplateContext):
    """Context for full character setting generation."""

    name: str = ""
    seed_setting: str = ""


@dataclass(frozen=True)
class CharacterBriefPromptContext(TemplateContext):
    """Context for single character brief compression."""

    name: str = ""
    setting: str = ""


@dataclass(frozen=True)
class CharacterBriefBatchPromptContext(TemplateContext):
    """Context for batch character brief compression."""

    characters_json: str = ""


def build_character_setting_system_section() -> Section[CharacterSettingPromptContext]:
    return I18nSection(
        "character_setting_system",
        key="generation.character_setting_system",
        params=lambda ctx: {"name": str(ctx.name or "").strip()},
    )


def build_character_setting_user_section() -> Section[CharacterSettingPromptContext]:
    return I18nSection(
        "character_setting_user",
        key="generation.character_setting_user",
        params=lambda ctx: {
            "setting": (
                str(ctx.seed_setting or "").strip()
                or ctx.tr("generation.character_setting_empty_hint")
            )
        },
    )


def build_character_brief_system_section() -> Section[CharacterBriefPromptContext]:
    return I18nSection(
        "character_brief_system",
        key="generation.character_brief_system",
    )


def build_character_brief_user_section() -> Section[CharacterBriefPromptContext]:
    return Section(
        "character_brief_user",
        separator="\n",
        children=(
            I18nSection(
                "header",
                priority=10,
                key="generation.character_brief_user_header",
                params=lambda ctx: {"name": str(ctx.name or "").strip()},
            ),
            TextSection(
                "setting",
                priority=20,
                text=lambda ctx: (
                    str(ctx.setting or "").strip()
                    or ctx.tr("generation.character_brief_empty_setting")
                ),
            ),
        ),
    )


def build_character_brief_batch_system_section() -> (
    Section[CharacterBriefBatchPromptContext]
):
    return I18nSection(
        "character_brief_batch_system",
        key="generation.character_brief_batch_system",
    )


def build_character_brief_batch_user_section() -> (
    Section[CharacterBriefBatchPromptContext]
):
    return TextSection(
        "character_brief_batch_user",
        text=lambda ctx: ctx.characters_json,
    )


CHARACTER_SETTING_SPEC: PromptSpec[
    CharacterSettingPromptContext, CharacterSettingPromptContext
] = PromptSpec(
    id="generation.character_setting",
    language_policy=PromptLanguagePolicy.FOLLOW_UI,
    system_builder=build_character_setting_system_section,
    user_builder=build_character_setting_user_section,
)

CHARACTER_BRIEF_SPEC: PromptSpec[
    CharacterBriefPromptContext, CharacterBriefPromptContext
] = PromptSpec(
    id="generation.character_brief",
    language_policy=PromptLanguagePolicy.FOLLOW_UI,
    system_builder=build_character_brief_system_section,
    user_builder=build_character_brief_user_section,
)

CHARACTER_BRIEF_BATCH_SPEC: PromptSpec[
    CharacterBriefBatchPromptContext, CharacterBriefBatchPromptContext
] = PromptSpec(
    id="generation.character_brief_batch",
    language_policy=PromptLanguagePolicy.FOLLOW_UI,
    system_builder=build_character_brief_batch_system_section,
    user_builder=build_character_brief_batch_user_section,
)


def render_character_setting_prompts(
    name: str,
    seed_setting: str,
    *,
    locale: str | None = None,
) -> tuple[str, str]:
    ctx = CharacterSettingPromptContext(
        locale=normalize_lang(locale) if locale else "zh_CN",
        name=name,
        seed_setting=seed_setting,
    )
    return (
        CHARACTER_SETTING_SPEC.render_system(ctx),
        CHARACTER_SETTING_SPEC.render_user(ctx),
    )


def render_character_brief_prompts(
    name: str,
    setting: str,
    *,
    locale: str | None = None,
) -> tuple[str, str]:
    ctx = CharacterBriefPromptContext(
        locale=normalize_lang(locale) if locale else "zh_CN",
        name=name,
        setting=setting,
    )
    return (
        CHARACTER_BRIEF_SPEC.render_system(ctx),
        CHARACTER_BRIEF_SPEC.render_user(ctx),
    )


def render_character_brief_batch_prompts(
    characters: Sequence[dict[str, Any]],
    *,
    locale: str | None = None,
) -> tuple[str, str]:
    payload_json = json.dumps({"characters": list(characters)}, ensure_ascii=False)
    ctx = CharacterBriefBatchPromptContext(
        locale=normalize_lang(locale) if locale else "zh_CN",
        characters_json=payload_json,
    )
    return (
        CHARACTER_BRIEF_BATCH_SPEC.render_system(ctx),
        CHARACTER_BRIEF_BATCH_SPEC.render_user(ctx),
    )


__all__ = [
    "CHARACTER_BRIEF_BATCH_SPEC",
    "CHARACTER_BRIEF_SPEC",
    "CHARACTER_SETTING_SPEC",
    "CharacterBriefBatchPromptContext",
    "CharacterBriefPromptContext",
    "CharacterSettingPromptContext",
    "build_character_brief_batch_system_section",
    "build_character_brief_batch_user_section",
    "build_character_brief_system_section",
    "build_character_brief_user_section",
    "build_character_setting_system_section",
    "build_character_setting_user_section",
    "render_character_brief_batch_prompts",
    "render_character_brief_prompts",
    "render_character_setting_prompts",
]
