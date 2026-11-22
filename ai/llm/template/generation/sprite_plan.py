"""Pure Composite prompt sections for sprite planning, transition inference, and H3 T2I/I2V contracts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import json
from typing import Any

from sdk.lang import normalize_lang

from ..core.catalog import PROMPT_CATALOG
from ..core.context import TemplateContext
from ..core.prompt_spec import PromptLanguagePolicy, PromptSpec
from ..core.section import I18nSection, Section, TextSection


@dataclass(frozen=True)
class SpritePlanPromptContext(TemplateContext):
    """Context for LLM-authored character sprite pose & tagging plans."""

    name: str = ""
    setting: str = ""
    count: int = 4
    requirements: str = ""
    has_reference: bool = False
    prompt_suffix: str = ""


@dataclass(frozen=True)
class TransitionRecommendationPromptContext(TemplateContext):
    """Context for classifying historical dialogue turns into existing sprite IDs."""

    payload_json: str = ""


@dataclass(frozen=True)
class SpriteIdleAnimationPromptContext(TemplateContext):
    """Context for locked English ComfyUI/MiniMax H3 idle animation prompt assembly."""

    breathing: bool = True
    blinking: bool = True
    breeze: bool = False
    custom_motion: str = ""
    loop: bool = True


class _SpritePlanFramingSection(Section[SpritePlanPromptContext]):
    def _render_self(self, context: SpritePlanPromptContext) -> str:
        key = (
            "generation.sprite_plan_framing_reference"
            if context.has_reference
            else "generation.sprite_plan_framing_full_body"
        )
        return context.tr(key)


def build_sprite_plan_system_section() -> Section[SpritePlanPromptContext]:
    return Section(
        "sprite_plan_system",
        separator="",
        children=(
            I18nSection("intro", priority=10, key="generation.sprite_plan_intro"),
            _SpritePlanFramingSection("framing", priority=20),
            I18nSection("body", priority=30, key="generation.sprite_plan_body"),
            I18nSection(
                "template_rule",
                priority=40,
                key="generation.sprite_plan_template_rule",
                params=lambda ctx: {"suffix": ctx.prompt_suffix},
            ),
            I18nSection(
                "props_and_no_appearance",
                priority=50,
                key="generation.sprite_plan_props_and_no_appearance",
            ),
            I18nSection(
                "tagging_rules",
                priority=60,
                key="generation.sprite_tag_instructions",
            ),
            I18nSection(
                "output_schema",
                priority=70,
                key="generation.sprite_plan_output_schema",
            ),
        ),
    )


def build_sprite_plan_user_section() -> Section[SpritePlanPromptContext]:
    return TextSection(
        "sprite_plan_user",
        text=lambda ctx: json.dumps(
            {
                "name": ctx.name,
                "setting": ctx.setting,
                "count": int(ctx.count),
                "requirements": ctx.requirements,
                "hasReference": bool(ctx.has_reference),
            },
            ensure_ascii=False,
        ),
    )


def build_transition_recommendation_system_section() -> (
    Section[TransitionRecommendationPromptContext]
):
    return I18nSection(
        "transition_recommendation_system",
        key="generation.transition_recommendation_system",
    )


def build_transition_recommendation_user_section() -> (
    Section[TransitionRecommendationPromptContext]
):
    return TextSection(
        "transition_recommendation_user",
        text=lambda ctx: ctx.payload_json,
    )


class _SpriteIdleMotionListSection(Section[SpriteIdleAnimationPromptContext]):
    def _render_self(self, context: SpriteIdleAnimationPromptContext) -> str:
        motions: list[str] = []
        if context.breathing:
            motions.append(context.tr("generation.sprite_idle_motion_breathing"))
        if context.blinking:
            motions.append(context.tr("generation.sprite_idle_motion_blinking"))
        if context.breeze:
            motions.append(context.tr("generation.sprite_idle_motion_breeze"))
        if context.custom_motion.strip():
            motions.append(context.custom_motion.strip())
        return "; ".join(motions)


def build_sprite_idle_animation_section() -> Section[SpriteIdleAnimationPromptContext]:
    return Section(
        "sprite_idle_animation",
        separator="",
        children=(
            I18nSection(
                "pose_lead",
                priority=10,
                key="generation.sprite_idle_pose_lead",
            ),
            TextSection(
                "no_blink_guard",
                priority=20,
                text=lambda ctx: (
                    ctx.tr("generation.sprite_idle_no_blink_guard")
                    if not ctx.blinking
                    else ""
                ),
            ),
            _SpriteIdleMotionListSection("motions", priority=30),
            I18nSection(
                "shot_tail",
                priority=40,
                key="generation.sprite_idle_shot_tail",
            ),
            TextSection(
                "loop_seam",
                priority=50,
                text=lambda ctx: (
                    ctx.tr("generation.sprite_idle_loop_seam") if ctx.loop else ""
                ),
            ),
            I18nSection(
                "reference_framing",
                priority=60,
                key="generation.sprite_reference_framing_suffix",
            ),
            I18nSection(
                "camera_suffix",
                priority=70,
                key="generation.sprite_camera_suffix",
            ),
        ),
    )


def build_mouth_speech_prompt_section() -> Section[TemplateContext]:
    return I18nSection("mouth_speech_prompt", key="generation.mouth_speech_prompt")


def build_mouth_blink_prompt_section() -> Section[TemplateContext]:
    return I18nSection("mouth_blink_prompt", key="generation.mouth_blink_prompt")


def build_sprite_transition_prompt_section() -> Section[TemplateContext]:
    return Section(
        "sprite_transition_prompt",
        separator="",
        children=(
            I18nSection(
                "lead",
                priority=10,
                key="generation.sprite_transition_lead",
            ),
            I18nSection(
                "reference_framing",
                priority=20,
                key="generation.sprite_reference_framing_suffix",
            ),
            I18nSection(
                "camera_suffix",
                priority=30,
                key="generation.sprite_camera_suffix",
            ),
        ),
    )


SPRITE_PLAN_SPEC: PromptSpec[SpritePlanPromptContext, SpritePlanPromptContext] = (
    PromptSpec(
        id="generation.sprite_plan",
        language_policy=PromptLanguagePolicy.FOLLOW_UI,
        system_builder=build_sprite_plan_system_section,
        user_builder=build_sprite_plan_user_section,
    )
)

TRANSITION_RECOMMENDATION_SPEC: PromptSpec[
    TransitionRecommendationPromptContext, TransitionRecommendationPromptContext
] = PromptSpec(
    id="generation.transition_recommendation",
    language_policy=PromptLanguagePolicy.FOLLOW_UI,
    system_builder=build_transition_recommendation_system_section,
    user_builder=build_transition_recommendation_user_section,
)

# L3 T2I / ComfyUI MiniMax H3 video generation prompts are locked to English
SPRITE_IDLE_ANIMATION_SPEC: PromptSpec[
    SpriteIdleAnimationPromptContext, SpriteIdleAnimationPromptContext
] = PromptSpec(
    id="generation.sprite_idle_animation",
    language_policy=PromptLanguagePolicy.LOCKED_CONTRACT,
    locked_locale="en",
    user_builder=build_sprite_idle_animation_section,
)

MOUTH_SPEECH_PROMPT_SPEC: PromptSpec[TemplateContext, TemplateContext] = PromptSpec(
    id="generation.mouth_speech_prompt",
    language_policy=PromptLanguagePolicy.LOCKED_CONTRACT,
    locked_locale="en",
    user_builder=build_mouth_speech_prompt_section,
)

MOUTH_BLINK_PROMPT_SPEC: PromptSpec[TemplateContext, TemplateContext] = PromptSpec(
    id="generation.mouth_blink_prompt",
    language_policy=PromptLanguagePolicy.LOCKED_CONTRACT,
    locked_locale="en",
    user_builder=build_mouth_blink_prompt_section,
)

SPRITE_TRANSITION_PROMPT_SPEC: PromptSpec[TemplateContext, TemplateContext] = (
    PromptSpec(
        id="generation.sprite_transition_prompt",
        language_policy=PromptLanguagePolicy.LOCKED_CONTRACT,
        locked_locale="en",
        user_builder=build_sprite_transition_prompt_section,
    )
)


def resolve_sprite_suffixes() -> tuple[str, str, str, str]:
    """Return `(camera_suffix, full_prompt_suffix, ref_framing_suffix, ref_prompt_suffix)`."""
    cam = PROMPT_CATALOG.translate("generation.sprite_camera_suffix", locale="en")
    full_prefix = PROMPT_CATALOG.translate(
        "generation.sprite_full_body_prefix", locale="en"
    )
    ref_framing = PROMPT_CATALOG.translate(
        "generation.sprite_reference_framing_suffix", locale="en"
    )
    ref_pose = PROMPT_CATALOG.translate(
        "generation.sprite_reference_pose_in_frame", locale="en"
    )
    return (
        cam,
        full_prefix + cam,
        ref_framing,
        ref_framing + ref_pose + cam,
    )


def render_sprite_plan_prompts(
    *,
    name: str,
    setting: str,
    count: int,
    requirements: str,
    has_reference: bool,
    prompt_suffix: str,
    locale: str | None = None,
) -> tuple[str, str]:
    ctx = SpritePlanPromptContext(
        locale=normalize_lang(locale) if locale else "zh_CN",
        name=name,
        setting=setting,
        count=count,
        requirements=requirements,
        has_reference=has_reference,
        prompt_suffix=prompt_suffix,
    )
    return (
        SPRITE_PLAN_SPEC.render_system(ctx),
        SPRITE_PLAN_SPEC.render_user(ctx),
    )


def render_transition_recommendation_prompts(
    *,
    name: str,
    setting: str,
    sprites: Sequence[dict[str, Any]],
    turns: Sequence[dict[str, Any]],
    locale: str | None = None,
) -> tuple[str, str]:
    payload_json = json.dumps(
        {
            "name": name,
            "setting": str(setting or "")[:4000],
            "sprites": list(sprites),
            "turns": list(turns),
        },
        ensure_ascii=False,
    )
    ctx = TransitionRecommendationPromptContext(
        locale=normalize_lang(locale) if locale else "zh_CN",
        payload_json=payload_json,
    )
    return (
        TRANSITION_RECOMMENDATION_SPEC.render_system(ctx),
        TRANSITION_RECOMMENDATION_SPEC.render_user(ctx),
    )


def render_sprite_idle_animation_prompt(
    *,
    breathing: bool = True,
    blinking: bool = True,
    breeze: bool = False,
    custom_motion: str = "",
    loop: bool = True,
) -> str:
    ctx = SpriteIdleAnimationPromptContext(
        locale="en",
        breathing=breathing,
        blinking=blinking,
        breeze=breeze,
        custom_motion=custom_motion,
        loop=loop,
    )
    return SPRITE_IDLE_ANIMATION_SPEC.render_user(ctx)


def render_mouth_speech_prompt(*, include_blink: bool = False) -> str:
    spec = MOUTH_BLINK_PROMPT_SPEC if include_blink else MOUTH_SPEECH_PROMPT_SPEC
    return spec.render_user(TemplateContext(locale="en"))


def render_sprite_transition_prompt() -> str:
    return SPRITE_TRANSITION_PROMPT_SPEC.render_user(TemplateContext(locale="en"))


__all__ = [
    "MOUTH_BLINK_PROMPT_SPEC",
    "MOUTH_SPEECH_PROMPT_SPEC",
    "SPRITE_IDLE_ANIMATION_SPEC",
    "SPRITE_PLAN_SPEC",
    "SPRITE_TRANSITION_PROMPT_SPEC",
    "SpriteIdleAnimationPromptContext",
    "SpritePlanPromptContext",
    "TRANSITION_RECOMMENDATION_SPEC",
    "TransitionRecommendationPromptContext",
    "build_mouth_blink_prompt_section",
    "build_mouth_speech_prompt_section",
    "build_sprite_idle_animation_section",
    "build_sprite_plan_system_section",
    "build_sprite_plan_user_section",
    "build_sprite_transition_prompt_section",
    "build_transition_recommendation_system_section",
    "build_transition_recommendation_user_section",
    "render_mouth_speech_prompt",
    "render_sprite_idle_animation_prompt",
    "render_sprite_plan_prompts",
    "render_sprite_transition_prompt",
    "render_transition_recommendation_prompts",
    "resolve_sprite_suffixes",
]
