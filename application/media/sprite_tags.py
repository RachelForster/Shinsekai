"""Shared instructions and output rules for character emotion/action tags."""

import re

from core.media.asset_tags import normalize_generated_tags


SPRITE_TAG_INSTRUCTIONS = (
    "仅用 2–3 个简短中文词语描述人物的情绪、表情和动作，至少包含一个情绪或表情词、"
    "一个动作或姿态词；用中文逗号分隔。例如：开心，微笑，挥手；害羞，低头；平静，站立。"
    "只描述可见状态，不写身份、外貌、服装、背景或推测的对话场景。"
    "不要英文、编号、标题、解释、句子或 Markdown。"
)


def normalize_sprite_tags(value: str) -> str:
    normalized = normalize_generated_tags(re.sub(r"[、/／]+", ",", str(value or "")))
    words = list(
        dict.fromkeys(word.strip() for word in normalized.split(",") if word.strip())
    )
    if not 2 <= len(words) <= 3 or any(
        not re.fullmatch(r"[\u3400-\u9fff]{1,8}", word) for word in words
    ):
        raise ValueError("视觉标注需要 2–3 个中文情绪、动作词，例如：开心，微笑，挥手")
    return "，".join(words)
