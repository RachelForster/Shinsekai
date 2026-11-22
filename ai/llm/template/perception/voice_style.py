"""Pure Composite prompt sections for character voice-style extraction."""

from __future__ import annotations

from dataclasses import dataclass
import re

from sdk.lang import normalize_lang

from ..core.context import TemplateContext
from ..core.prompt_spec import PromptLanguagePolicy, PromptSpec
from ..core.section import I18nSection, Section, TextSection


@dataclass(frozen=True)
class VoiceStylePromptContext(TemplateContext):
    """Context for one-off lore-free speaking style extraction."""

    character_name: str = ""
    character_brief: str = ""

    def clean_name(self) -> str:
        return str(self.character_name or "").strip()

    def clean_brief(self) -> str:
        return re.sub(r"\s+", " ", str(self.character_brief or "").strip())[:480]


def _ban_hint_params(ctx: VoiceStylePromptContext) -> dict[str, str]:
    name = ctx.clean_name()
    ban_hint = (
        ctx.tr("perception.voice_style_ban_name", name=name) if name else ""
    )
    return {"ban_hint": ban_hint}


def build_voice_style_system_section() -> Section[VoiceStylePromptContext]:
    return Section(
        "perception_voice_style_system",
        separator="\n",
        children=(
            I18nSection(
                "intro",
                priority=10,
                key="perception.voice_style_system_intro",
            ),
            I18nSection(
                "rules",
                priority=20,
                key="perception.voice_style_system_rules",
                params=_ban_hint_params,
            ),
        ),
    )


def build_voice_style_user_section() -> Section[VoiceStylePromptContext]:
    return Section(
        "perception_voice_style_user",
        separator="",
        children=(
            I18nSection(
                "prefix",
                priority=10,
                key="perception.voice_style_user_prefix",
            ),
            TextSection(
                "brief",
                priority=20,
                text=lambda ctx: ctx.clean_brief(),
            ),
        ),
    )


# Local Qwen3-VL-2B-Instruct voice-style extraction stays locked to zh_CN (L3 small-model contract)
VOICE_STYLE_SPEC: PromptSpec[VoiceStylePromptContext, VoiceStylePromptContext] = PromptSpec(
    id="perception.voice_style",
    language_policy=PromptLanguagePolicy.LOCKED_CONTRACT,
    locked_locale="zh_CN",
    system_builder=build_voice_style_system_section,
    user_builder=build_voice_style_user_section,
)


def render_voice_style_messages(
    character_name: str,
    character_brief: str,
    *,
    locale: str | None = None,
) -> list[dict[str, str]]:
    ctx = VoiceStylePromptContext(
        locale=normalize_lang(locale) if locale else "zh_CN",
        character_name=character_name,
        character_brief=character_brief,
    )
    return [
        {"role": "system", "content": VOICE_STYLE_SPEC.render_system(ctx)},
        {"role": "user", "content": VOICE_STYLE_SPEC.render_user(ctx)},
    ]


__all__ = [
    "VOICE_STYLE_SPEC",
    "VoiceStylePromptContext",
    "build_voice_style_system_section",
    "build_voice_style_user_section",
    "render_voice_style_messages",
]
