"""Pure renderers for story guidance, authoring, and transition assessment."""

from ai.llm.template.story.assessment import (
    build_story_assessment_system_section,
    build_story_assessment_user_section,
)
from ai.llm.template.story.author import (
    AUTHOR_COMPILER_TEMPLATE,
    build_story_author_system_section,
    build_story_author_user_section,
)
from ai.llm.template.story.context import (
    StoryGuidanceContext,
    StoryGuidanceTransition,
    StoryRequestContext,
)
from ai.llm.template.story.guidance import build_story_guidance_section

__all__ = [
    "AUTHOR_COMPILER_TEMPLATE",
    "StoryGuidanceContext",
    "StoryGuidanceTransition",
    "StoryRequestContext",
    "build_story_guidance_section",
    "build_story_author_system_section",
    "build_story_author_user_section",
    "build_story_assessment_system_section",
    "build_story_assessment_user_section",
]
