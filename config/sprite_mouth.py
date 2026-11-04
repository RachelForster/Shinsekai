"""Validate portable mouth bundles without importing any inference dependencies."""
from __future__ import annotations

import json
import math
from pathlib import Path

from config.sprite_files import sprite_field, sprite_fingerprint
from sdk.path_utils import safe_child_path

POSES = ("closed", "half", "open")
MAX_FRAMES = 720
MAX_DURATION = 12.0
MAX_JSON_BYTES = 2_000_000


def _number(value, low, high, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"无效的口型参数：{field}")
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"口型参数超出范围：{field}")
    return value


def correction(value=None):
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("无效的口型纠正参数")
    return {
        "offsetX": _number(value.get("offsetX", 0), -4096, 4096, "offsetX"),
        "offsetY": _number(value.get("offsetY", 0), -4096, 4096, "offsetY"),
        "scale": _number(value.get("scale", 1), 0.25, 4, "scale"),
        "rotation": _number(value.get("rotation", 0), -90, 90, "rotation"),
        "gain": _number(value.get("gain", 1), 0.1, 5, "gain"),
    }


def suggested_mouth_box(keypoints, width, height):
    """Normalized guide with five source pixels around the detected lips."""
    lips = keypoints[24:28]
    if len(lips) != 4:
        raise ValueError("嘴部定位数据不完整")
    xs, ys = zip(*((float(point[0]), float(point[1])) for point in lips))
    if not all(math.isfinite(value) for value in (*xs, *ys)):
        raise ValueError("嘴部定位坐标无效")
    return [
        min(width, max(0, min(xs) - 5)) / width,
        min(height, max(0, min(ys) - 5)) / height,
        min(width, max(0, max(xs) + 5)) / width,
        min(height, max(0, max(ys) + 5)) / height,
    ]


def read_manifest(path, *, verify_assets=True):
    path = Path(path)
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("口型轨迹文件过大")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("不支持的口型数据版本")
    width = _number(data.get("width"), 1, 8192, "width")
    height = _number(data.get("height"), 1, 8192, "height")
    if int(width) != width or int(height) != height or width * height > 8_388_608:
        raise ValueError("口型画布尺寸无效")
    _number(data.get("duration", 0), 0, MAX_DURATION + 0.1, "duration")
    _number(data.get("fps", 0), 0, 60, "fps")
    box = data.get("patchBox")
    if not isinstance(box, list) or len(box) != 4:
        raise ValueError("口型裁剪框无效")
    for i, value in enumerate(box):
        _number(value, 0, width if i % 2 == 0 else height, "patchBox")
    if box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError("口型裁剪框不能为空")
    mouths = data.get("mouths")
    if not isinstance(mouths, dict) or set(mouths) != set(POSES):
        raise ValueError("口型素材必须包含闭合、半开和张开")
    for pose in POSES:
        if mouths[pose] != f"mouth-{pose}.png":
            raise ValueError("无效的口型素材路径")
        if verify_assets and not safe_child_path(path.parent, mouths[pose]).is_file():
            raise ValueError("口型素材已丢失，请重新制作")
    track = data.get("track")
    if not isinstance(track, list) or not 1 <= len(track) <= MAX_FRAMES:
        raise ValueError("口型轨迹帧数无效")
    last = -1.0
    for sample in track:
        if not isinstance(sample, dict):
            raise ValueError("无效的口型轨迹")
        timestamp = _number(sample.get("time"), 0, MAX_DURATION + 0.1, "time")
        if timestamp <= last:
            raise ValueError("口型轨迹时间必须递增")
        last = timestamp
        matrix = sample.get("matrix")
        if not isinstance(matrix, list) or len(matrix) != 6:
            raise ValueError("口型变换矩阵无效")
        for index, value in enumerate(matrix):
            _number(value, -8 if index < 4 else -16384, 8 if index < 4 else 16384, "matrix")
        if matrix[0] * matrix[3] - matrix[1] * matrix[2] <= .0001:
            raise ValueError("口型变换矩阵不能退化或翻转")
    fingerprint = data.get("sourceFingerprint", "")
    if not isinstance(fingerprint, str) or len(fingerprint) != 64 or any(c not in "0123456789abcdef" for c in fingerprint):
        raise ValueError("口型来源指纹无效")
    data["correction"] = correction(data.get("correction"))
    return data


def valid_mouth_sync(sprite):
    path = sprite_field(sprite, "mouth_sync", "")
    if not path:
        return ""
    try:
        data = read_manifest(path)
        if data["sourceFingerprint"] == sprite_fingerprint(sprite_field(sprite, "path", "")):
            return str(path)
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return ""
