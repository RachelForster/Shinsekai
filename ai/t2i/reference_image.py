"""Fit reference artwork before a video node stretches its keyframe to a canvas."""

from io import BytesIO
from pathlib import Path


H3_SPRITE_RESOLUTIONS = {
    "workflow": None,
    "hd": (640, 1088),
    "native": (768, 1344),
}


def validate_h3_sprite_resolution(value):
    if not isinstance(value, str) or value not in H3_SPRITE_RESOLUTIONS:
        raise ValueError("H3 分辨率须为 workflow、hd 或 native")
    return value


def _validate_canvas(width: int, height: int) -> None:
    if (
        isinstance(width, bool)
        or isinstance(height, bool)
        or not isinstance(width, int)
        or not isinstance(height, int)
        or min(width, height) < 1
        or max(width, height) > 16_384
        or width * height > 16_777_216
    ):
        raise ValueError("H3 画布宽高应为 1–16384 的整数，且不能超过 1600 万像素")


def reference_canvas_size(path: str | Path, width: int, height: int) -> tuple[int, int]:
    """Choose a 32px-grid canvas close to the artwork within the workflow's budget."""
    from PIL import Image, ImageOps

    _validate_canvas(width, height)
    with Image.open(path) as image:
        oriented = ImageOps.exif_transpose(image)
        ratio = oriented.width / oriented.height
    return canvas_size_for_ratio(ratio, width, height)


def canvas_size_for_ratio(ratio: float, width: int, height: int) -> tuple[int, int]:
    """Fit an aspect ratio to a 32px grid within a canvas's pixel/edge budget."""
    _validate_canvas(width, height)
    budget = width * height
    long_edge = max(width, height)
    candidates = [
        (w, h)
        for w in range(32, long_edge + 1, 32)
        for h in range(32, long_edge + 1, 32)
        if w * h <= budget
    ]
    if not candidates:
        raise ValueError("H3 画布的宽高至少为 32 像素")

    def error(size):
        return abs(size[0] / size[1] / ratio - 1)

    close = [size for size in candidates if error(size) <= 0.02]
    if close:
        return max(close, key=lambda size: (size[0] * size[1], -error(size)))
    return min(candidates, key=lambda size: (error(size), -size[0] * size[1]))


def apply_h3_sprite_resolution(workflow, preset):
    """Resize only H3 nodes, retaining the workflow's orientation and proportions."""
    canvas = H3_SPRITE_RESOLUTIONS[validate_h3_sprite_resolution(preset)]
    if canvas is None:
        return
    for node in workflow.values():
        if node.get("class_type") != "MiniMaxH3ImageToVideo":
            continue
        inputs = node.get("inputs", {})
        width, height = inputs.get("width"), inputs.get("height")
        try:
            _validate_canvas(width, height)
        except ValueError as exc:
            raise ValueError(
                "H3 分辨率预设需要工作流中的 width、height 为整数；"
                "使用连接节点时请选择“跟随工作流”"
            ) from exc
        width, height = canvas_size_for_ratio(width / height, *canvas)
        inputs.update(width=width, height=height)


def fit_reference_to_canvas(
    path: str | Path, width: int, height: int, *, background="white"
) -> BytesIO:
    """Return an opaque PNG, preserving the original proportions and alpha edges."""
    from PIL import Image, ImageOps

    _validate_canvas(width, height)
    with Image.open(path) as source:
        oriented = ImageOps.exif_transpose(source).convert("RGBA")
        fitted = ImageOps.contain(oriented, (width, height), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (width, height), background)
        offset = ((width - fitted.width) // 2, (height - fitted.height) // 2)
        canvas.paste(fitted, offset, fitted.getchannel("A"))
    result = BytesIO()
    canvas.save(result, format="PNG")
    result.seek(0)
    return result
