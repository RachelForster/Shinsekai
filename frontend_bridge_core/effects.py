from __future__ import annotations

import shutil
from pathlib import Path, PureWindowsPath
from typing import Any

from .state import BridgeState, _jsonify

EFFECT_UPLOAD_DIR = "data/effects"


def _validate_effect_storage_name(name: str) -> str:
    """Validate that an effect name can only address one managed directory."""
    value = str(name or "").strip()
    if not value:
        raise ValueError("effect name is required")
    if "\x00" in value:
        raise ValueError("effect name contains an invalid character")
    if "/" in value or "\\" in value:
        raise ValueError("effect name must not contain path separators")

    path = Path(value)
    win_path = PureWindowsPath(value)
    if path.is_absolute() or win_path.is_absolute() or win_path.drive:
        raise ValueError("effect name must not be an absolute path")
    if value in {".", ".."} or any(part in {".", ".."} for part in path.parts):
        raise ValueError("effect name must not contain relative path segments")
    return value


def _effect_root() -> Path:
    return Path(EFFECT_UPLOAD_DIR).resolve()


def _effect_dir(name: str) -> Path:
    """Get the managed directory for an effect's audio files."""
    safe_name = _validate_effect_storage_name(name)
    root = _effect_root()
    candidate = (root / safe_name).resolve()
    if candidate == root or root not in candidate.parents:
        raise ValueError("effect directory escapes managed storage")
    return candidate


def _unlink_managed_effect_file(effect_name: str, raw_path: str) -> None:
    """Remove an audio file only when it is inside the effect's managed dir."""
    if not raw_path:
        return
    try:
        root = _effect_dir(effect_name).resolve()
        target = Path(str(raw_path)).resolve()
    except (OSError, ValueError):
        return
    if root not in target.parents:
        return
    try:
        if target.is_file():
            target.unlink()
    except OSError:
        pass


def _copy_effect_dir(src: Path, dst: Path) -> None:
    """Copy an effect's managed audio directory from src to dst."""
    if not src.is_dir():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        dest = dst / item.name
        if item.is_file():
            shutil.copy2(item, dest)


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
    _validate_effect_storage_name(name)
    if original_name:
        _validate_effect_storage_name(original_name)

    if not name:
        raise ValueError("特效方案名称不能为空。")

    effect_list = state.config_manager.config.effect_list
    from config.schema import Effect as EffectModel

    if original_name:
        original = state.config_manager.get_effect_by_name(original_name)
        if original is None:
            raise KeyError(f"effect not found: {original_name}")
        # Remove the original effect from the list
        effect_list[:] = [e for e in effect_list if e.name.lower() != original_name.lower()]
        # If renaming to a name that already exists, auto-suffix
        existing_names = {e.name.lower() for e in effect_list}
        base_name = name
        counter = 1
        while name.lower() in existing_names:
            name = f"{base_name}_{counter}"
            counter += 1
        if name != base_name:
            body["name"] = name
            print(f"[Effect] 重命名冲突，自动更名为: {name}")
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
            try:
                old_dir.rename(new_dir)
            except OSError:
                # If rename fails (e.g. target already exists), copy instead
                if old_dir.is_dir():
                    _copy_effect_dir(old_dir, new_dir)
                    shutil.rmtree(old_dir, ignore_errors=True)
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
    _validate_effect_storage_name(name)
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
    _validate_effect_storage_name(name)
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
        if not src.is_file():
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
    _validate_effect_storage_name(name)
    index = int(payload.get("index") or 0)
    effect = _effect_by_name(state, name)

    audio_list = list(effect.audio_list or [])
    if index < 0 or index >= len(audio_list):
        raise IndexError(f"audio index out of range: {index}")

    removed_path = audio_list.pop(index)
    _unlink_managed_effect_file(name, removed_path)

    # Rebuild tags — preserve all lines to keep 1:1 audio-to-tag mapping
    old_tags = str(effect.audio_tags or "")
    # Use splitlines() without filtering to maintain index alignment with audio_list
    tag_lines = old_tags.splitlines()
    # Drop trailing empty strings from splitlines (they don't correspond to any audio index)
    while tag_lines and not tag_lines[-1].strip():
        tag_lines.pop()
    if index < len(tag_lines):
        tag_lines.pop(index)
    # Rebuild with fresh numbering, preserving existing tag content after the colon
    new_tags = "".join(
        f"特效 {i + 1}：{line.split('：', 1)[-1].strip() if '：' in line else line.strip()}\n"
        for i, line in enumerate(tag_lines)
    )

    effect.audio_list = audio_list
    effect.audio_tags = new_tags
    state.config_manager.save_effect_config()
    return _effect_json_after_reload(state, name)


def _delete_all_effect_audio(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    _validate_effect_storage_name(name)
    effect = _effect_by_name(state, name)

    # Delete all managed audio files
    for path in (effect.audio_list or []):
        _unlink_managed_effect_file(name, path)

    effect.audio_list = []
    effect.audio_tags = ""
    state.config_manager.save_effect_config()
    return _effect_json_after_reload(state, name)


def _save_effect_audio_tags(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    _validate_effect_storage_name(name)
    effect = _effect_by_name(state, name)
    new_tags = str(payload.get("audioTags") or "")
    effect.audio_tags = new_tags
    # 检查每个音频是否都有对应提示词
    tag_lines = new_tags.splitlines()
    audio_count = len(effect.audio_list or [])
    missing = []
    for i in range(audio_count):
        line = tag_lines[i] if i < len(tag_lines) else ""
        # 提取冒号后的内容作为提示词
        if "：" in line:
            keyword = line.split("：", 1)[-1].strip()
        elif ":" in line:
            keyword = line.split(":", 1)[-1].strip()
        else:
            keyword = line.strip()
        if not keyword:
            missing.append(str(i + 1))
    if missing:
        print(f"[Effect] 警告：特效方案 '{name}' 的第 {', '.join(missing)} 个音频未输入提示词，将无法通过关键词触发。")
    state.config_manager.save_effect_config()
    return _effect_json_after_reload(state, name)


def _build_effect_usage_guide(state: BridgeState, effect_names: list[str]) -> str:
    """Generate a usage guide for selected effects to inject into the system prompt.

    Tells the LLM:
    - Which effects are available and their keywords
    - How to use loop:/stop:/before:/after: prefixes
    """
    if not effect_names:
        return ""

    lines: list[str] = []
    lines.append("[特效音效系统]")
    lines.append("你可以在 JSON 输出的 effect 字段中使用以下特效，格式示例：")
    lines.append('  {"effect": "关键词"}            → 对话前播放一次')
    lines.append('  {"effect": "loop:关键词"}       → 开始循环播放（雨声、风声等持续性音效）')
    lines.append('  {"effect": "stop:关键词"}       → 停止该关键词的循环播放')
    lines.append('  {"effect": "before:关键词"}     → 对话前播放一次（同无前缀）')
    lines.append('  {"effect": "after:关键词"}      → 对话后播放一次')
    lines.append("")

    for ef_name in effect_names:
        ef = state.config_manager.get_effect_by_name(ef_name)
        if ef is None:
            continue
        tags = (ef.audio_tags or "").splitlines()
        audio_list = ef.audio_list or []
        all_kw: list[str] = []
        for i, tag_line in enumerate(tags):
            tag_line = tag_line.strip()
            if not tag_line:
                continue
            if "：" in tag_line:
                keyword = tag_line.split("：", 1)[-1].strip()
            elif ":" in tag_line:
                keyword = tag_line.split(":", 1)[-1].strip()
            else:
                keyword = tag_line
            if keyword and i < len(audio_list) and audio_list[i]:
                # 拆分逗号分隔的多关键词
                for kw in keyword.split(","):
                    kw = kw.strip()
                    if kw:
                        all_kw.append(kw)

        if all_kw:
            lines.append(f"「{ef_name}」可触发：{', '.join(all_kw)}")
        else:
            lines.append(f"「{ef_name}」已加载但未配置触发词")

    lines.append("")
    lines.append("注意：仅在适当时机使用特效，过度使用会破坏沉浸感。effect 字段为可选，无需求时省略。")
    return "\n".join(lines)
