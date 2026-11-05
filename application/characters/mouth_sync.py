"""Generate and analyze one reusable mouth bundle for an exact sprite asset."""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time

from application.characters.generate_sprites import boundary_frame, render_sprite
from application.characters import mouth_resources
from core.media.sprite_mouth.manifest import correction, read_manifest
from sdk.path_utils import safe_child_path

_RECOGNITION_LOCK = threading.Lock()
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
