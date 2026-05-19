"""Tests for manifest-backed real-frame sprite animations."""

from __future__ import annotations

import json

import cv2
import numpy as np
import pytest

from core.sprite.animated_sprite import load_sprite_animation


def _write_png(path, rgba: np.ndarray) -> None:
    bgra = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA)
    ok, encoded = cv2.imencode(".png", bgra)
    assert ok
    encoded.tofile(path)


def test_load_sprite_animation_slices_row_and_keeps_durations(tmp_path):
    cell_w, cell_h = 2, 2
    sheet = np.zeros((cell_h, cell_w * 2, 4), dtype=np.uint8)
    sheet[:, 0:cell_w] = [255, 0, 0, 255]
    sheet[:, cell_w : cell_w * 2] = [0, 255, 0, 255]
    sheet_path = tmp_path / "sheet.png"
    _write_png(sheet_path, sheet)

    manifest = {
        "cell_size": [cell_w, cell_h],
        "columns": 2,
        "rows": [
            {
                "name": "idle",
                "frame_count": 2,
                "durations_ms": [80, 120],
            }
        ],
        "spritesheet_png": "sheet.png",
    }
    manifest_path = tmp_path / "animation-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    animation = load_sprite_animation(manifest_path, "idle")

    assert animation.state == "idle"
    assert animation.durations_ms == [80, 120]
    assert len(animation.frames) == 2
    assert animation.frames[0][0, 0].tolist() == [255, 0, 0, 255]
    assert animation.frames[1][0, 0].tolist() == [0, 255, 0, 255]


def test_load_sprite_animation_rejects_bad_duration_count(tmp_path):
    sheet = np.zeros((2, 4, 4), dtype=np.uint8)
    sheet[:, :] = [255, 0, 0, 255]
    sheet_path = tmp_path / "sheet.png"
    _write_png(sheet_path, sheet)
    manifest_path = tmp_path / "animation-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "cell_size": [2, 2],
                "columns": 2,
                "rows": [{"name": "idle", "frame_count": 2, "durations_ms": [80]}],
                "spritesheet_png": "sheet.png",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as exc_info:
        load_sprite_animation(manifest_path, "idle")
    assert "durations_ms" in str(exc_info.value)
