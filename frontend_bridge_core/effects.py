from __future__ import annotations

import os
import threading
from copy import deepcopy
from functools import wraps
from pathlib import Path, PureWindowsPath
from typing import Any

from sdk.file_transactions import (
    copy_file_exclusive_with_identity,
    portable_name_key,
    remove_directory_without_links,
    remove_empty_directory_without_links,
    remove_file_without_links,
    replace_directory_transactionally,
)
from sdk.path_contract import (
    managed_project_directory,
    managed_project_storage,
    path_is_link_or_reparse_point,
    project_root as runtime_project_root,
    require_directory_without_links,
    resolve_managed_project_path,
    resolve_runtime_asset_read_path,
    safe_path_component,
    safe_path_component_with_suffix,
)

from sdk.path_references import (
    make_path_reference,
    path_reference_value,
    project_relative_path,
    resolved_path_is_within,
    state_project_root,
)
from .security import portable_path_text, safe_existing_file_path
from application.runtime.state import BridgeState, _jsonify

EFFECT_UPLOAD_DIR = "data/effects"
_EFFECT_MUTATION_LOCK = threading.RLock()


def _serialized_effect_mutation(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with _EFFECT_MUTATION_LOCK:
            return function(*args, **kwargs)

    return wrapped


def _restore_model(target: Any, snapshot: Any) -> None:
    for field_name in type(target).model_fields:
        setattr(target, field_name, deepcopy(getattr(snapshot, field_name)))


def _unlink_created_files(
    paths: list[tuple[Path, os.stat_result]],
) -> None:
    for path, identity in reversed(paths):
        try:
            remove_file_without_links(
                path,
                missing_ok=True,
                expected_identity=identity,
            )
        except (OSError, ValueError):
            pass


def _validate_effect_storage_name(name: str) -> str:
    """Validate that an effect name can only address one managed directory."""
    value = str(name or "")
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
    return safe_path_component(value, field="effect name")


def _effect_root(state: BridgeState | None = None) -> Path:
    project_root = state_project_root(state) if state is not None else runtime_project_root()
    return managed_project_storage(EFFECT_UPLOAD_DIR, root=project_root)


def _effect_dir(name: str, state: BridgeState | None = None) -> Path:
    """Get the managed directory for an effect's audio files."""
    safe_name = _validate_effect_storage_name(name)
    project_root = state_project_root(state) if state is not None else runtime_project_root()
    return managed_project_directory(EFFECT_UPLOAD_DIR, safe_name, root=project_root)


def _canonical_effect_audio_value(
    state: BridgeState,
    effect_name: str,
    raw_path: str,
) -> str:
    raw = str(raw_path or "")
    if not raw:
        return ""
    raw = portable_path_text(raw, field="effect audio path")
    root = state_project_root(state)
    try:
        reference = make_path_reference(
            raw,
            root,
            legacy_project_prefixes=(("data", "effects"),),
            resource_prefixes=(("assets", "system", "sound"),),
            # This is the non-destructive launch-time repair path.  Recover
            # absolute references left by a moved pre-contract installation
            # before the child runtime reads effect.yaml.  Destructive effect
            # operations deliberately keep recovery disabled below so a
            # missing external file can never retarget a deletion.
            recover_legacy_absolute=True,
        )
        value = path_reference_value(reference) or raw
        if reference is not None and reference.get("scope") == "project":
            target = resolve_managed_project_path(value, root=root)
            if resolved_path_is_within(target, _effect_dir(effect_name, state)):
                return project_relative_path(target, root) or value
    except (OSError, RuntimeError, ValueError):
        return raw
    return value


def _managed_effect_audio_target(
    state: BridgeState,
    effect_name: str,
    raw_path: str,
) -> Path | None:
    root = state_project_root(state)
    try:
        reference = make_path_reference(
            str(raw_path or ""),
            root,
            legacy_project_prefixes=(("data", "effects"),),
            resource_prefixes=(("assets", "system", "sound"),),
            recover_legacy_absolute=False,
        )
        if reference is None or reference.get("scope") != "project":
            return None
        value = path_reference_value(reference)
        if not value:
            return None
        target = resolve_managed_project_path(value, root=root)
    except (OSError, PermissionError, ValueError):
        return None
    return target if resolved_path_is_within(target, _effect_dir(effect_name, state)) else None


def _effect_audio_path_in_use(state: BridgeState, raw_path: str) -> bool:
    root = state_project_root(state)
    try:
        reference = make_path_reference(
            str(raw_path or ""),
            root,
            legacy_project_prefixes=(("data", "effects"),),
            recover_legacy_absolute=False,
        )
        value = path_reference_value(reference)
        if reference is None or reference.get("scope") != "project" or not value:
            return False
        target = resolve_managed_project_path(value, root=root)
        if not resolved_path_is_within(target, _effect_root(state)):
            return False
    except (OSError, PermissionError, ValueError):
        return False

    for effect in state.config_manager.config.effect_list:
        for candidate_raw in effect.audio_list or []:
            try:
                candidate_reference = make_path_reference(
                    str(candidate_raw or ""),
                    root,
                    legacy_project_prefixes=(("data", "effects"),),
                    recover_legacy_absolute=False,
                )
                candidate_value = path_reference_value(candidate_reference)
                if (
                    candidate_reference is None
                    or candidate_reference.get("scope") != "project"
                    or not candidate_value
                ):
                    continue
                candidate = resolve_managed_project_path(candidate_value, root=root)
            except (OSError, PermissionError, ValueError):
                continue
            if candidate == target:
                return True
    return False


def _unlink_managed_effect_file(
    state: BridgeState,
    effect_name: str,
    raw_path: str,
    *,
    expected_identity: os.stat_result | None = None,
) -> None:
    """Remove an audio file only when it is inside the effect's managed dir."""
    if not raw_path:
        return
    try:
        target = _managed_effect_audio_target(state, effect_name, raw_path)
    except (OSError, ValueError, FileNotFoundError):
        return
    if target is None or not target.is_file():
        return
    current_identity = target.lstat()
    if (
        expected_identity is not None
        and not os.path.samestat(expected_identity, current_identity)
    ):
        return
    try:
        remove_file_without_links(
            target,
            expected_identity=current_identity,
        )
    except (OSError, ValueError):
        pass


def _managed_effect_file_snapshot(
    state: BridgeState,
    effect_name: str,
    raw_path: str,
) -> tuple[Path, os.stat_result] | None:
    if not raw_path:
        return None
    try:
        target = _managed_effect_audio_target(state, effect_name, raw_path)
        if target is None:
            return None
        identity = target.lstat()
    except (OSError, ValueError, FileNotFoundError):
        return None
    return (target, identity) if target.is_file() else None


def _effect_by_name(state: BridgeState, name: str) -> Any:
    effect = state.config_manager.get_effect_by_name(name)
    if effect is None:
        raise KeyError(f"effect not found: {name}")
    return effect


def _effect_json_after_reload(state: BridgeState, name: str) -> dict[str, Any]:
    state.config_manager.reload()
    return _jsonify(_effect_by_name(state, name))


def _save_effect(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    with _EFFECT_MUTATION_LOCK:
        return _save_effect_unlocked(state, payload)


def _save_effect_unlocked(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    body = payload.get("effect", payload)
    if not isinstance(body, dict):
        raise ValueError("effect payload must be an object")
    name = str(body.get("name") or "")
    original_name = str(payload.get("originalName") or "")
    _validate_effect_storage_name(name)
    if original_name:
        _validate_effect_storage_name(original_name)

    if not name:
        raise ValueError("特效方案名称不能为空。")

    effect_list = state.config_manager.config.effect_list
    original_effects = list(effect_list)
    from config.schema import Effect as EffectModel

    renamed_directory: tuple[Path, Path, os.stat_result] | None = None
    created_directory: tuple[Path, os.stat_result] | None = None
    saved_name = name
    try:
        if original_name:
            original = state.config_manager.get_effect_by_name(original_name)
            if original is None:
                raise KeyError(f"effect not found: {original_name}")
            retained = [e for e in effect_list if e is not original]
            original_key = portable_name_key(original.name)
            if portable_name_key(name) == original_key and name != original.name:
                # A case/normalization-only rename is not portable: it is the
                # same directory on Windows/macOS but a different one on Linux.
                name = original.name
                body["name"] = name

            existing_names = {portable_name_key(e.name) for e in retained}
            base_name = name
            counter = 1
            while portable_name_key(name) in existing_names or (
                portable_name_key(name) != original_key
                and _effect_dir(name, state).exists()
            ):
                name = safe_path_component_with_suffix(
                    base_name,
                    f"_{counter}",
                    field="effect name",
                )
                counter += 1
            if name != base_name:
                body["name"] = name
                print(f"[Effect] 重命名冲突，自动更名为: {name}")

            old_dir = _effect_dir(original.name, state)
            new_dir = _effect_dir(name, state)
            if old_dir.is_dir() and old_dir != new_dir:
                if new_dir.exists() or path_is_link_or_reparse_point(new_dir):
                    raise FileExistsError(f"effect storage already exists: {name}")
                if "audio_list" in body and isinstance(body["audio_list"], list):
                    updated_audio_list: list[Any] = []
                    for raw_audio in body["audio_list"]:
                        target = _managed_effect_audio_target(
                            state,
                            original.name,
                            str(raw_audio or ""),
                        )
                        if target is None:
                            updated_audio_list.append(raw_audio)
                            continue
                        try:
                            relative_audio = target.relative_to(old_dir)
                        except ValueError:
                            updated_audio_list.append(raw_audio)
                            continue
                        updated_audio_list.append(
                            project_relative_path(
                                new_dir / relative_audio,
                                state_project_root(state),
                            )
                            or str(raw_audio or "")
                        )
                    body["audio_list"] = updated_audio_list

            updated = EffectModel.model_validate(body)
            if old_dir.is_dir() and old_dir != new_dir:
                new_dir.parent.mkdir(parents=True, exist_ok=True)
                old_dir_identity = old_dir.lstat()
                replace_directory_transactionally(
                    old_dir,
                    new_dir,
                    overwrite=False,
                    expected_staging_identity=old_dir_identity,
                    expected_destination_identity=None,
                )
                renamed_directory = (new_dir, old_dir, old_dir_identity)
            elif not new_dir.exists():
                new_dir.mkdir(parents=True)
                created_path = require_directory_without_links(
                    new_dir,
                    field="effect storage directory",
                )
                created_directory = (created_path, created_path.lstat())
            effect_list[:] = [*retained, updated]
            saved_name = updated.name
        else:
            existing = state.config_manager.get_effect_by_name(name)
            updated = EffectModel.model_validate(body)
            target_dir = _effect_dir(name, state)
            if existing is None and target_dir.exists():
                raise FileExistsError(f"effect storage already exists: {name}")
            if not target_dir.exists():
                target_dir.mkdir(parents=True)
                created_path = require_directory_without_links(
                    target_dir,
                    field="effect storage directory",
                )
                created_directory = (created_path, created_path.lstat())
            if existing is None:
                effect_list.append(updated)
            else:
                effect_list[:] = [
                    updated if effect is existing else effect
                    for effect in effect_list
                ]
            saved_name = updated.name

        state.config_manager.save_effect_config()
    except BaseException:
        effect_list[:] = original_effects
        if renamed_directory is not None:
            new_dir, old_dir, renamed_identity = renamed_directory
            try:
                if new_dir.exists() and not old_dir.exists():
                    replace_directory_transactionally(
                        new_dir,
                        old_dir,
                        overwrite=False,
                        expected_staging_identity=renamed_identity,
                        expected_destination_identity=None,
                    )
            except OSError as rollback_error:
                raise RuntimeError("effect directory rollback failed") from rollback_error
        if created_directory is not None:
            created_path, created_identity = created_directory
            try:
                remove_empty_directory_without_links(
                    created_path,
                    expected_identity=created_identity,
                )
            except (OSError, ValueError):
                pass
        raise

    state.config_manager.reload()
    return _jsonify(_effect_by_name(state, saved_name))


@_serialized_effect_mutation
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
    try:
        ef_dir = _effect_dir(match.name, state)
        ef_dir_identity = ef_dir.lstat() if ef_dir.is_dir() else None
    except (OSError, PermissionError, ValueError):
        ef_dir = None
        ef_dir_identity = None
    original_index = effect_list.index(match)
    effect_list.remove(match)
    try:
        state.config_manager.save_effect_config()
    except BaseException:
        effect_list.insert(original_index, match)
        raise
    # Clean up managed audio directory
    storage_key = portable_name_key(match.name)
    storage_in_use = any(
        portable_name_key(effect.name) == storage_key
        for effect in effect_list
    )
    if (
        not storage_in_use
        and ef_dir is not None
        and ef_dir_identity is not None
    ):
        try:
            remove_directory_without_links(
                ef_dir,
                expected_identity=ef_dir_identity,
            )
        except OSError:
            pass
    return {}


@_serialized_effect_mutation
def _upload_effect_audio(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "")
    paths = list(payload.get("paths") or [])
    _validate_effect_storage_name(name)
    if not name:
        raise ValueError("特效方案名称不能为空。")
    effect = _effect_by_name(state, name)

    ef_dir = _effect_dir(name, state)
    directory_was_missing = not ef_dir.exists()
    created_directory_identity: os.stat_result | None = None
    snapshot = effect.model_copy(deep=True)
    created_files: list[tuple[Path, os.stat_result]] = []
    try:
        audio_list = list(effect.audio_list or [])
        tags = str(payload.get("audioTags") or effect.audio_tags or "")

        for file_path in paths:
            try:
                src = safe_existing_file_path(
                    resolve_runtime_asset_read_path(
                        str(file_path),
                        root=state_project_root(state),
                    ),
                    field="effect audio path",
                )
            except (OSError, ValueError, FileNotFoundError):
                continue
            filename = safe_path_component(src.name, field="effect audio filename")
            dest, dest_identity = copy_file_exclusive_with_identity(
                src,
                ef_dir,
                filename,
                field="effect audio filename",
            )
            created_files.append((dest, dest_identity))
            if (
                directory_was_missing
                and created_directory_identity is None
            ):
                created_directory_identity = ef_dir.lstat()
            dest_str = project_relative_path(dest, state_project_root(state)) or dest.as_posix()
            audio_list.append(dest_str)
            tags += f"特效 {len(audio_list)}：\n"

        effect.audio_list = audio_list
        effect.audio_tags = tags
        state.config_manager.save_effect_config()
    except BaseException:
        _restore_model(effect, snapshot)
        _unlink_created_files(created_files)
        if directory_was_missing and created_directory_identity is not None:
            try:
                remove_empty_directory_without_links(
                    ef_dir,
                    expected_identity=created_directory_identity,
                )
            except (OSError, ValueError):
                pass
        raise
    return _effect_json_after_reload(state, name)


@_serialized_effect_mutation
def _delete_effect_audio(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "")
    _validate_effect_storage_name(name)
    index = int(payload.get("index") or 0)
    effect = _effect_by_name(state, name)

    audio_list = list(effect.audio_list or [])
    if index < 0 or index >= len(audio_list):
        raise IndexError(f"audio index out of range: {index}")

    removed_path = audio_list.pop(index)
    removed_snapshot = _managed_effect_file_snapshot(
        state,
        name,
        str(removed_path),
    )
    snapshot = effect.model_copy(deep=True)

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
    try:
        state.config_manager.save_effect_config()
    except BaseException:
        _restore_model(effect, snapshot)
        raise
    if (
        removed_snapshot is not None
        and not _effect_audio_path_in_use(state, removed_path)
    ):
        _unlink_managed_effect_file(
            state,
            name,
            removed_path,
            expected_identity=removed_snapshot[1],
        )
    return _effect_json_after_reload(state, name)


@_serialized_effect_mutation
def _delete_all_effect_audio(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "")
    _validate_effect_storage_name(name)
    effect = _effect_by_name(state, name)

    removed_paths = list(effect.audio_list or [])
    removed_snapshots = {
        raw_path: file_snapshot
        for raw_path in removed_paths
        if (
            file_snapshot := _managed_effect_file_snapshot(
                state,
                name,
                str(raw_path),
            )
        ) is not None
    }
    snapshot = effect.model_copy(deep=True)
    try:
        effect.audio_list = []
        effect.audio_tags = ""
        state.config_manager.save_effect_config()
    except BaseException:
        _restore_model(effect, snapshot)
        raise
    for path in removed_paths:
        removed_snapshot = removed_snapshots.get(path)
        if (
            removed_snapshot is not None
            and not _effect_audio_path_in_use(state, path)
        ):
            _unlink_managed_effect_file(
                state,
                name,
                path,
                expected_identity=removed_snapshot[1],
            )
    return _effect_json_after_reload(state, name)


@_serialized_effect_mutation
def _save_effect_audio_tags(state: BridgeState, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "")
    _validate_effect_storage_name(name)
    effect = _effect_by_name(state, name)
    new_tags = str(payload.get("audioTags") or "")
    snapshot = effect.model_copy(deep=True)
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
    try:
        state.config_manager.save_effect_config()
    except BaseException:
        _restore_model(effect, snapshot)
        raise
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

    paths_changed = False
    changed_effects: list[tuple[Any, Any]] = []
    for ef_name in effect_names:
        ef = state.config_manager.get_effect_by_name(ef_name)
        if ef is None:
            continue
        tags = (ef.audio_tags or "").splitlines()
        audio_list = [
            _canonical_effect_audio_value(state, ef_name, str(path or ""))
            for path in (ef.audio_list or [])
        ]
        if audio_list != list(ef.audio_list or []):
            changed_effects.append((ef, ef.model_copy(deep=True)))
            ef.audio_list = audio_list
            paths_changed = True
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

    if paths_changed:
        try:
            state.config_manager.save_effect_config()
        except BaseException:
            for effect, snapshot in changed_effects:
                _restore_model(effect, snapshot)
            raise

    lines.append("")
    lines.append("注意：仅在适当时机使用特效，过度使用会破坏沉浸感。effect 字段为可选，无需求时省略。")
    return "\n".join(lines)
