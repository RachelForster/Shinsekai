"""Pure renderers for story guidance, authoring, and transition assessment."""

from ai.llm.template.story.assessment import (
    STORY_ASSESSMENT_SPEC,
    build_story_assessment_system_section,
    build_story_assessment_user_section,
)
from ai.llm.template.story.author import (
    AUTHOR_COMPILER_TEMPLATE,
    STORY_AUTHOR_SPEC,
    build_story_author_system_section,
    build_story_author_user_section,
)
from ai.llm.template.story.context import (
    StoryGuidanceContext,
    StoryGuidanceTransition,
    StoryRequestContext,
)
from ai.llm.template.story.guidance import (
    STORY_GUIDANCE_SPEC,
    build_story_guidance_section,
)

__all__ = [
    "AUTHOR_COMPILER_TEMPLATE",
    "STORY_ASSESSMENT_SPEC",
    "STORY_AUTHOR_SPEC",
    "STORY_GUIDANCE_SPEC",
    "StoryGuidanceContext",
    "StoryGuidanceTransition",
    "StoryRequestContext",
    "build_story_guidance_section",
    "build_story_author_system_section",
    "build_story_author_user_section",
    "build_story_assessment_system_section",
    "build_story_assessment_user_section",
]
