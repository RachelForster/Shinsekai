"""Shared instructions and output rules for character emotion/action tags."""

from __future__ import annotations

import re

from ai.llm.template.generation.media_annotation import render_sprite_tag_instructions
from core.media.asset_tags import normalize_generated_tags

# L3 locked contract: normalize_sprite_tags enforces 2-3 Chinese words (r"[\u3400-\u9fff]{1,8}")
SPRITE_TAG_INSTRUCTIONS = render_sprite_tag_instructions()


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
