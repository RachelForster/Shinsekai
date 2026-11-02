from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from application.characters import (
    CharacterExportResult,
    CharacterOperation,
    CharacterUseCase,
    parse_character_request,
)
from application.runtime.state import BridgeState, _jsonify
from frontend_bridge_core.tools import _local_file_access_roots


def _execute_character_request(
    state: BridgeState,
    operation: CharacterOperation,
    payload: dict[str, Any],
    *,
    extra_file_access_roots: Iterable[Path] = (),
) -> Any:
    request = parse_character_request(operation, payload)
    roots = (*_local_file_access_roots(state), *extra_file_access_roots)
    return CharacterUseCase(state, file_access_roots=roots).execute(request)


def character_response_payload(result: Any) -> Any:
    """Project application results onto the character HTTP response shape."""

    if isinstance(result, CharacterExportResult):
        return {
            "downloadUrl": f"/api/download?path={result.path}",
            "path": result.path,
        }
    return result


def _character_json_after_reload(state: BridgeState, name: str) -> dict[str, Any]:
    state.config_manager.reload()
    character = state.config_manager.get_character_by_name(name)
    if character is None:
        raise KeyError(f"character not found: {name}")
    return _jsonify(character)


def _generate_character_setting(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    from application.characters.generate_character import generate_character

    name = str(payload.get("name") or "").strip()
    setting = str(payload.get("setting") or "")
    result = generate_character(
        state.character_manager,
        state.config_manager,
        name,
        setting,
    )
    return {
        "characterBrief": result.character_brief,
        "characterSetting": result.character_setting,
        "message": result.message,
    }


def _generate_character_brief(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    from application.characters.generate_briefs import generate_character_brief

    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("角色名称不能为空")
    brief = generate_character_brief(
        state.config_manager,
        name,
        str(payload.get("setting") or ""),
    )
    return {"characterBrief": brief, "message": "输出成功"}


def _ensure_character_briefs(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    from application.characters.generate_briefs import ensure_character_briefs

    names = payload.get("names")
    if not isinstance(names, list):
        raise ValueError("names must be a list")
    characters, generated_names = ensure_character_briefs(
        state.config_manager,
        names,
    )
    return {
        "characters": [_jsonify(character) for character in characters],
        "generatedNames": generated_names,
    }


def _translate_character_fields(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    from application.localization.field_translation import (
        translate_character_name_and_tags,
    )

    ui_language = str(getattr(state.config_manager.config.system_config, "ui_language", "") or "")
    error, name, emotion_tags, character_setting = translate_character_name_and_tags(
        state.config_manager,
        ui_language,
        str(payload.get("name") or ""),
        str(payload.get("emotionTags") or ""),
        str(payload.get("characterSetting") or ""),
    )
    if error:
        return {
            "characterSetting": character_setting,
            "emotionTags": emotion_tags,
            "error": error,
            "name": name,
        }
    return {
        "characterSetting": character_setting,
        "emotionTags": emotion_tags,
        "name": name,
    }


def _save_character_emotion_tags(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    emotion_tags = str(payload.get("emotionTags") or "")
    message = state.character_manager.upload_emotion_tags(name, emotion_tags)
    if (
        message.startswith("请先")
        or message.startswith("请输入")
        or message.startswith("找不到")
        or message.startswith("标注出错")
    ):
        raise RuntimeError(message)
    return _character_json_after_reload(state, name)


def _save_sprite_scale(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    scale = float(payload.get("scale") or 0)
    message = state.character_manager.save_sprite_scale(name, scale)
    text = str(message[0] if isinstance(message, tuple) else message)
    if text.startswith("名称不能为空") or text.startswith("找不到"):
        raise RuntimeError(text)
    return _character_json_after_reload(state, name)

def _validate_reference_audio(voice_path: str) -> None:
    """参考音频校验：仅限 WAV 格式，时长 3-10 秒"""
    from sdk.ui.validators import audio_duration_between

    ext = Path(voice_path).suffix.lower()
    if ext != ".wav":
        raise ValueError("参考语音仅支持 WAV 格式")
    ok, err = audio_duration_between(voice_path, 3.0, 10.0, "参考语音")
    if not ok:
        raise ValueError(err)


def _list_character_scenarios(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    scenarios = state.character_manager.get_character_scenarios(name)
    return {"scenarios": scenarios, "name": name}


def _save_character_scenarios(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    scenarios = payload.get("scenarios") or []
    message = state.character_manager.save_character_scenarios(name, scenarios)
    if message.startswith("找不到") or message.startswith("请先"):
        raise RuntimeError(message)
    return _character_json_after_reload(state, name)


def _upload_scenario_voice(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    scenario_index = int(payload.get("scenarioIndex") or 0)
    voice_path = str(payload.get("voicePath") or "").strip()
    voice_text = str(payload.get("voiceText") or "").strip()
    voice_type = str(payload.get("voiceType") or "").strip().lower()
    if not voice_path:
        raise ValueError("voice path is required")
    from sdk.path_utils import safe_existing_file_path
    voice_path = str(safe_existing_file_path(voice_path, roots=_local_file_access_roots(state)))
    if voice_type == "reference":
        _validate_reference_audio(voice_path)
    elif voice_type != "preset" and voice_text.strip():
        _validate_reference_audio(voice_path)
    scenarios = payload.get("scenarios")
    if scenarios is not None and not isinstance(scenarios, list):
        raise ValueError("scenarios must be a list")
    message, _path = state.character_manager.upload_scenario_voice(
        name, scenario_index, voice_path, voice_text, voice_type, scenarios=scenarios,
    )
    if message.startswith("找不到") or message.startswith("情景不存在") or message.startswith("请先") or message.startswith("请选择"):
        raise RuntimeError(message)
    return _character_json_after_reload(state, name)


def _delete_scenario_voice(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    scenario_index = int(payload.get("scenarioIndex") or 0)
    message = state.character_manager.delete_scenario_voice(name, scenario_index)
    if message.startswith("找不到") or message.startswith("情景不存在"):
        raise RuntimeError(message)
    return _character_json_after_reload(state, name)


def _save_scenario_voice_text(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    scenario_index = int(payload.get("scenarioIndex") or 0)
    voice_text = str(payload.get("voiceText") or "").strip()
    message = state.character_manager.save_scenario_voice_text(name, scenario_index, voice_text)
    if message.startswith("找不到"):
        raise RuntimeError(message)
    return _character_json_after_reload(state, name)


def _save_scenario_voice_type(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    scenario_index = int(payload.get("scenarioIndex") or 0)
    voice_type = str(payload.get("voiceType") or "").strip().lower()
    if not voice_type:
        raise ValueError("voice type is required")
    message = state.character_manager.save_scenario_voice_type(name, scenario_index, voice_type)
    if message.startswith("找不到"):
        raise RuntimeError(message)
    return _character_json_after_reload(state, name)


def _translate_scenario_names(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    """AI translate scenario tag names to English."""
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")
    from application.localization.scenario_translation import translate_scenario_names

    character = state.config_manager.get_character_by_name(name)
    if character is None:
        raise KeyError(f"character not found: {name}")
    names = payload.get("names")
    if names is None:
        names = [scenario.name for scenario in character.scenarios]
    if not isinstance(names, list) or not all(isinstance(item, str) for item in names):
        raise ValueError("names must be a list of strings")
    return {"translated": translate_scenario_names(state.config_manager, names)}
