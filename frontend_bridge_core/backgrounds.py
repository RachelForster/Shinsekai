from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from application.backgrounds import (
    BackgroundExportResult,
    BackgroundOperation,
    BackgroundUseCase,
    parse_background_request,
)
from application.runtime.state import BridgeState, _jsonify
from frontend_bridge_core.media_utils import _tag_content
from frontend_bridge_core.tools import _local_file_access_roots


def _execute_background_request(
    state: BridgeState,
    operation: BackgroundOperation,
    payload: dict[str, Any],
    *,
    extra_file_access_roots: Iterable[Path] = (),
) -> Any:
    request = parse_background_request(operation, payload)
    roots = (*_local_file_access_roots(state), *extra_file_access_roots)
    return BackgroundUseCase(state, file_access_roots=roots).execute(request)


def background_response_payload(result: Any) -> Any:
    """Project application results onto the background HTTP response shape."""

    if isinstance(result, BackgroundExportResult):
        return {
            "downloadUrl": f"/api/download?path={result.path}",
            "path": result.path,
        }
    return result


def _background_json_after_reload(state: BridgeState, name: str) -> dict[str, Any]:
    state.config_manager.reload()
    background = state.config_manager.get_background_by_name(name)
    if background is None:
        raise KeyError(f"background not found: {name}")
    return _jsonify(background)


def _numbered_background_bgm_tags(tags: list[str]) -> str:
    return "".join(f"音乐 {index + 1}：{str(tag or '').strip()}\n" for index, tag in enumerate(tags))


def _translate_background_fields(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    from application.localization.field_translation import translate_background_fields

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
        return {
            "bgTags": bg_tags,
            "bgmRowTags": bgm_row_tags,
            "bgmTags": bgm_tags,
            "error": error,
            "name": name,
        }
    return {
        "bgTags": bg_tags,
        "bgmRowTags": bgm_row_tags,
        "bgmTags": bgm_tags,
        "name": name,
    }


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
