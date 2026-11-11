"""Generate, validate, and persist reusable mouth bundles for sprite assets."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
from threading import Lock
import time
from typing import Any, Iterable
from uuid import uuid4

from application.characters.sprite import mouth_resources
from application.characters.sprite.generate_sprites import boundary_frame, render_sprite
from application.characters.sprite.mouth_resources import (
    configure_mouth_setup,
    import_mouth_models,
    run_mouth_setup,
)
from application.media.resource_paths import MediaResourcePaths
from application.runtime.state import _jsonify
from application.runtime.tasks import _update_task
from config.sprite_files import sprite_field, sprite_fingerprint
from core.sprite.mouth.manifest import (
    correction,
    read_manifest,
    suggested_mouth_box,
    valid_mouth_sync,
)
from sdk.path_utils import safe_child_path, safe_existing_file_path

_RECOGNITION_LOCK = threading.Lock()
_save_lock = Lock()
MOUTH_FRAME_COUNTS = (5, 22, 39)
DEFAULT_MOUTH_FRAME_COUNT = 22
MOUTH_PROMPT = (
    "A quiet, natural conversational lip movement for this 2D character, as if "
    "softly saying one short word. Only the lips and the inside of the mouth move. "
    "Start with the original resting mouth, gently part the lips a little, briefly "
    "form a modest opening for a soft vowel, then ease back to the original resting "
    "mouth. Three distinct, subtle stages: resting, slightly parted, and gently open. "
    "Keep the mouth near its original position and width. Leave visible skin between "
    "the upper lip and the base of the nose, and between the lower lip and the chin "
    "in every frame. Preserve the eyes, eyebrows, gaze, nose, cheeks, jawline, chin, "
    "head angle, ears, hair, neck and clothing from the reference. Same character "
    "design, lighting and crop, locked camera, plain white background."
)
MOUTH_BLINK_PROMPT = (
    "A short, fixed-camera animation of this exact 2D portrait. In the first half, "
    "with both eyes held at the original openness and gaze, softly say one short "
    "syllable. Show the original resting mouth, a slightly parted mouth and a modest "
    "vowel opening, then return to the resting mouth. Keep the mouth resting during "
    "one natural blink in the second half: eyes open, eyelids half lowered, eyelids "
    "fully closed briefly, then smoothly reopen to the original gaze and eye shape. "
    "Blink only if both eyes are open and visible in the reference. Only the lips and "
    "eyelids move. Preserve the eyebrows, nose, cheeks, chin, jawline, head angle, "
    "ears, hair, neck, clothing and proportions. Keep visible skin between the lips "
    "and the nose and chin. Match the exact original framing and lighting, plain "
    "white background. End at the original expression."
)


def _local_file_access_roots(state: Any) -> tuple[Path, ...]:
    project_root = Path(getattr(state, "project_root_dir", "") or Path.cwd())
    return MediaResourcePaths(project_root).file_access_roots


def _resolve_file_access_roots(
    state: Any, file_access_roots: Iterable[Path] = ()
) -> tuple[Path, ...]:
    roots = tuple(file_access_roots)
    if not roots:
        return _local_file_access_roots(state)
    project_root = Path(getattr(state, "project_root_dir", "") or Path.cwd())
    return MediaResourcePaths(
        project_root, file_access_roots=roots
    ).file_access_roots


def mouth_frame_count(payload):
    value = payload.get("frameCount", DEFAULT_MOUTH_FRAME_COUNT)
    if isinstance(value, bool) or not isinstance(value, int) or value not in MOUTH_FRAME_COUNTS:
        raise ValueError("说话视频帧数请选择 5、22 或 39")
    return value


def validate_manual(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {"mouthBox", "chin"}:
        raise ValueError("手动定位参数无效")
    result = {}
    for key, length in (("mouthBox", 4), ("chin", 2)):
        if key not in value:
            continue
        points = value[key]
        if not isinstance(points, list) or len(points) != length:
            raise ValueError("请在预览中标定嘴部与下巴")
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or not 0 <= x <= 1 for x in points):
            raise ValueError("手动定位坐标必须在画面范围内")
        result[key] = points
    if "mouthBox" in result:
        x0, y0, x1, y1 = result["mouthBox"]
        if x1 - x0 < .001 or y1 - y0 < .001:
            raise ValueError("嘴部范围不能为空")
    if bool(result.get("mouthBox")) != bool(result.get("chin")):
        raise ValueError("请同时标定嘴部范围与下巴")
    return result or None


def invoke_worker(root, config_store, request, progress):
    locations = mouth_resources.locations(root)
    request = {**request, "models": str(locations["models"]), "device": mouth_resources.settings(root)["device"]}
    request_path = Path(request["output"]) / f"{request['action']}-request.json"
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text(json.dumps(request), encoding="utf-8")
    command = mouth_resources.worker_command(root, config_store, request_path)
    # Do not retain recognition VRAM while the separately managed H3 model runs.
    with _RECOGNITION_LOCK, tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errors:
        process = subprocess.Popen(
            command, cwd=root, stdout=subprocess.PIPE, stderr=errors,
            text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        result, error = None, ""
        deadline = time.monotonic() + 600
        timer = threading.Timer(600, process.kill)
        timer.start()
        try:
            for line in process.stdout:
                if time.monotonic() > deadline:
                    raise TimeoutError("口型处理超时，请检查识别环境")
                if not line.startswith("MOUTH_EVENT:"):
                    continue
                event = json.loads(line.removeprefix("MOUTH_EVENT:"))
                if event.get("type") == "progress":
                    progress(event.get("message", "正在处理口型"))
                elif event.get("type") == "result":
                    result = event["result"]
                elif event.get("type") == "error":
                    error = str(event.get("message", ""))
            code = process.wait(timeout=15)
            if code or result is None:
                errors.seek(0)
                raise ValueError(error or errors.read()[-2000:] or "识别环境没有返回口型结果")
            return result
        finally:
            timer.cancel()
            if process.poll() is None:
                process.kill()
            process.wait()


def build_bundle(root, config_store, source, reference, output, fingerprint, payload, progress, *, previous=None):
    frame_count = mouth_frame_count(payload)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    manual = validate_manual(payload.get("manual"))
    adjustments = correction(payload.get("correction"))
    if previous:
        for item in Path(previous).iterdir():
            if item.is_file() and item.name in {"speech.mp4", "reference.png", "face-reference.png", "prepared.json", "frames.json"}:
                shutil.copyfile(item, output / item.name)
    speech = output / "speech.mp4"
    supplied = payload.get("speechVideo")
    if supplied and not speech.is_file():
        shutil.copyfile(supplied, speech)
    prepared = output / "prepared.json"
    old = json.loads(prepared.read_text(encoding="utf-8")) if prepared.is_file() else {}
    speech_crop = old.get("speechCrop", old.get("crop")) if speech.is_file() else None
    tracking_keypoints = old.get("trackingKeypoints", old.get("keypoints")) if manual else None
    input_reference = boundary_frame(reference, output / "input.png", last=False)
    try:
        preparation = invoke_worker(root, config_store, {
            "action": "prepare", "reference": str(input_reference), "output": str(output), "manual": manual,
            "speechCrop": speech_crop, "trackingKeypoints": tracking_keypoints,
            "speechTransform": old.get("speechTransform") if speech_crop else None,
        }, progress)
    except ValueError as error:
        assets = {}
        if speech.is_file():
            try:
                assets = invoke_worker(root, config_store, {"action": "inspect", "output": str(output)}, progress)
            except ValueError:
                assets = {"speechVideo": "speech.mp4"}
        for key in ("speechVideo",):
            if assets.get(key):
                assets[key] = str(output / assets[key])
        for frame in assets.get("frames", []):
            frame["path"] = str(output / frame["path"])
        return {"ready": False, "calibrationNeeded": True, "message": str(error), "reference": str(input_reference), "directory": str(output), "manual": manual, "selectedFrames": payload.get("selectedFrames"), "correction": adjustments, **assets}
    if not speech.is_file():
        include_blink = payload.get("includeBlink", False)
        if include_blink and frame_count == 5:
            raise ValueError("同时生成说话和眨眼请选择 22 帧或 39 帧")
        progress(f"正在生成 {frame_count} 帧说话视频")
        generated = render_sprite(
            config_store,
            {"name": payload["name"], "prompt": MOUTH_BLINK_PROMPT if include_blink else MOUTH_PROMPT, "tagging": "口型素材"},
            output / "generated.png", output / "face-reference.png",
            require_h3_video=True, loop_reference=True, h3_frame_count=frame_count,
        )
        shutil.copyfile(generated["videoPath"], speech)
    request = {
        "action": "analyze", "output": str(output), "sourceFingerprint": fingerprint,
        "sourceVideo": str(source) if Path(source).suffix.lower() in {".webm", ".mp4", ".mov", ".mkv", ".avi", ".m4v"} else None,
        "selectedFrames": payload.get("selectedFrames"), "manual": manual, "correction": adjustments,
    }
    result = invoke_worker(root, config_store, request, progress)
    result["directory"] = str(output)
    result["suggestedManual"] = preparation["suggestedManual"]
    for key in ("reference", "speechVideo", "manifest"):
        if result.get(key):
            result[key] = str(output / result[key])
    for frame in result.get("frames", []):
        frame["path"] = str(output / frame["path"])
    if result.get("ready"):
        read_manifest(result["manifest"])
    return result


def copy_mouth_assets(source, destination, *, speech_only=False):
    filenames = ("speech.mp4", "frames.json")
    if not speech_only:
        filenames += ("mouth-closed.png", "mouth-half.png", "mouth-open.png", "reference.png", "face-reference.png", "prepared.json")
    for filename in filenames:
        path = safe_child_path(source, filename)
        if path.is_file():
            shutil.copyfile(path, destination / filename)
    frames = safe_child_path(source, "frames")
    if frames.is_dir():
        (destination / "frames").mkdir(exist_ok=True)
        for file in frames.iterdir():
            if re.fullmatch(r"\d{3}\.jpg", file.name) and file.is_file():
                shutil.copyfile(safe_child_path(frames, file.name), destination / "frames" / file.name)


def transfer_bundle(root, config_store, video, reference, profile, output, fingerprint, progress):
    prepared = safe_child_path(profile.parent, "prepared.json")
    geometry = json.loads(prepared.read_text(encoding="utf-8")) if prepared.is_file() and prepared.stat().st_size < 100_000 else {}
    result = invoke_worker(root, config_store, {
        "action": "transfer", "output": str(output), "sourceVideo": str(video),
        "profile": str(profile), "reference": str(reference), "sourceFingerprint": fingerprint,
        "speechGeometry": geometry,
    }, progress)
    manifest = safe_child_path(output, result["manifest"])
    read_manifest(manifest)
    copy_mouth_assets(profile.parent, output, speech_only=True)
    return manifest


def _source(state, payload, *, file_access_roots: Iterable[Path] = ()):
    name = str(payload.get("name") or "").strip()
    character = state.config_manager.get_character_by_name(name)
    if character is None:
        raise ValueError("请先保存角色再制作口型")
    path = str(payload.get("spritePath") or "")
    matches = [(i, sprite) for i, sprite in enumerate(character.sprites) if str(sprite_field(sprite, "path", "")) == path]
    if len(matches) != 1:
        raise ValueError("来源立绘已变化或不属于当前角色，请重新选择")
    index, sprite = matches[0]
    source = safe_existing_file_path(
        path,
        roots=_resolve_file_access_roots(state, file_access_roots),
        field="spritePath",
    )
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


def inherit_mouth_bundle(
    state,
    name,
    reference,
    video,
    output,
    progress,
    *,
    file_access_roots: Iterable[Path] = (),
):
    _, _, sprite, source = _source(
        state,
        {"name": name, "spritePath": reference["path"]},
        file_access_roots=file_access_roots,
    )
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
        **({"eyeFrames": data["eyeFrames"]} if "eyeFrames" in data else {}),
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


def run_sprite_mouth(
    state, task_id, payload, *, file_access_roots: Iterable[Path] = ()
):
    character, _, sprite, source = _source(
        state, payload, file_access_roots=file_access_roots
    )
    name = character.name
    original = str(sprite_field(sprite, "path"))
    fingerprint = sprite_fingerprint(source)
    identity = {"name": name, "spritePath": original, "sourceFingerprint": fingerprint, "taskId": task_id}
    if not isinstance(payload.get("regenerate", False), bool):
        raise ValueError("regenerate 必须为布尔值")
    include_blink = payload.get("includeBlink", False)
    if not isinstance(include_blink, bool):
        raise ValueError("includeBlink 必须为布尔值")
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
    elif not payload.get("regenerate", False) and not include_blink:
        saved = valid_mouth_sync(sprite)
        if saved:
            return {**identity, **describe_bundle(state, saved), "cached": True}
    setup = mouth_resources.status(state.project_root_dir, state.config_manager)
    if not setup["runtimeReady"] or not setup["modelsReady"]:
        raise ValueError("请先准备口型识别环境和模型")
    speech = payload.get("speechVideo")
    if speech:
        speech = safe_existing_file_path(
            str(speech),
            roots=_resolve_file_access_roots(state, file_access_roots),
            field="speechVideo",
        )
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


def _validate_eye_frames(manifest, eyes):
    if not isinstance(eyes, dict) or set(eyes) - {"open", "half", "closed"}:
        raise ValueError("无效的眼睛选帧")
    if any(
        type(index) is not int or not 0 <= index < 180
        or not safe_child_path(manifest.parent, f"frames/{index:03d}.jpg").is_file()
        for index in eyes.values()
    ):
        raise ValueError("眼睛选帧超出说话视频范围")
    if len(set(eyes.values())) != len(eyes):
        raise ValueError("不同的眼睛状态请选择不同帧")


def _same_speech(first, second):
    if first == second:
        return True
    a, b = (safe_child_path(manifest.parent, "speech.mp4") for manifest in (first, second))
    return a.is_file() and b.is_file() and sprite_fingerprint(a) == sprite_fingerprint(b)


def _saved_profile(state, sprite, fingerprint):
    try:
        path = _bundle_manifest(state, sprite_field(sprite, "mouth_sync"))
        data = read_manifest(path)
        if data["sourceFingerprint"] == fingerprint:
            return path, data
    except (OSError, ValueError):
        pass
    return None, None


def _save_eye_frames(manifest, data, eyes):
    _validate_eye_frames(manifest, eyes)
    if eyes:
        data["eyeFrames"] = eyes
    else:
        data.pop("eyeFrames", None)
    temporary = manifest.with_name(f".eyes-{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(data), encoding="utf-8")
        os.replace(temporary, manifest)
    finally:
        temporary.unlink(missing_ok=True)


def save_sprite_mouths(
    state, payload, *, file_access_roots: Iterable[Path] = ()
):
    with _save_lock:
        return _save_sprite_mouths(
            state, payload, file_access_roots=file_access_roots
        )


def _save_sprite_mouths(
    state, payload, *, file_access_roots: Iterable[Path] = ()
):
    name = str(payload.get("name") or "").strip()
    items = payload.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= 12:
        raise ValueError("请选择 1–12 份口型结果")
    eyes_only = payload.get("eyesOnly", False)
    if type(eyes_only) is not bool or (eyes_only and len(items) != 1):
        raise ValueError("请选择一份眨眼选帧")
    results, seen = [], set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("口型结果格式无效")
        task_id = str(item.get("taskId") or "")
        with state.task_lock:
            task = state.tasks.get(task_id) or {}
            result = dict(task.get("result") or {})
        character, index, sprite, source = _source(
            state,
            {"name": name, "spritePath": result.get("spritePath")},
            file_access_roots=file_access_roots,
        )
        result = _previous(state, task_id, name, result.get("spritePath"), sprite_fingerprint(source))
        if not result.get("ready"):
            raise ValueError("请先完成口型识别或人工校准")
        if index in seen:
            raise ValueError("同一张立绘不能同时保存多份口型")
        seen.add(index)
        manifest = _bundle_manifest(state, result["manifestPath"])
        current, current_data = _saved_profile(state, sprite, result["sourceFingerprint"])
        if eyes_only:
            if current is None or not _same_speech(manifest, current):
                raise ValueError("请先保存当前说话视频的口型，再保存眼睛选帧")
            _save_eye_frames(current, current_data, item.get("eyeFrames"))
            return _jsonify(character)
        data = read_manifest(manifest)
        data["correction"] = correction(item.get("correction", data.get("correction")))
        # A cached task can still point at a prior installation. Preserve the
        # latest eye choices only when they belong to this exact clip.
        data.pop("eyeFrames", None)
        if "eyeFrames" in item:
            eyes = item["eyeFrames"]
            _validate_eye_frames(manifest, eyes)
        else:
            eyes = current_data.get("eyeFrames") if current and _same_speech(manifest, current) else None
        if eyes:
            data["eyeFrames"] = eyes
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


def remove_sprite_mouth(
    state, payload, *, file_access_roots: Iterable[Path] = ()
):
    with _save_lock:
        character, index, _, _ = _source(
            state, payload, file_access_roots=file_access_roots
        )
        state.character_manager.save_sprite_mouths(character.name, [(index, payload["spritePath"], None)])
        state.config_manager.reload()
        return _jsonify(state.config_manager.get_character_by_name(character.name))


__all__ = [
    "DEFAULT_MOUTH_FRAME_COUNT",
    "MOUTH_BLINK_PROMPT",
    "MOUTH_FRAME_COUNTS",
    "MOUTH_PROMPT",
    "build_bundle",
    "configure_mouth_setup",
    "copy_mouth_assets",
    "describe_bundle",
    "discard_mouth_bundle",
    "import_mouth_models",
    "inherit_mouth_bundle",
    "install_mouth_bundle",
    "invoke_worker",
    "mouth_frame_count",
    "read_profile",
    "remove_sprite_mouth",
    "run_mouth_setup",
    "run_sprite_mouth",
    "save_sprite_mouths",
    "transfer_bundle",
    "validate_manual",
]
