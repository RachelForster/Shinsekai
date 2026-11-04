"""Validated task/persistence boundary for generated sprite mouth bundles."""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import shutil
from uuid import uuid4

from application.characters.mouth_sync import build_bundle, copy_mouth_assets, transfer_bundle
from application.characters import mouth_resources
from application.runtime.state import _jsonify
from application.runtime.tasks import _update_task
from config.sprite_files import sprite_field, sprite_fingerprint
from config.sprite_mouth import correction, read_manifest, suggested_mouth_box, valid_mouth_sync
from frontend_bridge_core.tools import _local_file_access_roots
from sdk.path_utils import safe_child_path, safe_existing_file_path


def _source(state, payload):
    name = str(payload.get("name") or "").strip()
    character = state.config_manager.get_character_by_name(name)
    if character is None:
        raise ValueError("请先保存角色再制作口型")
    path = str(payload.get("spritePath") or "")
    matches = [(i, sprite) for i, sprite in enumerate(character.sprites) if str(sprite_field(sprite, "path", "")) == path]
    if len(matches) != 1:
        raise ValueError("来源立绘已变化或不属于当前角色，请重新选择")
    index, sprite = matches[0]
    source = safe_existing_file_path(path, roots=_local_file_access_roots(state), field="spritePath")
    return character, index, sprite, source


def _bundle_manifest(state, path):
    root = Path(state.project_root_dir).resolve()
    candidate = Path(str(path))
    if not candidate.is_absolute():
        candidate = root / candidate
    path = safe_existing_file_path(candidate, roots=(root / "cache/sprite_generation", root / "data/sprite"), field="mouth manifest")
    if path.name != "manifest.json":
        raise ValueError("无效的口型配置文件")
    return path


def _public_path(state, path):
    # The media endpoint accepts project-relative resources; absolute external
    # files require a separate, explicit runtime approval.
    return Path(path).resolve().relative_to(Path(state.project_root_dir).resolve()).as_posix()


def read_profile(state, path):
    return read_manifest(_bundle_manifest(state, path))


def discard_mouth_bundle(state, manifest):
    root = Path(state.project_root_dir) / "data/sprite"
    directory = Path(manifest).parent.resolve()
    if directory.is_dir() and directory != root.resolve() and directory.is_relative_to(root.resolve()):
        shutil.rmtree(directory)


def install_mouth_bundle(state, character, manifest, data=None):
    manifest = _bundle_manifest(state, manifest)
    if data is None:
        data = read_manifest(manifest)
    root = Path(state.project_root_dir) / "data/sprite"
    directory = safe_child_path(root, f"{character.sprite_prefix}/mouth-sync/{uuid4().hex}")
    directory.mkdir(parents=True, exist_ok=False)
    try:
        copy_mouth_assets(manifest.parent, directory)
        destination = directory / "manifest.json"
        destination.write_text(json.dumps(data), encoding="utf-8")
        read_manifest(destination)
        return destination
    except Exception:
        discard_mouth_bundle(state, directory / "manifest.json")
        raise


def inherit_mouth_bundle(state, name, reference, video, output, progress):
    _, _, sprite, source = _source(state, {"name": name, "spritePath": reference["path"]})
    path = sprite_field(sprite, "mouth_sync")
    if not path:
        return None
    manifest = _bundle_manifest(state, path)
    fingerprint = sprite_fingerprint(source)
    if read_manifest(manifest)["sourceFingerprint"] != fingerprint or reference["fingerprint"] != fingerprint:
        raise ValueError("参考立绘已变化，请重新生成动态立绘后再匹配口型")
    root = Path(state.project_root_dir)
    frame = safe_existing_file_path(reference["frame"], roots=(root / "cache/sprite_generation",), field="mouth reference")
    progress("正在复用参考立绘的嘴型并计算跟随轨迹")
    return transfer_bundle(root, state.config_manager, video, frame, manifest, output, sprite_fingerprint(video), progress)


def describe_bundle(state, path):
    path = _bundle_manifest(state, path)
    data = read_manifest(path)
    directory = path.parent
    profile = {**data, "mouths": {pose: _public_path(state, safe_child_path(directory, relative)) for pose, relative in data["mouths"].items()}}
    frames = []
    timing_file = safe_child_path(directory, "frames.json")
    try:
        timing = json.loads(timing_file.read_text(encoding="utf-8")) if timing_file.is_file() and timing_file.stat().st_size < 100_000 else {}
    except (ValueError, OSError):
        timing = {}
    fps = timing.get("fps", 24) if isinstance(timing, dict) else 24
    if isinstance(fps, bool) or not isinstance(fps, (int, float)) or not math.isfinite(fps) or not 1 <= fps <= 60:
        fps = 24
    times = {}
    samples = timing.get("frames", []) if isinstance(timing, dict) else []
    for sample in samples if isinstance(samples, list) else []:
        if isinstance(sample, dict) and isinstance(sample.get("index"), int):
            timestamp = sample.get("time")
            if isinstance(timestamp, (int, float)) and math.isfinite(timestamp) and 0 <= timestamp <= 12:
                times[sample["index"]] = timestamp
    frame_dir = safe_child_path(directory, "frames")
    if frame_dir.is_dir():
        for frame in sorted(frame_dir.iterdir()):
            if re.fullmatch(r"\d{3}\.jpg", frame.name) and frame.is_file():
                index = int(frame.stem)
                frames.append({"index": index, "time": times.get(index, index / fps), "path": _public_path(state, safe_child_path(frame_dir, frame.name))})
    prepared = safe_child_path(directory, "prepared.json")
    suggested = None
    if prepared.is_file() and prepared.stat().st_size < 100_000:
        metadata = json.loads(prepared.read_text(encoding="utf-8"))
        suggested = metadata.get("suggestedManual")
        if isinstance(suggested, dict) and not data.get("manual") and "keypoints" in metadata:
            try:
                suggested = {
                    **suggested,
                    "mouthBox": suggested_mouth_box(metadata["keypoints"], data["width"], data["height"]),
                }
            except (TypeError, ValueError, IndexError, KeyError):
                pass
    return {
        "ready": True, "manifestPath": _public_path(state, path), "profile": profile,
        "reference": _public_path(state, safe_child_path(directory, "reference.png")),
        "speechVideo": _public_path(state, safe_child_path(directory, "speech.mp4")),
        "frames": frames, "speechFps": fps, "suggestedManual": suggested,
        "selectedFrames": data.get("selectedFrames"), "manual": data.get("manual"),
    }


def _previous(state, task_id, name, source, fingerprint):
    with state.task_lock:
        task = state.tasks.get(task_id)
        if not task or task.get("kind") != "character-sprite-mouth" or task.get("status") != "succeeded":
            raise ValueError("口型结果不可用，请重新制作")
        result = dict(task.get("result") or {})
    if result.get("name") != name or result.get("spritePath") != source or result.get("sourceFingerprint") != fingerprint:
        raise ValueError("来源立绘已变化，请重新制作口型")
    return result


def run_sprite_mouth(state, task_id, payload):
    character, _, sprite, source = _source(state, payload)
    name = character.name
    original = str(sprite_field(sprite, "path"))
    fingerprint = sprite_fingerprint(source)
    identity = {"name": name, "spritePath": original, "sourceFingerprint": fingerprint, "taskId": task_id}
    if not isinstance(payload.get("regenerate", False), bool):
        raise ValueError("regenerate 必须为布尔值")
    previous = None
    if payload.get("retryTaskId"):
        previous = _previous(state, str(payload["retryTaskId"]), name, original, fingerprint)
        # Applying frame choices can omit placement or playback corrections.
        # A null placement is an explicit request to return to automatic alignment.
        payload = {
            "manual": previous.get("manual"),
            "selectedFrames": previous.get("selectedFrames"),
            "correction": previous.get("correction") or (previous.get("profile") or {}).get("correction"),
            **payload,
        }
    elif not payload.get("regenerate", False):
        saved = valid_mouth_sync(sprite)
        if saved:
            return {**identity, **describe_bundle(state, saved), "cached": True}
    setup = mouth_resources.status(state.project_root_dir, state.config_manager)
    if not setup["runtimeReady"] or not setup["modelsReady"]:
        raise ValueError("请先准备口型识别环境和模型")
    speech = payload.get("speechVideo")
    if speech:
        speech = safe_existing_file_path(str(speech), roots=_local_file_access_roots(state), field="speechVideo")
        if speech.suffix.lower() not in {".mp4", ".webm", ".mov", ".mkv"}:
            raise ValueError("请选择 MP4 或 WebM 说话视频")
    root = Path(state.project_root_dir)
    output = safe_child_path(root / "cache/sprite_generation", f"{task_id}-mouth")
    previous_dir = None
    if previous:
        candidate = previous.get("manifestPath") or str(Path(previous.get("reference", "")).parent / "manifest.json")
        candidate = Path(candidate)
        directory = (candidate if candidate.is_absolute() else root / candidate).parent
        # A retry can use a cached failed analysis, but never arbitrary API paths.
        retry_reference = directory / "input.png"
        if not retry_reference.is_file():
            retry_reference = directory / "reference.png"
        allowed = safe_existing_file_path(str(retry_reference), roots=(root / "cache/sprite_generation", root / "data/sprite"), field="mouth retry")
        previous_dir = allowed.parent
    def progress(message):
        _update_task(state, task_id, phase="mouth-sync", progress=.3, message=message)
    result = build_bundle(
        root, state.config_manager, source, source, output, fingerprint,
        {**payload, "name": name, "speechVideo": str(speech) if speech else None}, progress,
        previous=previous_dir,
    )
    if sprite_fingerprint(source) != fingerprint:
        raise ValueError("制作期间来源立绘已变化，请重新制作")
    if result.get("ready"):
        result.update(describe_bundle(state, result["manifest"]))
    result.pop("directory", None)
    result.pop("manifest", None)
    if not result.get("ready"):
        for key in ("reference", "speechVideo"):
            if result.get(key):
                result[key] = _public_path(state, result[key])
        for frame in result.get("frames", []):
            frame["path"] = _public_path(state, frame["path"])
    _update_task(state, task_id, phase="complete", progress=1, message="口型已就绪" if result.get("ready") else "需要手动校准口型")
    return {**identity, **result}


def save_sprite_mouths(state, payload):
    name = str(payload.get("name") or "").strip()
    items = payload.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= 12:
        raise ValueError("请选择 1–12 份口型结果")
    results, seen = [], set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("口型结果格式无效")
        task_id = str(item.get("taskId") or "")
        with state.task_lock:
            task = state.tasks.get(task_id) or {}
            result = dict(task.get("result") or {})
        character, index, _, source = _source(state, {"name": name, "spritePath": result.get("spritePath")})
        result = _previous(state, task_id, name, result.get("spritePath"), sprite_fingerprint(source))
        if not result.get("ready"):
            raise ValueError("请先完成口型识别或人工校准")
        if index in seen:
            raise ValueError("同一张立绘不能同时保存多份口型")
        seen.add(index)
        manifest = _bundle_manifest(state, result["manifestPath"])
        data = read_manifest(manifest)
        data["correction"] = correction(item.get("correction", data.get("correction")))
        results.append((index, result["spritePath"], character, manifest, data))
    installed = []
    try:
        for index, source, character, manifest, data in results:
            destination = install_mouth_bundle(state, character, manifest, data)
            installed.append((index, source, str(destination)))
        state.character_manager.save_sprite_mouths(name, installed)
    except Exception:
        for _, _, destination in installed:
            discard_mouth_bundle(state, destination)
        raise
    state.config_manager.reload()
    return _jsonify(state.config_manager.get_character_by_name(name))


def run_mouth_setup(state, task_id, payload, action):
    root = state.project_root_dir
    def progress(message, value):
        _update_task(state, task_id, phase="mouth-setup", progress=value, message=message)
    if action == "download":
        mouth_resources.download_models(root, progress)
    elif action == "install":
        mouth_resources.install_runtime(root, state.config_manager, progress)
    return mouth_resources.status(root, state.config_manager)


def configure_mouth_setup(state, payload):
    mouth_resources.configure(state.project_root_dir, payload)
    return mouth_resources.status(state.project_root_dir, state.config_manager)


def import_mouth_models(state, payload):
    paths = payload.get("paths")
    if not isinstance(paths, list) or len(paths) != 2:
        raise ValueError("请选择两份模型文件")
    checked = [str(safe_existing_file_path(str(path), roots=_local_file_access_roots(state), field="model")) for path in paths]
    mouth_resources.import_models(state.project_root_dir, checked)
    return mouth_resources.status(state.project_root_dir, state.config_manager)


def remove_sprite_mouth(state, payload):
    character, index, _, _ = _source(state, payload)
    state.character_manager.save_sprite_mouths(character.name, [(index, payload["spritePath"], None)])
    state.config_manager.reload()
    return _jsonify(state.config_manager.get_character_by_name(character.name))
