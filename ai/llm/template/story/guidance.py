"""Dynamic story guidance appended to the ordinary template system prompt."""

import json

from ai.llm.template.core import I18nSection, PromptSpec, Section, TextSection
from ai.llm.template.story.context import StoryGuidanceContext


def _state_text(context: StoryGuidanceContext) -> str:
    k_cond = context.tr("story.guidance_key_condition")
    k_next = context.tr("story.guidance_key_next_title")
    data = {
        context.tr("story.guidance_key_title"): context.title,
        context.tr("story.guidance_key_instruction"): context.instruction,
        context.tr("story.guidance_key_turn_count"): context.turn_count,
        context.tr("story.guidance_key_max_rounds"): context.max_rounds,
        context.tr("story.guidance_key_transitions"): [
            {k_cond: item.condition, k_next: item.next_title}
            for item in context.transitions
        ],
    }
    if context.background:
        data[context.tr("story.guidance_key_background")] = context.background
    return json.dumps(data, ensure_ascii=False)


def build_story_guidance_section() -> Section[StoryGuidanceContext]:
    return Section(
        id="story.guidance.system",
        children=(
            I18nSection(
                id="instructions",
                priority=10,
                key="story.guidance_instructions",
            ),
            TextSection(id="state", priority=20, text=_state_text),
        ),
    )


STORY_GUIDANCE_SPEC = PromptSpec(
    id="story.guidance",
    system_builder=build_story_guidance_section,
)
