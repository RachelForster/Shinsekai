"""Pure renderers for story guidance, authoring, transition assessment, and scene rendering."""

from __future__ import annotations

from ai.llm.template.story.assessment import (
    STORY_ASSESSMENT_SPEC,
    build_story_assessment_system_section,
    build_story_assessment_user_section,
)
from ai.llm.template.story.author import (
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
from ai.llm.template.story.scene import (
    STORY_SCENE_SPEC,
    build_story_scene_system_section,
    build_story_scene_user_section,
    render_scene_degraded_fallback,
)


def __getattr__(name: str) -> str:
    if name == "AUTHOR_COMPILER_TEMPLATE":
        from ai.llm.template.story import author

        return getattr(author, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AUTHOR_COMPILER_TEMPLATE",
    "STORY_ASSESSMENT_SPEC",
    "STORY_AUTHOR_SPEC",
    "STORY_GUIDANCE_SPEC",
    "STORY_SCENE_SPEC",
    "StoryGuidanceContext",
    "StoryGuidanceTransition",
    "StoryRequestContext",
    "build_story_guidance_section",
    "build_story_author_system_section",
    "build_story_author_user_section",
    "build_story_assessment_system_section",
    "build_story_assessment_user_section",
    "build_story_scene_system_section",
    "build_story_scene_user_section",
    "render_scene_degraded_fallback",
]
