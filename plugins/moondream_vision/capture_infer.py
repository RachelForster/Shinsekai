from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)

try:
    import mss
    from PIL import Image
except ImportError as e:  # pragma: no cover
    mss = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]
    _import_err = e
else:
    _import_err = None


def monitor_max_side_pixels(monitor_index: int) -> int:
    """当前 mss 监视器宽高中的较大边（像素），用于鼠标移动百分比阈值。"""
    if mss is None:
        return 1080
    with mss.mss() as sct:
        if monitor_index < 0 or monitor_index >= len(sct.monitors):
            monitor_index = 1
        mon = sct.monitors[monitor_index]
        w = int(mon.get("width", 0))
        h = int(mon.get("height", 0))
        return max(w, h, 1)


def _grab_screen_rgb(monitor_index: int) -> Image.Image:
    if mss is None or Image is None:
        raise RuntimeError(
            "需要 mss 与 Pillow：pip install -r plugins/moondream_vision/requirements.txt"
        ) from _import_err
    with mss.mss() as sct:
        if monitor_index < 0 or monitor_index >= len(sct.monitors):
            monitor_index = 1
        mon = sct.monitors[monitor_index]
        shot = sct.grab(mon)
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def grab_screen_thumbnail(monitor_index: int, max_side: int = 96) -> Image.Image:
    """下采样灰度图，用于低成本差分检测。"""
    im = _grab_screen_rgb(monitor_index)
    w, h = im.size
    side = max(w, h)
    if side > max_side and side > 0:
        scale = max_side / float(side)
        im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.BILINEAR)
    return im.convert("L")


def thumbnail_change_ratio(prev: Image.Image | None, curr: Image.Image) -> float:
    """0~1，缩略图像素级相对上一参考帧的变化比例。"""
    if prev is None:
        return 0.0
    if prev.size != curr.size:
        curr = curr.resize(prev.size, Image.Resampling.BILINEAR)
    a = prev.tobytes()
    b = curr.tobytes()
    n = len(a)
    if n == 0:
        return 0.0
    changed = 0
    threshold = 14
    for i in range(n):
        if abs(a[i] - b[i]) > threshold:
            changed += 1
    return changed / float(n)


def grab_screen_png(monitor_index: int) -> bytes:
    im = _grab_screen_rgb(monitor_index)
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
