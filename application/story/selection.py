"""Resolve story authoring selections against the installed resource library."""

from __future__ import annotations

from typing import Any

from application.chat.runtime_process import TRANSPARENT_BACKGROUND_NAME


TEMPLATE_OPTION_KEYS = (
    "useEffect",
    "useCg",
    "useTranslation",
    "useCot",
    "useChoice",
    "useNarration",
    "useStat",
    "maxSpeechChars",
    "maxDialogItems",
    "mediaSelectionMode",
    "workflowPath",
    "effectNames",
    "voiceLanguage",
)


def normal_template_options(state: Any) -> dict:
    """Read the normal mode's settings without regenerating or saving a template."""
    directory = getattr(state, "template_dir_path", "")
    if not directory:
        return {}
    from application.chat.session_store import load_template_session
    from application.chat.templates import _template_session_to_frontend

    saved = _template_session_to_frontend(load_template_session(directory)) or {}
    return {key: saved[key] for key in TEMPLATE_OPTION_KEYS if key in saved}


def generation_selection(state: Any, options: dict) -> tuple[dict, dict]:
    names = options.get("characters")
    if not isinstance(names, list) or not names or len(names) > 128:
        raise ValueError("请选择 1 至 128 位人物。")
    if any(not isinstance(name, str) or not name.strip() for name in names):
        raise ValueError("人物名称无效。")
    names = list(dict.fromkeys(names))
    mode = options.get("characterPromptMode", "full")
    if mode not in {"full", "compact"}:
        raise ValueError("请先设置主次人物。")
    primary = names if mode == "full" else options.get("primaryCharacters")
    if (
        not isinstance(primary, list)
        or not primary
        or any(name not in names for name in primary)
    ):
        raise ValueError("请至少选择一位已出场的主要人物。")
    background = str(options.get("backgroundName") or TRANSPARENT_BACKGROUND_NAME)
    record = state.config_manager.get_background_by_name(background)
    if background != TRANSPARENT_BACKGROUND_NAME and record is None:
        raise ValueError(f"背景不存在：{background}")
    characters = []
    for index, name in enumerate(names):
        character = state.config_manager.get_character_by_name(name)
        if character is None:
            raise ValueError(f"人物不存在：{name}")
        is_primary = name in primary
        setting = str(
            getattr(character, "character_setting", "")
            if is_primary
            else getattr(character, "character_brief", "")
        ).strip()
        if not is_primary and not setting:
            raise ValueError(f"请先为次要人物生成简介：{name}")
        characters.append(
            {
                "id": f"selected-{index + 1}",
                "name": name,
                "characterSetting": setting,
                "importance": "primary" if is_primary else "secondary",
                "source": {"type": "local-library", "characterId": name},
            }
        )
    resolved = {
        **normal_template_options(state),
        **options,
        "characters": names,
        "characterPromptMode": mode,
        "primaryCharacters": list(dict.fromkeys(primary)),
        "backgroundName": background,
    }
    resolved.pop("templateId", None)
    return resolved, {
        "characters": characters,
        "backgrounds": [background] if record and record.sprites else [],
    }
