"""Load manifest-backed character sprite animations.

The runtime still treats regular sprite images as the default path.  This
module only handles explicit spritesheet manifests produced by external asset
pipelines, so the UI can play real frames without synthesizing motion locally.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np


@dataclass(frozen=True)
class SpriteAnimationFrames:
    """Decoded RGBA frames and per-frame timing for one animation row."""

    frames: list[np.ndarray]
    durations_ms: list[int]
    state: str
    manifest_path: str
    spritesheet_path: str


def _decode_rgba(path: Path) -> np.ndarray:
    img_data = np.fromfile(path, dtype=np.uint8)
    image = cv2.imdecode(img_data, cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError(f"无法加载 spritesheet: {path}")
    if image.ndim != 3:
        raise ValueError(f"spritesheet 必须是 RGB/RGBA 图像: {path}")
    if image.shape[2] == 3:
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        alpha = np.full((rgb.shape[0], rgb.shape[1]), 255, dtype=np.uint8)
        return cv2.merge([rgb, alpha])
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2RGBA)
    raise ValueError(f"不支持的 spritesheet 通道数: {image.shape[2]}")


def _positive_int(value: Any, *, field_name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} 必须是整数: {value!r}") from exc
    if parsed <= 0:
        raise ValueError(f"{field_name} 必须大于 0: {parsed}")
    return parsed


def _select_row(rows: list[dict[str, Any]], state: str | None) -> tuple[int, dict[str, Any]]:
    if not rows:
        raise ValueError("animation manifest 缺少 rows")
    if state:
        for index, row in enumerate(rows):
            if str(row.get("name", "")) == state:
                return index, row
        raise ValueError(f"animation manifest 中找不到状态: {state}")
    return 0, rows[0]


def load_sprite_animation(manifest_path: str | Path, state: str | None = None) -> SpriteAnimationFrames:
    """Load one animation row from a longform spritesheet manifest.

    Supported manifest shape matches the longform interaction sprite pipeline:
    ``cell_size``, ``columns``, ``rows[*].frame_count``, optional
    ``rows[*].durations_ms`` / ``duration_ms``, and ``spritesheet_png`` or
    ``spritesheet_webp``.
    """

    manifest = Path(manifest_path).expanduser()
    if not manifest.exists():
        raise FileNotFoundError(f"animation manifest 不存在: {manifest}")
    data = json.loads(manifest.read_text(encoding="utf-8"))

    try:
        cell_w = _positive_int(data["cell_size"][0], field_name="cell_size[0]")
        cell_h = _positive_int(data["cell_size"][1], field_name="cell_size[1]")
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("animation manifest 缺少有效 cell_size") from exc

    columns = _positive_int(data.get("columns", 1), field_name="columns")
    rows_raw = data.get("rows", [])
    if not isinstance(rows_raw, list):
        raise ValueError("animation manifest 的 rows 必须是列表")
    if any(not isinstance(row, dict) for row in rows_raw):
        raise ValueError("animation manifest 的 rows 条目必须是对象")
    rows: list[dict[str, Any]] = rows_raw
    row_index, row = _select_row(rows, state)
    row_name = str(row.get("name") or state or row_index)
    frame_count = _positive_int(row.get("frame_count"), field_name=f"{row_name}.frame_count")
    if frame_count > columns:
        raise ValueError(f"{row_name}.frame_count({frame_count}) 超过 columns({columns})")

    raw_durations = row.get("durations_ms")
    if raw_durations is None:
        duration = _positive_int(row.get("duration_ms", 100), field_name=f"{row_name}.duration_ms")
        durations = [duration for _ in range(frame_count)]
    else:
        if not isinstance(raw_durations, list):
            raise ValueError(f"{row_name}.durations_ms 必须是列表")
        if len(raw_durations) != frame_count:
            raise ValueError(
                f"{row_name}.durations_ms 长度({len(raw_durations)}) 必须等于 frame_count({frame_count})"
            )
        durations = [
            _positive_int(value, field_name=f"{row_name}.durations_ms[{index}]")
            for index, value in enumerate(raw_durations)
        ]

    sheet_ref = data.get("spritesheet_png") or data.get("spritesheet_webp")
    if not sheet_ref:
        raise ValueError("animation manifest 缺少 spritesheet_png/spritesheet_webp")
    sheet_path = Path(sheet_ref)
    if not sheet_path.is_absolute():
        sheet_path = manifest.parent / sheet_path
    sheet = _decode_rgba(sheet_path)

    y0 = row_index * cell_h
    y1 = y0 + cell_h
    if y1 > sheet.shape[0]:
        raise ValueError(f"状态 {row_name} 超出 spritesheet 高度")

    frames: list[np.ndarray] = []
    for frame_index in range(frame_count):
        x0 = frame_index * cell_w
        x1 = x0 + cell_w
        if x1 > sheet.shape[1]:
            raise ValueError(f"状态 {row_name} 第 {frame_index} 帧超出 spritesheet 宽度")
        frames.append(np.ascontiguousarray(sheet[y0:y1, x0:x1, :]))

    return SpriteAnimationFrames(
        frames=frames,
        durations_ms=durations,
        state=row_name,
        manifest_path=manifest.as_posix(),
        spritesheet_path=sheet_path.as_posix(),
    )
