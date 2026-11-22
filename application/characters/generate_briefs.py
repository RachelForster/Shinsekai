"""AI generation and persistence for compact character briefs."""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

from ai.llm.llm_manager import LLMAdapterFactory, LLMManager


MAX_CHARACTER_BRIEF_LENGTH = 100
CHARACTER_BRIEF_PROMPT = (
    "你负责将人物设定压缩为可复用的人物简介。简介必须不超过100个字符，"
    "使用一个自然段，优先保留身份、核心性格、行为或语言特点以及重要人物关系。"
    "不要加入原设定中没有的信息，不要使用标题、列表、Markdown或引号，只输出简介。"
)


def normalize_character_brief(value: Any) -> str:
    """Return a single-paragraph brief capped at the persisted field limit."""

    text = re.sub(r"\s+", " ", str(value or "")).strip().strip('"')
    return text[:MAX_CHARACTER_BRIEF_LENGTH].rstrip()


def chat_character_text(
    config_store: Any, system: str, user: str, *, tools_enabled: bool | None = None
) -> str:
    provider, model, base_url, api_key = config_store.get_llm_api_config()
    if not provider or not model or not api_key:
        raise ValueError("llm_incomplete")
    adapter = LLMAdapterFactory.create_adapter(
        **config_store.merged_llm_factory_kwargs(
            provider,
            {
                "llm_provider": provider,
                "api_key": api_key,
                "base_url": base_url,
                "model": model,
            },
        )
    )
    options = {} if tools_enabled is None else {"tools_enabled": tools_enabled}
    manager = LLMManager(adapter=adapter, user_template=system, **options)
    return str(
        manager.chat(
            user,
            stream=False,
            response_format={"type": "text"},
            include_local_time=False,
        )
        or ""
    )


_chat = chat_character_text


def generate_character_brief(config_store: Any, name: str, setting: str) -> str:
    """Generate one reusable brief from a character's detailed setting."""

    user = f"人物名称：{name}\n人物设定：\n{setting or '无详细设定'}"
    brief = normalize_character_brief(_chat(config_store, CHARACTER_BRIEF_PROMPT, user))
    if not brief:
        raise ValueError("人物简介生成结果为空")
    return brief


def _parse_brief_rows(raw: str) -> list[dict[str, Any]]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text, flags=re.DOTALL)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("人物简介批量生成结果不是 JSON 对象")
    payload = json.loads(text[start : end + 1])
    rows = payload.get("briefs") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError("人物简介批量生成结果缺少 briefs 数组")
    return [row for row in rows if isinstance(row, dict)]


def ensure_character_briefs(
    config_store: Any,
    names: Iterable[str],
    *,
    characters: Any = None,
) -> tuple[list[Any], list[str]]:
    """Generate all missing briefs in one request and persist them once."""
    from config.character_ops import CHARACTER_MUTATION_LOCK

    resolved_characters: list[Any] = []
    seen: set[str] = set()
    for raw_name in names:
        name = str(raw_name or "").strip()
        key = name.casefold()
        if not name or key in seen:
            continue
        seen.add(key)
        character = (
            characters.get_by_name(name)
            if characters is not None
            else config_store.get_character_by_name(name)
        )
        if character is not None:
            resolved_characters.append(character)

    missing = [
        character
        for character in resolved_characters
        if not str(getattr(character, "character_brief", "") or "").strip()
    ]
    if not missing:
        return resolved_characters, []

    system = (
        "你负责批量生成可复用的人物简介。每条简介必须不超过100个字符，使用一个自然段，"
        "优先保留身份、核心性格、行为或语言特点以及重要人物关系。不要加入人物设定中没有的信息。"
        "只输出一个JSON对象，格式为"
        '{"briefs":[{"name":"人物原名","brief":"简介"}]}。'
        "必须为输入中的每个人物返回一条记录，name必须原样返回。"
    )
    user = json.dumps(
        {
            "characters": [
                {
                    "name": str(character.name),
                    "setting": str(getattr(character, "character_setting", "") or ""),
                }
                for character in missing
            ]
        },
        ensure_ascii=False,
    )
    rows = _parse_brief_rows(_chat(config_store, system, user))
    generated = {
        str(row.get("name") or "")
        .strip()
        .casefold(): normalize_character_brief(row.get("brief"))
        for row in rows
    }
    resolved_briefs: list[tuple[Any, str]] = []
    for character in missing:
        brief = generated.get(str(character.name).casefold(), "")
        if not brief:
            raise ValueError(f"人物 {character.name} 的简介生成结果为空")
        resolved_briefs.append((character, brief))

    generated_names: list[str] = []
    with CHARACTER_MUTATION_LOCK:
        if characters is not None:
            atomic = getattr(characters, "atomic", None)
            ctx = atomic() if callable(atomic) else None
            if ctx is not None:
                with ctx:
                    for character, brief in resolved_briefs:
                        char_id = str(getattr(character, "id", "") or "").strip()
                        latest = (characters.get(char_id) if char_id else None) or characters.get_by_name(character.name)
                        if latest is not None:
                            characters.put(latest.id, latest.model_copy(update={"character_brief": brief}))
                            generated_names.append(str(latest.name))
            else:
                for character, brief in resolved_briefs:
                    char_id = str(getattr(character, "id", "") or "").strip()
                    latest = (characters.get(char_id) if char_id else None) or characters.get_by_name(character.name)
                    if latest is not None:
                        characters.put(latest.id, latest.model_copy(update={"character_brief": brief}))
                        generated_names.append(str(latest.name))
            refresh = getattr(config_store, "refresh_characters", None)
            if callable(refresh):
                refresh()
            refreshed = [
                (characters.get(str(getattr(c, "id", "") or "")) if getattr(c, "id", "") else None)
                or characters.get_by_name(c.name)
                or c
                for c in resolved_characters
            ]
            return refreshed, generated_names

        for character, brief in resolved_briefs:
            latest = config_store.get_character_by_name(character.name) or character
            latest.character_brief = brief
            generated_names.append(str(latest.name))
        config_store.save_characters_config()
    return resolved_characters, generated_names


__all__ = [
    "CHARACTER_BRIEF_PROMPT",
    "MAX_CHARACTER_BRIEF_LENGTH",
    "ensure_character_briefs",
    "generate_character_brief",
    "normalize_character_brief",
]
