"""Pure localized prompt sections for the controlled story scene renderer."""

from __future__ import annotations

import json

from ai.llm.template.core import (
    I18nSection,
    PROMPT_CATALOG,
    PromptSpec,
    Section,
    TemplateContext,
    TextSection,
)
from ai.llm.template.story.context import StoryRequestContext


def build_story_scene_system_section() -> Section[TemplateContext]:
    return Section(
        id="story.scene.system",
        children=(
            I18nSection(
                id="role",
                priority=10,
                key="story.scene_renderer_role",
            ),
            I18nSection(
                id="output",
                priority=20,
                key="story.scene_renderer_output",
            ),
            I18nSection(
                id="transitions",
                priority=30,
                key="story.scene_renderer_transitions",
            ),
        ),
    )


def build_story_scene_user_section() -> Section[StoryRequestContext]:
    return Section(
        id="story.scene.user",
        children=(
            TextSection(
                id="request",
                text=lambda context: json.dumps(
                    context.payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            ),
        ),
    )


STORY_SCENE_SPEC = PromptSpec(
    id="story.scene",
    system_builder=build_story_scene_system_section,
    user_builder=build_story_scene_user_section,
)


def render_scene_degraded_fallback(
    title: str,
    *,
    locale: str | None = "zh_CN",
) -> str:
    return PROMPT_CATALOG.translate(
        "story.scene_degraded_fallback",
        locale=locale,
        title=title,
    )


__all__ = [
    "STORY_SCENE_SPEC",
    "build_story_scene_system_section",
    "build_story_scene_user_section",
    "render_scene_degraded_fallback",
]
