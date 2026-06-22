from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .media_utils import _optional_suffix_check, _path_namespace_list
from .state import BridgeState, _jsonify


def _validate_reference_audio(voice_path: str) -> None:
    """Validate reference audio for TTS voice cloning (WAV only, 3.0–10.0 s)."""
    if not voice_path.lower().endswith(".wav"):
        raise ValueError("参考语音必须是 WAV 格式")
    from sdk.ui.validators import audio_duration_between

    ok, err = audio_duration_between(voice_path, 3.0, 10.0, "参考语音")
    if not ok:
        raise ValueError(err)


def _normalize_sprite_voice_type(value: Any, *, allow_empty: bool = False) -> str:
    voice_type = str(value or "").strip().lower()
    if not voice_type and allow_empty:
        return ""
    if voice_type not in {"preset", "reference"}:
        raise ValueError("voice type must be preset or reference")
    return voice_type


def _has_gpt_sovits_model(character: Any) -> bool:
    return bool(
        str(getattr(character, "gpt_model_path", "") or "").strip()
        and str(getattr(character, "sovits_model_path", "") or "").strip()
    )


def _default_sprite_voice_type(character: Any) -> str:
    return "reference" if _has_gpt_sovits_model(character) else "preset"


def _as_character_config(character: Any) -> Any:
    from config.character_config import CharacterConfig

    data = character.model_dump(mode="json") if hasattr(character, "model_dump") else dict(character)
    return CharacterConfig.parse_dic(data)


def _is_remote_url(url: str) -> bool:
    host = (urlparse(str(url or "")).hostname or "").lower()
    return bool(host and host not in {"127.0.0.1", "localhost", "0.0.0.0", "::1"})


def _uses_remote_gpt_sovits(state: BridgeState) -> bool:
    api_config = state.config_manager.config.api_config
    provider = str(getattr(api_config, "tts_provider", "") or "").strip().lower()
    return provider == "kaggle-gpt-sovits" or (
        provider == "gpt-sovits" and _is_remote_url(str(getattr(api_config, "gpt_sovits_url", "") or ""))
    )


def _validate_character_payload(body: dict[str, Any], *, allow_remote_voice_paths: bool = False) -> None:
    from sdk.ui.validators import (
        ascii_only,
        audio_duration_between,
        check_all,
        file_exists,
        no_quotes,
        not_empty,
    )

    sprite_prefix = str(body.get("sprite_prefix") or "").strip()
    gpt_model_path = str(body.get("gpt_model_path") or "").strip()
    sovits_model_path = str(body.get("sovits_model_path") or "").strip()
    refer_audio_path = str(body.get("refer_audio_path") or "").strip()
    checks = [
        not_empty(sprite_prefix, "立绘目录"),
        ascii_only(sprite_prefix, "立绘目录"),
        no_quotes(gpt_model_path, "GPT 模型路径"),
        _optional_suffix_check(gpt_model_path, ".ckpt", "GPT 模型路径"),
        no_quotes(sovits_model_path, "SoVITS 模型路径"),
        _optional_suffix_check(sovits_model_path, ".pth", "SoVITS 模型路径"),
        no_quotes(refer_audio_path, "参考音频"),
    ]
    if not allow_remote_voice_paths:
        checks.extend([
            file_exists(gpt_model_path, "GPT 模型路径"),
            file_exists(sovits_model_path, "SoVITS 模型路径"),
            file_exists(refer_audio_path, "参考音频"),
            audio_duration_between(refer_audio_path, 3.0, 10.0, "参考音频"),
        ])
    ok, errors = check_all(*checks)
    if not ok:
        raise ValueError("\n".join(errors))


def _sprite_voice_path(sprite: Any) -> str:
    if hasattr(sprite, "voice_path"):
        return str(sprite.voice_path or "")
    if isinstance(sprite, dict):
        return str(sprite.get("voice_path") or "")
    return ""


def _validate_sprite_voice_duration(voice_path: str, voice_text: str) -> None:
    if not voice_text.strip():
        return
    from sdk.ui.validators import audio_duration_between

    ok, err = audio_duration_between(voice_path, 3.0, 10.0, "语音")
    if not ok:
        raise ValueError(err)


def _save_character(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    from config.schema import Character

    body = payload.get("character", payload)
    if not isinstance(body, dict):
        raise ValueError("character payload must be an object")
    original_name = str(payload.get("originalName") or body.get("name") or "").strip()
    _validate_character_payload(body, allow_remote_voice_paths=_uses_remote_gpt_sovits(state))
    character = Character.model_validate(body)
    saved_name = character.name.strip()
    message, _names = state.character_manager.add_character(
        saved_name,
        str(character.color or "").strip() or "#d07d7d",
        character.sprite_prefix.strip() or "temp",
        str(character.gpt_model_path or "").strip(),
        str(character.sovits_model_path or "").strip(),
        str(character.refer_audio_path or "").strip(),
        str(character.prompt_text or "").strip(),
        str(character.prompt_lang or "").strip(),
        str(character.character_setting or "").strip(),
        speech_speed=character.speech_speed,
        speech_volume=character.speech_volume,
        pronunciation_map=character.pronunciation_map,
        edit_as_name=original_name,
        emotion_tags=str(character.emotion_tags or ""),
    )
    if message.startswith("名称不能为空") or "已与其他角色重复" in message or message.startswith("保存失败"):
        raise RuntimeError(message)
    state.config_manager.reload()
    saved = state.config_manager.get_character_by_name(saved_name)
    return _jsonify(saved or character)


def _character_by_name(state: BridgeState, name: str) -> Any:
    character = state.config_manager.get_character_by_name(name)
    if character is None:
        raise KeyError(f"character not found: {name}")
    return character


def _character_json_after_reload(state: BridgeState, name: str) -> dict[str, Any]:
    state.config_manager.reload()
    return _jsonify(_character_by_name(state, name))


def _check_mem0_before_call() -> dict[str, Any] | None:
    """Check if mem0 is available before a memory operation.

    Returns a :class:`RuntimeDependencyError`-shaped dict if the dependency
    is missing; returns ``None`` if mem0 is ready or needs loading.
    """
    import importlib.util as _importlib_util

    _spec = _importlib_util.find_spec("mem0")
    if _spec is not None:
        return None
    from sdk.exception.types import runtime_dependency_error_from_module

    return runtime_dependency_error_from_module("mem0")


def _get_mem0_status() -> dict[str, Any]:
    """Return mem0 availability status for polling from the frontend.

    Never blocks — returns the current state immediately so the frontend
    can show an appropriate loading dialog.

    Always returns a dict with a ``status`` key matching
    :class:`Mem0Status` on the frontend.
    """
    import importlib.util as _importlib_util

    _spec = _importlib_util.find_spec("mem0")
    if _spec is None:
        from sdk.exception.types import runtime_dependency_error_from_module

        _dep = runtime_dependency_error_from_module("mem0")
        _dep["status"] = "missing_dependency"
        return _dep

    from llm.tools.memory_tools import check_mem0_status

    return check_mem0_status()


def _character_agent_id(name: str) -> str:
    value = str(name or "").strip()
    return value if value else "user"


def _list_character_memories(name: str) -> dict[str, Any]:
    _dep_error = _check_mem0_before_call()
    if _dep_error is not None:
        return _dep_error

    from llm.tools.memory_tools import _get_mem0

    agent_id = _character_agent_id(name)
    mem = _get_mem0()
    raw = mem.get_all(filters={"user_id": agent_id}, limit=200)
    rows = raw.get("results", []) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
    memories = []
    for row in rows:
        if isinstance(row, dict):
            memories.append({"id": str(row.get("id") or ""), "memory": str(row.get("memory") or row.get("content") or "")})
        else:
            memories.append({"id": "", "memory": str(row)})
    return {"agentId": agent_id, "count": len(memories), "memories": memories}


def _add_character_memory(name: str, content: str) -> dict[str, Any]:
    _dep_error = _check_mem0_before_call()
    if _dep_error is not None:
        return _dep_error

    from llm.tools.memory_tools import memory_remember

    text = str(content or "").strip()
    if not text:
        raise ValueError("memory content is required")
    result = memory_remember(text, character_name=_character_agent_id(name))
    if isinstance(result, dict) and result.get("error"):
        raise RuntimeError(str(result["error"]))
    return _list_character_memories(name)


def _delete_character_memory(name: str, memory_id: str) -> dict[str, Any]:
    _dep_error = _check_mem0_before_call()
    if _dep_error is not None:
        return _dep_error

    from llm.tools.memory_tools import memory_forget

    mid = str(memory_id or "").strip()
    if not mid:
        raise ValueError("memory id is required")
    result = memory_forget(mid)
    if isinstance(result, dict) and result.get("error"):
        raise RuntimeError(str(result["error"]))
    return _list_character_memories(name)


def _generate_character_setting(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    setting = str(payload.get("setting") or "")
    message, character_setting = state.character_manager.generate_character_setting(name, setting)
    return {"characterSetting": character_setting, "message": message}


def _translate_character_fields(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    from ui.settings_ui.ai_field_translate import translate_character_name_and_tags

    ui_language = str(getattr(state.config_manager.config.system_config, "ui_language", "") or "")
    error, name, emotion_tags, character_setting = translate_character_name_and_tags(
        state.config_manager,
        ui_language,
        str(payload.get("name") or ""),
        str(payload.get("emotionTags") or ""),
        str(payload.get("characterSetting") or ""),
    )
    if error:
        return {"characterSetting": character_setting, "emotionTags": emotion_tags, "error": error, "name": name}
    return {"characterSetting": character_setting, "emotionTags": emotion_tags, "name": name}


def _upload_sprite_voice(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    sprite_index = int(payload.get("spriteIndex") or 0)
    voice_path = str(payload.get("voicePath") or "").strip()
    voice_text = str(payload.get("voiceText") or "").strip()
    character = _character_by_name(state, name)
    voice_type = _normalize_sprite_voice_type(payload.get("voiceType"), allow_empty=True)
    if not voice_type:
        voice_type = _default_sprite_voice_type(character)
    if not voice_path:
        raise ValueError("voice path is required")
    if voice_type == "reference":
        _validate_reference_audio(voice_path)
    elif voice_type != "preset" and voice_text.strip():
        _validate_sprite_voice_duration(voice_path, voice_text)
    message, _path = state.character_manager.upload_voice(name, sprite_index, voice_path, voice_text, voice_type)
    if message.startswith("找不到") or message.startswith("立绘不存在") or message.startswith("请选择") or message.startswith("请先"):
        raise RuntimeError(message)
    return _character_json_after_reload(state, name)


def _upload_character_sprites(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    emotion_tags = str(payload.get("emotionTags") or "")
    paths = payload.get("paths") or []
    if not isinstance(paths, list):
        raise ValueError("paths must be a list")
    message, _paths, _tags = state.character_manager.upload_sprites(
        name,
        _path_namespace_list([str(item) for item in paths]),
        emotion_tags,
    )
    if message.startswith("找不到") or message.startswith("请选择") or message.startswith("请先"):
        raise RuntimeError(message)
    return _character_json_after_reload(state, name)


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


def _delete_character_sprite(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    sprite_index = int(payload.get("spriteIndex") or 0)
    message, _paths, _tags = state.character_manager.delete_single_sprite(name, sprite_index)
    if message.startswith("找不到") or message.startswith("立绘不存在") or message.startswith("请先"):
        raise RuntimeError(message)
    return _character_json_after_reload(state, name)


def _delete_all_character_sprites(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    message, _paths, _tags = state.character_manager.delete_all_sprites(name)
    if message.startswith("找不到") or message.startswith("请先"):
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


def _save_sprite_voice_text(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    sprite_index = int(payload.get("spriteIndex") or 0)
    voice_text = str(payload.get("voiceText") or "").strip()
    character = _character_by_name(state, name)
    sprites = getattr(character, "sprites", []) or []
    if 0 <= sprite_index < len(sprites):
        _s = sprites[sprite_index]
        if hasattr(_s, "voice_type"):
            _vt = _s.voice_type
        else:
            _vt = _s.get("voice_type") if isinstance(_s, dict) else None
        if _vt != "preset":
            voice_path = _sprite_voice_path(_s)
            if voice_path and Path(voice_path).is_file():
                _validate_sprite_voice_duration(voice_path, voice_text)
    message = state.character_manager.save_sprite_voice_text(name, sprite_index, voice_text)
    if message.startswith("找不到") or message.startswith("立绘不存在") or message.startswith("请先"):
        raise RuntimeError(message)
    return _character_json_after_reload(state, name)


def _save_sprite_voice_type(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    sprite_index = int(payload.get("spriteIndex") or 0)
    voice_type = _normalize_sprite_voice_type(payload.get("voiceType"))
    character = _character_by_name(state, name)
    sprites = getattr(character, "sprites", []) or []
    if voice_type == "reference" and 0 <= sprite_index < len(sprites):
        voice_path = _sprite_voice_path(sprites[sprite_index])
        if voice_path:
            if not Path(voice_path).is_file():
                raise ValueError("reference audio file does not exist")
            _validate_reference_audio(voice_path)
    message = state.character_manager.save_sprite_voice_type(name, sprite_index, voice_type)
    if message.startswith("找不到") or message.startswith("立绘不存在") or message.startswith("请先"):
        raise RuntimeError(message)
    return _character_json_after_reload(state, name)


def _delete_sprite_voice(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    sprite_index = int(payload.get("spriteIndex") or 0)
    message = state.character_manager.delete_sprite_voice(name, sprite_index)
    if message.startswith("找不到") or message.startswith("立绘不存在") or message.startswith("请先"):
        raise RuntimeError(message)
    return _character_json_after_reload(state, name)
