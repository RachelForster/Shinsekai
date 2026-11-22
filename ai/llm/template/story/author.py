"""Story author instructions shared by stage generation and compiler repair."""

from __future__ import annotations

import json

from ai.llm.template.core import (
    I18nSection,
    PromptSpec,
    Section,
    TemplateContext,
    TextSection,
)
from ai.llm.template.story.context import StoryRequestContext


def build_story_author_system_section() -> Section[TemplateContext]:
    return Section(
        id="story.author.system",
        children=(
            I18nSection(
                id="role",
                priority=10,
                key="story.author_role",
            ),
            I18nSection(
                id="output",
                priority=20,
                key="story.author_output",
            ),
            I18nSection(
                id="scope",
                priority=30,
                key="story.author_scope",
            ),
        ),
    )


def build_story_author_user_section() -> Section[StoryRequestContext]:
    return Section(
        id="story.author.user",
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


STORY_AUTHOR_SPEC = PromptSpec(
    id="story.author",
    system_builder=build_story_author_system_section,
    user_builder=build_story_author_user_section,
)


def __getattr__(name: str) -> str:
    if name == "AUTHOR_COMPILER_TEMPLATE":
        return STORY_AUTHOR_SPEC.render_system(TemplateContext(locale="en"))
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AUTHOR_COMPILER_TEMPLATE",
    "STORY_AUTHOR_SPEC",
    "build_story_author_system_section",
    "build_story_author_user_section",
]
