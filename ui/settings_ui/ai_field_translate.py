"""使用设置中的 LLM 将表单字段译成当前 UI 语言（与 system_config.ui_language 一致）。"""

from __future__ import annotations

import json
import re
from typing import Any, Tuple

from config.config_manager import ConfigManager
from i18n import normalize_lang


def _target_language_phrase(ui_lang_code: str) -> str:
    c = normalize_lang(ui_lang_code)
    if c == "en":
        return "English"
    if c == "ja":
        return "Japanese (日本語)"
    return "Simplified Chinese (简体中文)"


def _parse_json_object(text: str) -> dict[str, Any]:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t, flags=re.DOTALL)
    t = t.strip()
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        raise ValueError("no_json_object")
    return json.loads(t[i : j + 1])


def _llm_one_shot(config: ConfigManager, system: str, user: str) -> str:
    llm_provider, llm_model, llm_base_url, api_key = config.get_llm_api_config()
    if not llm_provider or not api_key or not llm_model:
        raise ValueError("llm_incomplete")
    from llm.llm_manager import LLMAdapterFactory, LLMManager

    llm_adapter = LLMAdapterFactory.create_adapter(
        llm_provider=llm_provider,
        api_key=api_key,
        base_url=llm_base_url,
        model=llm_model,
    )
    manager = LLMManager(adapter=llm_adapter, user_template=system)
    return manager.chat(user, stream=False, response_format={"type": "text"})


def translate_character_name_and_tags(
    config: ConfigManager,
    ui_lang_code: str,
    name: str,
    emotion_block: str,
    character_setting: str,
) -> Tuple[str, str, str, str]:
    """
    返回 (错误信息, 译后名称, 译后情绪标注块, 译后角色设定长文)。
    无错误时错误信息为 ""。
    """
    n = (name or "").strip()
    e = emotion_block or ""
    s = character_setting or ""
    if not n and not (e and e.strip()) and not (s and s.strip()):
        return "no_content", n, e, s

    target = _target_language_phrase(ui_lang_code)
    system = (
        f"You are a professional translator. Translate the user's fields to {target}. "
        "If the text is already in the target language, return it with minimal edits. "
        "Output ONLY a single JSON object, no markdown fences, no other text. "
        'The JSON must have exactly three string keys: "name", "emotion_block", and "character_setting". '
        "Preserve all line breaks and paragraph structure in emotion_block and character_setting. "
        "Use empty string for a field that had no source text."
    )
    user = json.dumps(
        {"name": n, "emotion_block": e, "character_setting": s},
        ensure_ascii=False,
    )
    try:
        raw = _llm_one_shot(config, system, user)
    except ValueError as ex:
        if str(ex) == "llm_incomplete":
            return "llm_incomplete", n, e, s
        raise
    except Exception as ex:
        return f"llm_error:{ex}", n, e, s

    try:
        d = _parse_json_object(raw)
    except Exception as ex:
        return f"parse_error:{ex}", n, e, s

    out_n = d.get("name", n) if isinstance(d.get("name"), str) else n
    out_e = d.get("emotion_block", e) if isinstance(d.get("emotion_block"), str) else e
    out_s = d.get("character_setting", s) if isinstance(d.get("character_setting"), str) else s
    return "", out_n.strip() if out_n else n, out_e, out_s


def translate_background_fields(
    config: ConfigManager,
    ui_lang_code: str,
    bg_name: str,
    bg_info: str,
    bgm_info: str,
    bgm_row_tags: list[str],
) -> Tuple[str, str, str, str, list[str]]:
    """
    返回 (错误信息, 译后背景名, 背景说明, BGM 整段描述, 与表格行一一对应的标签列表)。
    """
    tags = list(bgm_row_tags or [])
    n = (bg_name or "").strip()
    bgi = bg_info or ""
    bgmi = bgm_info or ""
    if not n and not (bgi and bgi.strip()) and not (bgmi and bgmi.strip()) and not any(
        (t or "").strip() for t in tags
    ):
        return "no_content", n, bgi, bgmi, tags

    target = _target_language_phrase(ui_lang_code)
    system = (
        f"You are a professional translator. Translate the user's fields to {target}. "
        "If the text is already in the target language, return it with minimal edits. "
        "Output ONLY a single JSON object, no markdown fences, no other text. "
        'Keys: "bg_name" (string), "bg_info" (string), "bgm_info" (string), "bgm_row_tags" (array of strings). '
        "The array bgm_row_tags MUST have the same length as in the input, same order (one per BGM table row). "
        "Translate each tag independently; for empty input tags use empty string. "
        "Preserve line breaks in bg_info and bgm_info."
    )
    user = json.dumps(
        {
            "bg_name": n,
            "bg_info": bgi,
            "bgm_info": bgmi,
            "bgm_row_tags": tags,
        },
        ensure_ascii=False,
    )
    try:
        raw = _llm_one_shot(config, system, user)
    except ValueError as ex:
        if str(ex) == "llm_incomplete":
            return "llm_incomplete", n, bgi, bgmi, tags
        raise
    except Exception as ex:
        return f"llm_error:{ex}", n, bgi, bgmi, tags

    try:
        d = _parse_json_object(raw)
    except Exception as ex:
        return f"parse_error:{ex}", n, bgi, bgmi, tags

    out_n = d.get("bg_name", n) if isinstance(d.get("bg_name"), str) else n
    out_bgi = d.get("bg_info", bgi) if isinstance(d.get("bg_info"), str) else bgi
    out_bgmi = d.get("bgm_info", bgmi) if isinstance(d.get("bgm_info"), str) else bgmi
    row_out = d.get("bgm_row_tags")
    if not isinstance(row_out, list) or len(row_out) != len(tags):
        return "bad_bgm_row_tags", n, bgi, bgmi, tags
    new_tags: list[str] = []
    for i, t in enumerate(tags):
        item = row_out[i]
        new_tags.append(str(item) if item is not None else t)
    return (
        "",
        (out_n or n).strip() if out_n else n,
        out_bgi,
        out_bgmi,
        new_tags,
    )
