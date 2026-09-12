"""Dynamic story guidance appended to the ordinary template system prompt."""

import json

from ai.llm.template.core.section import Section, TextSection
from ai.llm.template.story.context import StoryGuidanceContext


def _state_text(context: StoryGuidanceContext) -> str:
    data = {
        "当前剧情": context.title,
        "剧情要求": context.instruction,
        "已进行轮数": context.turn_count,
        "建议轮数": context.max_rounds,
        "剧情衔接条件": [
            {"条件": item.condition, "下一段": item.next_title}
            for item in context.transitions
        ],
    }
    if context.background:
        data["剧情地点参考"] = context.background
    return json.dumps(data, ensure_ascii=False)


def build_story_guidance_section() -> Section[StoryGuidanceContext]:
    return Section(
        id="story.guidance.system",
        children=(
            TextSection(
                id="instructions",
                priority=10,
                text=(
                    "【当前剧本进度】\n"
                    "这是附加的剧情引导。结合用户行动自然展开当前剧情，"
                    "人物、背景、立绘、工具使用与回复格式均沿用原有模板系统提示词。"
                    "剧情中的人物和地点是叙事参考，不是额外的可用人物或素材白名单。"
                    "不要在回复中增加剧本状态字段或内部节点编号。\n"
                ),
            ),
            TextSection(id="state", priority=20, text=_state_text),
        ),
    )
