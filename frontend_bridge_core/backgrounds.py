from __future__ import annotations

from typing import Any

from .media_utils import _path_namespace_list, _tag_content
from .state import BridgeState, _jsonify


def _save_background(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    body = payload.get("background", payload)
    if not isinstance(body, dict):
        raise ValueError("background payload must be an object")
    name = str(body.get("name") or "").strip()
    prefix = str(body.get("sprite_prefix") or "temp").strip() or "temp"
    original_name = str(payload.get("originalName") or "").strip()
    message, _names = state.background_manager.add_background(name, prefix, edit_as_name=original_name or None)
    if message.startswith("名称") or "重复" in message or message.startswith("找不到"):
        raise RuntimeError(message)
    state.config_manager.reload()
    saved = state.config_manager.get_background_by_name(name)
    if saved is None:
        raise RuntimeError(message)
    return _jsonify(saved)


def _background_by_name(state: BridgeState, name: str) -> Any:
    background = state.config_manager.get_background_by_name(name)
    if background is None:
        raise KeyError(f"background not found: {name}")
    return background


def _background_json_after_reload(state: BridgeState, name: str) -> dict[str, Any]:
    state.config_manager.reload()
    return _jsonify(_background_by_name(state, name))


def _numbered_background_bgm_tags(tags: list[str]) -> str:
    return "".join(f"音乐 {index + 1}：{str(tag or '').strip()}\n" for index, tag in enumerate(tags))


def _translate_background_fields(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    from ui.settings_ui.ai_field_translate import translate_background_fields

    row_tag_payload = payload.get("bgmRowTags")
    if isinstance(row_tag_payload, list):
        bgm_row_tags = [str(item or "") for item in row_tag_payload]
    else:
        bgm_row_tags = [_tag_content(line) for line in str(payload.get("bgmTags") or "").splitlines()]
    ui_language = str(getattr(state.config_manager.config.system_config, "ui_language", "") or "")
    error, name, bg_tags, bgm_tags, bgm_row_tags = translate_background_fields(
        state.config_manager,
        ui_language,
        str(payload.get("name") or ""),
        str(payload.get("bgTags") or ""),
        str(payload.get("bgmTags") or ""),
        bgm_row_tags,
    )
    response_bgm_tags = _numbered_background_bgm_tags(bgm_row_tags) if bgm_row_tags else bgm_tags
    if bgm_row_tags:
        bgm_tags = response_bgm_tags
    if error:
        return {"bgTags": bg_tags, "bgmRowTags": bgm_row_tags, "bgmTags": bgm_tags, "error": error, "name": name}
    return {"bgTags": bg_tags, "bgmRowTags": bgm_row_tags, "bgmTags": bgm_tags, "name": name}


def _upload_background_images(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    files = _path_namespace_list(payload.get("paths") or [])
    message, _paths, _tags = state.background_manager.upload_sprites(name, files, str(payload.get("bgTags") or ""))
    if message.startswith("找不到") or message.startswith("请选择") or message.startswith("请先"):
        raise RuntimeError(message)
    return _background_json_after_reload(state, name)


def _upload_background_bgm(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    files = _path_namespace_list(payload.get("paths") or [])
    background = _background_by_name(state, name)
    background.bgm_tags = str(payload.get("bgmTags") or background.bgm_tags or "")
    state.config_manager.save_background_config()
    message, _df, _tags = state.background_manager.upload_bgms(name, files)
    if message.startswith("找不到") or message.startswith("请选择") or message.startswith("请先"):
        raise RuntimeError(message)
    return _background_json_after_reload(state, name)


def _save_background_image_tags(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    message = state.background_manager.upload_bg_tags(name, str(payload.get("bgTags") or ""))
    if message.startswith("找不到") or message.startswith("请") or "出错" in message:
        raise RuntimeError(message)
    return _background_json_after_reload(state, name)


def _save_background_bgm_tags(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    message = state.background_manager.upload_bgm_tags(name, str(payload.get("bgmTags") or ""))
    if message.startswith("找不到") or message.startswith("请") or "出错" in message:
        raise RuntimeError(message)
    return _background_json_after_reload(state, name)


def _delete_background_image(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    index = int(payload.get("index") or 0)
    message, _paths, _tags = state.background_manager.delete_single_sprite(name, index)
    if message.startswith("找不到") or message.startswith("背景图片不存在") or message.startswith("请先"):
        raise RuntimeError(message)
    return _background_json_after_reload(state, name)


def _delete_all_background_images(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    message, _paths, _tags = state.background_manager.delete_all_sprites(name)
    if message.startswith("找不到") or message.startswith("请先"):
        raise RuntimeError(message)
    return _background_json_after_reload(state, name)


def _delete_background_bgm(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    index = int(payload.get("index") or 0)
    message, _paths, _tags = state.background_manager.delete_single_bgm(name, index)
    if message.startswith("找不到") or message.startswith("背景音乐不存在") or message.startswith("请先"):
        raise RuntimeError(message)
    return _background_json_after_reload(state, name)


def _delete_all_background_bgm(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    message, _paths, _tags = state.background_manager.delete_all_bgms(name)
    if message.startswith("找不到") or message.startswith("请先"):
        raise RuntimeError(message)
    return _background_json_after_reload(state, name)
