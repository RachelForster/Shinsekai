from __future__ import annotations

import subprocess
import sys

import pytest


def test_load_image_rgba_array_supports_unicode_paths(tmp_path):
    """Run legacy Qt image loading in a child process so broken DLLs can skip safely."""

    image_path = tmp_path / "立绘.png"
    script = """
import json
import sys
from PySide6.QtGui import QColor, QImage
from core.runtime.ui_update_manager import _load_image_rgba_array

image_format = getattr(getattr(QImage, "Format", QImage), "Format_RGBA8888")
image = QImage(2, 1, image_format)
image.setPixelColor(0, 0, QColor(10, 20, 30, 40))
image.setPixelColor(1, 0, QColor(50, 60, 70, 255))
assert image.save(sys.argv[1])
array = _load_image_rgba_array(sys.argv[1])
print(json.dumps({"shape": list(array.shape), "pixels": array.tolist()}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(image_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        pytest.skip(
            "legacy Qt image support unavailable: "
            f"{(result.stderr or result.stdout).strip()[:300]}"
        )

    assert '"shape": [1, 2, 4]' in result.stdout
    assert "[10, 20, 30, 40]" in result.stdout
    assert "[50, 60, 70, 255]" in result.stdout
