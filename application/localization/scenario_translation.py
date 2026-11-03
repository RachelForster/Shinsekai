"""Translate character voice-tag names through the application LLM service."""

from __future__ import annotations

import json
import re
from typing import Any

from .field_translation import _llm_one_shot, _parse_json_object


def translate_scenario_names(config: Any, names: list[str]) -> dict[str, str]:
    needs = [(index, name) for index, name in enumerate(names)
             if name and not re.fullmatch(r"[A-Za-z0-9_-]+", name)]
    if not needs:
        return {}
    system = (
        "Translate each voice tag to a short lowercase English tag. "
        "Use only letters, numbers, underscores or hyphens. "
        'Return ONLY a JSON object with a "translations" array in the same order.'
    )
    raw = _llm_one_shot(config, system, json.dumps([name for _, name in needs], ensure_ascii=False))
    translations = _parse_json_object(raw).get("translations")
    if not isinstance(translations, list) or len(translations) != len(needs):
        raise ValueError("Invalid voice tag translation response")
    result = {}
    for (index, _), translated in zip(needs, translations):
        if not isinstance(translated, str) or not re.fullmatch(r"[a-z0-9_-]+", translated.strip().lower()):
            raise ValueError("Invalid translated voice tag")
        result[str(index)] = translated.strip().lower()
    return result
