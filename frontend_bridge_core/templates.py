from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from core.sprite.chat_branch_storage import ACTIVE_HISTORY_FILENAME, BRANCH_TREE_FILENAME

from .state import BridgeState

MARK_SCENARIO = "<<<EASYAI_USER_SCENARIO>>>"
MARK_SYSTEM = "<<<EASYAI_SYSTEM_TEMPLATE>>>"
TEMP_SPLIT_META = "_temp_split.json"


def _template_dir(state: BridgeState) -> Path:
    path = Path(state.template_dir_path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _template_id(path: Path) -> str:
    return path.name


def _compose_stored_template(scenario: str, system: str) -> str:
    a = (scenario or "").replace("\r\n", "\n").rstrip()
    b = (system or "").replace("\r\n", "\n").rstrip()
    return f"{MARK_SCENARIO}\n{a}\n{MARK_SYSTEM}\n{b}\n"


def _parse_stored_template(raw: str) -> tuple[str, str]:
    text = (raw or "").replace("\r\n", "\n")
    if MARK_SCENARIO in text and MARK_SYSTEM in text:
        try:
            i = text.index(MARK_SCENARIO) + len(MARK_SCENARIO)
            j = text.index(MARK_SYSTEM, i)
            return text[i:j].strip("\n"), text[j + len(MARK_SYSTEM) :].strip("\n")
        except ValueError:
            pass
    text = text.strip()
    return (text, "") if text else ("", "")


def _compose_for_llm(scenario: str, system: str) -> str:
    a = (scenario or "").strip()
    b = (system or "").strip()
    if a and b:
        return f"{a}\n\n{b}"
    return a or b


def _history_id_from_scenario(user_scenario: str, system_template: str) -> str:
    stable = (user_scenario or "").strip() or (system_template or "").strip()
    return hashlib.md5(stable.encode("utf-8")).hexdigest()


def _latest_history_json(history_dir: str) -> Path | None:
    path = Path(history_dir)
    if not path.is_dir():
        return None
    candidates: list[tuple[Path, float]] = [
        (item, item.stat().st_mtime) for item in path.glob("*.json") if item.is_file()
    ]
    candidates.extend(
        (
            item,
            max(
                child.stat().st_mtime
                for child in (
                    item / ACTIVE_HISTORY_FILENAME,
                    item / BRANCH_TREE_FILENAME,
                    item / f"{ACTIVE_HISTORY_FILENAME}.tmp",
                )
                if child.is_file()
            ),
        )
        for item in path.iterdir()
        if item.is_dir()
        and any(
            (item / name).is_file()
            for name in (ACTIVE_HISTORY_FILENAME, BRANCH_TREE_FILENAME, f"{ACTIVE_HISTORY_FILENAME}.tmp")
        )
    )
    candidates.extend(
        (item.parent / item.name[:-4], item.stat().st_mtime)
        for item in path.glob("*.json.tmp")
        if item.is_file()
    )
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[1])[0]


def _read_split_meta(template_dir: Path) -> tuple[str, str] | None:
    meta_path = template_dir / TEMP_SPLIT_META
    if not meta_path.is_file():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    scenario = data.get("scenario", "")
    system = data.get("system", "")
    if not isinstance(scenario, str):
        scenario = ""
    if not isinstance(system, str):
        system = ""
    if scenario.strip() or system.strip():
        return scenario, system
    return None


def _repair_template_parts_from_session_if_needed(
    state: BridgeState,
    scenario: str,
    system: str,
) -> tuple[str, str]:
    if not _has_untranslated_template_keys(scenario, system):
        return scenario, system
    from ui.settings_ui.services.template_tab_session import load_template_session

    repaired = _repair_template_session_if_needed(state, load_template_session(state.template_dir_path))
    if not repaired:
        return scenario, system
    return str(repaired.get("scenario_text") or ""), str(repaired.get("system_template_text") or "")


def _resume_template_parts(state: BridgeState) -> tuple[str, str, str] | None:
    template_dir = _template_dir(state)
    temp_path = template_dir / "_temp.txt"
    if temp_path.is_file() and temp_path.stat().st_size > 0:
        split_meta = _read_split_meta(template_dir)
        if split_meta is not None:
            scenario, system = _repair_template_parts_from_session_if_needed(state, split_meta[0], split_meta[1])
            return scenario, system, "_temp.txt"
        try:
            scenario, system = _parse_stored_template(temp_path.read_text(encoding="utf-8"))
        except OSError:
            scenario, system = "", ""
        if scenario.strip() or system.strip():
            return scenario, system, "_temp.txt"

    candidates = [item for item in template_dir.glob("*.txt") if item.is_file() and item.name != "_temp.txt"]
    if not candidates:
        return None
    path = max(candidates, key=lambda item: item.stat().st_mtime)
    try:
        scenario, system = _parse_stored_template(path.read_text(encoding="utf-8"))
    except OSError:
        return None
    if scenario.strip() or system.strip():
        return scenario, system, path.name
    return None


def _list_templates(state: BridgeState) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(_template_dir(state).glob("*.txt"), key=lambda item: item.name.lower()):
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        scenario, system = _parse_stored_template(raw)
        rows.append(
            {
                "content": _compose_for_llm(scenario, system),
                "id": _template_id(path),
                "name": path.stem,
                "path": path.as_posix(),
                "scenario": scenario,
                "system": system,
                "updatedAt": str(int(path.stat().st_mtime)),
            }
        )
    return rows


def _save_template_summary(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    template = payload.get("template", payload)
    if not isinstance(template, dict):
        raise ValueError("template payload must be an object")
    name = str(template.get("name") or template.get("id") or "").strip()
    if not name:
        raise ValueError("template name is required")
    scenario = str(template.get("scenario") or template.get("content") or "")
    system = str(template.get("system") or "")
    file_name = name if name.endswith(".txt") else f"{name}.txt"
    (_template_dir(state) / file_name).write_text(_compose_stored_template(scenario, system), encoding="utf-8")
    file_name = f"{name}.txt" if not name.endswith(".txt") else name
    for row in _list_templates(state):
        if row["id"] == file_name:
            return row
    raise RuntimeError("template was saved but not found")


def _generate_template_summary(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    selected = payload.get("characters") or []
    if not isinstance(selected, list):
        raise ValueError("characters must be a list")
    background = str(payload.get("backgroundName") or "")
    voice_language = str(payload.get("voiceLanguage") or "").strip()
    if voice_language:
        sc = state.config_manager.config.system_config.model_copy(deep=True)
        sc.voice_language = voice_language
        state.config_manager.config.system_config = sc
        state.config_manager.save_system_config()
    max_speech_chars = max(0, int(payload.get("maxSpeechChars") or 0))
    max_dialog_items = max(0, int(payload.get("maxDialogItems") or 0))
    content, result = state.template_generator.generate_chat_template(
        selected,
        background,
        bool(payload.get("useEffect", True)),
        bool(payload.get("useCg", False)),
        bool(payload.get("useTranslation", True)),
        bool(payload.get("useCot", False)),
        bool(payload.get("useChoice", True)),
        bool(payload.get("useNarration", True)),
        bool(payload.get("useStat", True)),
        max_speech_chars=max_speech_chars,
        max_dialog_items=max_dialog_items,
    )
    output_name = str(result or "").strip()
    name = str(output_name or payload.get("name") or "generated").strip()
    scenario = str(payload.get("scenario") or "")
    row = {
        "content": _compose_for_llm(scenario, content),
        "id": "",
        "name": name,
        "path": "",
        "scenario": scenario,
        "system": content,
        "updatedAt": "",
    }
    row["generationMessage"] = result
    return row


def _safe_session_int(value: Any, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _template_session_to_frontend(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if not raw:
        return None
    return {
        "background": str(raw.get("background") or ""),
        "filenameStub": str(raw.get("filename_stub") or ""),
        "historyPath": str(raw.get("history_file") or ""),
        "initSpritePath": str(raw.get("init_sprite_path") or ""),
        "maxDialogItems": _safe_session_int(raw.get("max_dialog_items")),
        "maxSpeechChars": _safe_session_int(raw.get("max_speech_chars")),
        "roomId": str(raw.get("room_id") or ""),
        "scenario": str(raw.get("scenario_text") or ""),
        "selectedCharacters": [str(item) for item in (raw.get("selected_characters") or []) if str(item)],
        "system": str(raw.get("system_template_text") or ""),
        "templateFileDropdown": str(raw.get("template_file_dropdown") or ""),
        "workflowPath": str(raw.get("workflow_path") or ""),
        "useCg": bool(raw.get("use_cg_yes", False)),
        "useChoice": bool(raw.get("use_choice_yes", True)),
        "useCot": bool(raw.get("use_cot_yes", False)),
        "useEffect": bool(raw.get("use_effect_yes", True)),
        "useNarration": bool(raw.get("use_narration_yes", True)),
        "useStat": bool(raw.get("use_stat_yes", True)),
        "useTranslation": bool(raw.get("use_tr_yes", True)),
        "voiceLanguage": str(raw.get("voice_lang") or ""),
    }


def _load_template_session_payload(state: BridgeState) -> dict[str, Any] | None:
    from ui.settings_ui.services.template_tab_session import load_template_session

    raw = load_template_session(state.template_dir_path)
    raw = _repair_template_session_if_needed(state, raw)
    return _template_session_to_frontend(raw)


def _save_template_session_payload(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    from ui.settings_ui.services.template_tab_session import save_template_session

    data = {
        "selected_characters": payload.get("selectedCharacters") or [],
        "background": str(payload.get("background") or ""),
        "voice_lang": str(payload.get("voiceLanguage") or ""),
        "use_effect_yes": bool(payload.get("useEffect", True)),
        "use_tr_yes": bool(payload.get("useTranslation", True)),
        "use_cg_yes": bool(payload.get("useCg", False)),
        "use_cot_yes": bool(payload.get("useCot", False)),
        "use_choice_yes": bool(payload.get("useChoice", True)),
        "use_narration_yes": bool(payload.get("useNarration", True)),
        "use_stat_yes": bool(payload.get("useStat", True)),
        "max_speech_chars": _safe_session_int(payload.get("maxSpeechChars")),
        "max_dialog_items": _safe_session_int(payload.get("maxDialogItems")),
        "scenario_text": str(payload.get("scenario") or ""),
        "system_template_text": str(payload.get("system") or ""),
        "filename_stub": str(payload.get("filenameStub") or ""),
        "template_file_dropdown": str(payload.get("templateFileDropdown") or ""),
        "init_sprite_path": str(payload.get("initSpritePath") or ""),
        "history_file": str(payload.get("historyPath") or ""),
        "room_id": str(payload.get("roomId") or ""),
        "workflow_path": str(payload.get("workflowPath") or ""),
    }
    save_template_session(state.template_dir_path, data)
    loaded = _load_template_session_payload(state)
    if loaded is None:
        raise RuntimeError("template session was saved but not found")
    return loaded


def _has_untranslated_template_keys(*values: Any) -> bool:
    return any("template_gen." in str(value or "") for value in values)


def _repair_template_session_if_needed(state: BridgeState, raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if not raw or not _has_untranslated_template_keys(raw.get("scenario_text"), raw.get("system_template_text")):
        return raw
    selected = raw.get("selected_characters") or []
    if not isinstance(selected, list) or not selected:
        return raw
    content, _result = state.template_generator.generate_chat_template(
        [str(item) for item in selected if str(item)],
        str(raw.get("background") or ""),
        bool(raw.get("use_effect_yes", True)),
        bool(raw.get("use_cg_yes", False)),
        bool(raw.get("use_tr_yes", True)),
        bool(raw.get("use_cot_yes", False)),
        bool(raw.get("use_choice_yes", True)),
        bool(raw.get("use_narration_yes", True)),
        bool(raw.get("use_stat_yes", True)),
        max_speech_chars=_safe_session_int(raw.get("max_speech_chars")),
        max_dialog_items=_safe_session_int(raw.get("max_dialog_items")),
    )
    repaired = dict(raw)
    if _has_untranslated_template_keys(repaired.get("scenario_text")):
        repaired["scenario_text"] = ""
    repaired["system_template_text"] = content
    try:
        from ui.settings_ui.services.template_tab_session import save_template_session

        save_template_session(state.template_dir_path, repaired)
    except Exception:
        pass
    return repaired
