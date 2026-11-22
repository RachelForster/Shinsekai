"""Prompt sections for assessing transitions after ordinary dialogue."""

import json

from ai.llm.template.core import I18nSection, PromptSpec, Section, TemplateContext, TextSection
from ai.llm.template.story.context import StoryRequestContext


def build_story_assessment_system_section() -> Section[TemplateContext]:
    return Section(
        id="story.assessment.system",
        children=(
            I18nSection(
                id="scope",
                priority=10,
                key="story.assessment_scope",
            ),
            I18nSection(
                id="output",
                priority=20,
                key="story.assessment_output",
            ),
        ),
    )


def build_story_assessment_user_section() -> Section[StoryRequestContext]:
    return Section(
        id="story.assessment.user",
        children=(
            TextSection(
                id="request",
                text=lambda context: json.dumps(context.payload, ensure_ascii=False),
            ),
        ),
    )


STORY_ASSESSMENT_SPEC = PromptSpec(
    id="story.assessment",
    system_builder=build_story_assessment_system_section,
    user_builder=build_story_assessment_user_section,
)
