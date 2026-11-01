"""Choose a screen distinct from both anchors and recover soft foreground edges."""

SCREEN_COLORS = (
    ("green", (0, 255, 0)),
    ("blue", (0, 0, 255)),
    ("magenta", (255, 0, 255)),
    ("cyan", (0, 255, 255)),
    ("yellow", (255, 255, 0)),
    ("red", (255, 0, 0)),
)
SCREEN_VERSION = 1


def _chromaticity(rgb):
    import numpy as np

    values = np.asarray(rgb, dtype=np.float32)
    return values / np.maximum(values.sum(axis=-1, keepdims=True), 1)


def validate_screen_color(color):
    if (
        not isinstance(color, (list, tuple))
        or len(color) != 3
        or any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value <= 255
            for value in color
        )
        or tuple(color) not in {rgb for _, rgb in SCREEN_COLORS}
    ):
        raise ValueError("无效的纯色幕颜色")
    return tuple(color)


def choose_screen_color(paths):
    """Include rare foreground colors (eyes/accessories), not just dominant colors.

    An opaque anchor cannot be safely recolored without changing its contents.
    Leave it to AI matting instead of inventing a foreground mask before rendering.
    """
    import numpy as np
    from PIL import Image, ImageOps

    palettes = []
    for path in paths:
        with Image.open(path) as image:
            rgba = np.asarray(ImageOps.exif_transpose(image).convert("RGBA"))
        alpha = rgba[..., 3]
        if np.count_nonzero(alpha < 16) < alpha.size * 0.001:
            return {"method": "ai", "reason": "opaque-reference"}
        foreground = rgba[..., :3][alpha >= 64]
        if not len(foreground):
            raise ValueError("参考图没有可见人物，请选择完整的透明立绘")
        # A bounded 5-bit palette retains tiny accents without downscaling them away.
        packed = foreground.astype(np.uint16) >> 3
        packed = (packed[:, 0] << 10) | (packed[:, 1] << 5) | packed[:, 2]
        unique = np.unique(packed)
        palette = (
            np.stack(((unique >> 10) & 31, (unique >> 5) & 31, unique & 31), axis=-1)
            * 8
            + 4
        )
        # Near black has no reliable hue and will always be protected during keying.
        palette = palette[palette.sum(axis=-1) > 32]
        if len(palette):
            palettes.append(_chromaticity(palette))
    foreground = np.concatenate(palettes) if palettes else np.empty((0, 3))
    scores = []
    for name, color in SCREEN_COLORS:
        distances = np.linalg.norm(foreground - _chromaticity(color), axis=-1)
        scores.append((float(distances.min()) if len(distances) else 1.0, name, color))
    distance, name, color = max(scores, key=lambda item: item[0])
    if distance < 0.28:
        return {"method": "ai", "reason": "foreground-colors"}
    return {
        "method": "chroma",
        "screenColor": list(color),
        "screenName": name,
        "screenTolerance": min(0.20, distance * 0.55),
        "screenForegroundDistance": distance,
        "version": SCREEN_VERSION,
    }


def _observed_screen(rgb, color, foreground_distance):
    """Calibrate codec/model tint from matching border pixels, never from the body."""
    import numpy as np

    strip = max(1, min(rgb.shape[:2]) // 64)
    border = np.concatenate(
        (
            rgb[:strip].reshape(-1, 3),
            rgb[-strip:].reshape(-1, 3),
            rgb[:, :strip].reshape(-1, 3),
            rgb[:, -strip:].reshape(-1, 3),
        )
    )
    distances = np.linalg.norm(_chromaticity(border) - _chromaticity(color), axis=-1)
    allowed_drift = min(0.25, foreground_distance * 0.45)
    matching = border[(distances <= allowed_drift) & (border.max(axis=-1) >= 96)]
    if len(matching) < max(4, len(border) * 0.01):
        return color, 0.0
    observed = np.median(matching, axis=0)
    drift = float(np.linalg.norm(_chromaticity(observed) - _chromaticity(color)))
    return observed, drift


def screen_prompt(settings):
    if settings.get("method") != "chroma":
        return ""
    color = validate_screen_color(settings["screenColor"])
    hex_color = "#" + "".join(f"{value:02X}" for value in color)
    return (
        f"; keep a perfectly uniform solid {settings['screenName']} chroma-key background "
        f"({hex_color}) throughout every frame, flat evenly lit screen, no gradient, "
        "no background texture, no cast shadow on the screen; preserve the character's "
        "original colors with no screen-color reflection or spill on the character"
    )


def remove_screen_background(image, settings, *, alpha_matting=True):
    import numpy as np
    from PIL import Image

    color = validate_screen_color(settings.get("screenColor"))
    tolerance = settings.get("screenTolerance", 0.20)
    if (
        isinstance(tolerance, bool)
        or not isinstance(tolerance, (int, float))
        or not 0.05 <= tolerance <= 0.20
    ):
        raise ValueError("无效的纯色幕容差")
    rgb = np.asarray(image.convert("RGB"))
    foreground_distance = settings.get("screenForegroundDistance", 0.5)
    if (
        isinstance(foreground_distance, bool)
        or not isinstance(foreground_distance, (int, float))
        or not 0.28 <= foreground_distance <= 1.5
    ):
        raise ValueError("无效的纯色幕前景距离")
    color, drift = _observed_screen(rgb, color, foreground_distance)
    tolerance = max(0.05, min(tolerance, (foreground_distance - drift) * 0.55))
    distance = np.linalg.norm(_chromaticity(rgb) - _chromaticity(color), axis=-1)
    alpha = np.clip((distance - 0.04) / (tolerance - 0.04), 0, 1)
    alpha = alpha * alpha * (3 - 2 * alpha)
    # Do not punch holes in black clothing where hue is undefined.
    alpha[rgb.astype(np.uint16).sum(axis=-1) <= 32] = 1
    mask = Image.fromarray(np.rint(alpha * 255).astype(np.uint8), "L")
    if not np.any(alpha < 0.04) or not np.any(alpha > 0.96):
        raise ValueError("生成画面未保留可识别的纯色背景或人物，无法安全抠图，请重绘")
    if alpha_matting:
        from core.media.alpha_matting import refine_alpha_edges

        return _remove_edge_spill(
            refine_alpha_edges(image, mask), settings["screenColor"]
        )
    # Recover straight foreground RGB from the known screen, rather than leaving
    # colored antialiasing around partially transparent hair and fabric.
    foreground = (
        rgb.astype(np.float32) - (1 - alpha[..., None]) * np.asarray(color)
    ) / np.maximum(alpha[..., None], 1 / 255)
    output = np.dstack((np.clip(foreground, 0, 255).astype(np.uint8), np.asarray(mask)))
    return Image.fromarray(output, "RGBA")


def _remove_edge_spill(image, color):
    """Suppress the selected screen only in the narrow visible boundary band."""
    import numpy as np
    from PIL import Image
    from scipy.ndimage import binary_erosion

    rgba = np.asarray(image.convert("RGBA")).copy()
    alpha = rgba[..., 3]
    edge = (alpha > 0) & ~binary_erosion(alpha >= 250, iterations=2, border_value=0)
    rgb = rgba[..., :3].astype(np.int16)
    on = np.asarray(color) > 127
    off = ~on
    excess = np.maximum(0, rgb[..., on].min(axis=-1) - rgb[..., off].max(axis=-1))
    for channel in np.flatnonzero(on):
        rgb[..., channel] -= np.where(edge, excess, 0)
    rgba[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")
