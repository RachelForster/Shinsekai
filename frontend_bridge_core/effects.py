from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from .state import BridgeState, _jsonify

EFFECT_UPLOAD_DIR = "data/effects"


def _effect_dir(name: str) -> Path:
    """Get the managed directory for an effect's audio files."""
    return Path(EFFECT_UPLOAD_DIR) / name


def _effect_by_name(state: BridgeState, name: str) -> Any:
    effect = state.config_manager.get_effect_by_name(name)
    if effect is None:
        raise KeyError(f"effect not found: {name}")
    return effect


def _effect_json_after_reload(state: BridgeState, name: str) -> dict[str, Any]:
    state.config_manager.reload()
    return _jsonify(_effect_by_name(state, name))


def _save_effect(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    body = payload.get("effect", payload)
    if not isinstance(body, dict):
        raise ValueError("effect payload must be an object")
    name = str(body.get("name") or "").strip()
    original_name = str(payload.get("originalName") or "").strip()

    if not name:
        raise ValueError("特效方案名称不能为空。")

    effect_list = state.config_manager.config.effect_list
    from config.schema import Effect as EffectModel

    if original_name:
        original = state.config_manager.get_effect_by_name(original_name)
        if original is None:
            raise KeyError(f"effect not found: {original_name}")
        effect_list[:] = [e for e in effect_list if e.name.lower() != original_name.lower()]
        # Rename directory if it exists, and update paths
        old_dir = _effect_dir(original_name)
        new_dir = _effect_dir(name)
        if old_dir.is_dir() and old_dir != new_dir:
            new_dir.parent.mkdir(parents=True, exist_ok=True)
            # Update audio_list paths from old dir to new dir
            old_prefix = old_dir.as_posix()
            new_prefix = new_dir.as_posix()
            if "audio_list" in body and isinstance(body["audio_list"], list):
                body["audio_list"] = [
                    p.replace(old_prefix, new_prefix) if isinstance(p, str) and p.startswith(old_prefix) else p
                    for p in body["audio_list"]
                ]
            old_dir.rename(new_dir)
        updated = EffectModel.model_validate(body)
        effect_list.append(updated)
        state.config_manager.save_effect_config()
        _effect_dir(name).mkdir(parents=True, exist_ok=True)
        state.config_manager.reload()
        return _jsonify(_effect_by_name(state, updated.name))

    existing = state.config_manager.get_effect_by_name(name)
    if existing is not None:
        effect_list[:] = [e for e in effect_list if e.name.lower() != name.lower()]
        updated = EffectModel.model_validate(body)
        effect_list.append(updated)
        state.config_manager.save_effect_config()
        _effect_dir(name).mkdir(parents=True, exist_ok=True)
        state.config_manager.reload()
        return _jsonify(_effect_by_name(state, updated.name))

    new_effect = EffectModel.model_validate(body)
    effect_list.append(new_effect)
    state.config_manager.save_effect_config()
    # Ensure the managed audio directory exists
    _effect_dir(name).mkdir(parents=True, exist_ok=True)
    state.config_manager.reload()
    return _jsonify(_effect_by_name(state, new_effect.name))


def _delete_effect(state: BridgeState, name: str) -> dict[str, Any]:
    effect_list = state.config_manager.config.effect_list
    match = None
    for e in effect_list:
        if e.name.lower() == name.lower():
            match = e
            break
    if match is None:
        raise KeyError(f"effect not found: {name}")
    effect_list.remove(match)
    state.config_manager.save_effect_config()
    # Clean up managed audio directory
    ef_dir = _effect_dir(name)
    if ef_dir.is_dir():
        shutil.rmtree(ef_dir, ignore_errors=True)
    return {}


def _upload_effect_audio(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    paths = list(payload.get("paths") or [])
    if not name:
        raise ValueError("特效方案名称不能为空。")
    effect = _effect_by_name(state, name)

    # Ensure managed directory exists
    ef_dir = _effect_dir(name)
    ef_dir.mkdir(parents=True, exist_ok=True)

    audio_list = list(effect.audio_list or [])
    tags = str(payload.get("audioTags") or effect.audio_tags or "")

    for file_path in paths:
        src = Path(str(file_path))
        if not src.exists():
            continue
        # Copy to managed directory
        dest = ef_dir / src.name
        # Avoid overwriting: add suffix if file already exists
        counter = 1
        while dest.exists():
            stem = src.stem
            dest = ef_dir / f"{stem}_{counter}{src.suffix}"
            counter += 1
        shutil.copy2(src, dest)
        dest_str = dest.as_posix()
        if dest_str not in audio_list:
            audio_list.append(dest_str)
            tags += f"特效 {len(audio_list)}：\n"

    effect.audio_list = audio_list
    effect.audio_tags = tags
    state.config_manager.save_effect_config()
    return _effect_json_after_reload(state, name)


def _delete_effect_audio(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    index = int(payload.get("index") or 0)
    effect = _effect_by_name(state, name)

    audio_list = list(effect.audio_list or [])
    if index < 0 or index >= len(audio_list):
        raise IndexError(f"audio index out of range: {index}")

    removed_path = audio_list.pop(index)
    # Delete the file from managed directory
    if removed_path:
        try:
            os.remove(removed_path)
        except OSError:
            pass  # File may already be gone

    # Rebuild tags
    old_tags = str(effect.audio_tags or "")
    tag_lines = [line for line in old_tags.splitlines() if line.strip()]
    if index < len(tag_lines):
        tag_lines.pop(index)
    new_tags = "".join(
        f"特效 {i + 1}：{line.split('：', 1)[-1] if '：' in line else line}\n"
        for i, line in enumerate(tag_lines)
    )

    effect.audio_list = audio_list
    effect.audio_tags = new_tags
    state.config_manager.save_effect_config()
    return _effect_json_after_reload(state, name)


def _delete_all_effect_audio(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    effect = _effect_by_name(state, name)

    # Delete all managed audio files
    for path in (effect.audio_list or []):
        if path:
            try:
                os.remove(path)
            except OSError:
                pass

    effect.audio_list = []
    effect.audio_tags = ""
    state.config_manager.save_effect_config()
    return _effect_json_after_reload(state, name)


def _save_effect_audio_tags(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    effect = _effect_by_name(state, name)
    effect.audio_tags = str(payload.get("audioTags") or "")
    state.config_manager.save_effect_config()
    return _effect_json_after_reload(state, name)
