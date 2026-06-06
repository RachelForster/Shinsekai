from __future__ import annotations

from pathlib import Path
from typing import Any

from .media_utils import _optional_suffix_check, _path_namespace_list
from .state import BridgeState, _jsonify


def _as_character_config(character: Any) -> Any:
    from config.character_config import CharacterConfig

    data = character.model_dump(mode="json") if hasattr(character, "model_dump") else dict(character)
    return CharacterConfig.parse_dic(data)


def _validate_character_payload(body: dict[str, Any]) -> None:
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
    ok, errors = check_all(
        not_empty(sprite_prefix, "立绘目录"),
        ascii_only(sprite_prefix, "立绘目录"),
        no_quotes(gpt_model_path, "GPT 模型路径"),
        file_exists(gpt_model_path, "GPT 模型路径"),
        _optional_suffix_check(gpt_model_path, ".ckpt", "GPT 模型路径"),
        no_quotes(sovits_model_path, "SoVITS 模型路径"),
        file_exists(sovits_model_path, "SoVITS 模型路径"),
        _optional_suffix_check(sovits_model_path, ".pth", "SoVITS 模型路径"),
        no_quotes(refer_audio_path, "参考音频"),
        file_exists(refer_audio_path, "参考音频"),
        audio_duration_between(refer_audio_path, 3.0, 10.0, "参考音频"),
    )
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
    _validate_character_payload(body)
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


def _character_agent_id(name: str) -> str:
    value = str(name or "").strip()
    return value if value else "user"


def _list_character_memories(name: str) -> dict[str, Any]:
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
    from llm.tools.memory_tools import memory_remember

    text = str(content or "").strip()
    if not text:
        raise ValueError("memory content is required")
    result = memory_remember(text, character_name=_character_agent_id(name))
    if isinstance(result, dict) and result.get("error"):
        raise RuntimeError(str(result["error"]))
    return _list_character_memories(name)


def _delete_character_memory(name: str, memory_id: str) -> dict[str, Any]:
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
    if not voice_path:
        raise ValueError("voice path is required")
    _validate_sprite_voice_duration(voice_path, voice_text)
    message, _path = state.character_manager.upload_voice(name, sprite_index, voice_path, voice_text)
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


def _sprite_path_value(sprite: Any) -> str:
    if hasattr(sprite, "path"):
        return str(sprite.path or "")
    if isinstance(sprite, dict):
        return str(sprite.get("path") or "")
    return ""


def _sprite_tag_contents(block: str, count: int) -> list[str]:
    lines = [line for line in str(block or "").splitlines() if line.strip()]
    tags: list[str] = []
    for index in range(count):
        line = lines[index] if index < len(lines) else ""
        separator_positions = [position for position in (line.find(":"), line.find("\uff1a")) if position >= 0]
        separator = min(separator_positions) if separator_positions else -1
        tags.append(line[separator + 1 :].strip() if separator >= 0 else line.strip())
    return tags


def _numbered_sprite_tags(tags: list[str]) -> str:
    return "".join(f"\u7acb\u7ed8 {index + 1}\uff1a{tag}\n" for index, tag in enumerate(tags))


def _register_character_sprites(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    items = payload.get("items") or []
    if not name:
        raise ValueError("name is required")
    if not isinstance(items, list) or not items:
        raise ValueError("items must be a non-empty list")

    character = _character_by_name(state, name)
    if character.sprites is None:
        character.sprites = []

    existing_paths = {_sprite_path_value(sprite) for sprite in character.sprites}
    tags = _sprite_tag_contents(str(character.emotion_tags or ""), len(character.sprites))

    for item in items:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        if not Path(path).exists():
            raise FileNotFoundError(f"sprite file not found: {path}")
        label = str(item.get("label") or "").strip()
        if path in existing_paths:
            index = next(
                (sprite_index for sprite_index, sprite in enumerate(character.sprites) if _sprite_path_value(sprite) == path),
                -1,
            )
            if index >= 0 and label:
                tags[index] = label
            continue
        character.sprites.append({"path": path})
        existing_paths.add(path)
        tags.append(label)

    if not character.sprites:
        raise ValueError("no usable sprite paths were provided")

    character.emotion_tags = _numbered_sprite_tags(tags)
    state.config_manager.save_characters_config()
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
        voice_path = _sprite_voice_path(sprites[sprite_index])
        if voice_path and Path(voice_path).is_file():
            _validate_sprite_voice_duration(voice_path, voice_text)
    message = state.character_manager.save_sprite_voice_text(name, sprite_index, voice_text)
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
