"""Select likely subtitle lines from the spatial output of RapidOCR."""

from dataclasses import dataclass


_PLAYER_LABELS = {
    "播放", "暂停", "倍速", "字幕", "全屏", "设置", "画质", "自动", "关闭弹幕", "开启弹幕",
    "play", "pause", "settings", "subtitles", "fullscreen", "auto",
}
_CURSOR_CHROME_LABELS = _PLAYER_LABELS | {
    "点赞", "收藏", "投币", "分享", "转发", "回复", "评论", "关注", "已关注", "复制", "确定", "取消",
}


@dataclass(frozen=True)
class _Line:
    text: str
    x: float
    y: float
    left: float
    right: float
    height: float


def select_screen_text(rows) -> str:
    """Read confident text in the chosen image, including text away from the bottom."""
    lines = []
    for box, raw_text, confidence in rows or ():
        text = " ".join(str(raw_text).split())
        if confidence >= 0.65 and text:
            xs, ys = zip(*box)
            lines.append((min(ys), min(xs), text[:120]))
    return "\n".join(dict.fromkeys(text for _, _, text in sorted(lines)))[:360]


def select_subtitles(rows, *, width: int, height: int) -> str:
    """Keep lower-half subtitles or RPG/Galgame dialogue boxes in reading order."""
    if width <= 0 or height <= 0:
        return ""

    candidates: list[_Line] = []
    for box, raw_text, confidence in rows or ():
        text = " ".join(str(raw_text).split())
        if (
            confidence < 0.65 or len(text) < 2 or text.casefold() in _PLAYER_LABELS
            or not any(char.isalpha() for char in text)
        ):
            continue
        xs, ys = zip(*box)
        left = min(xs) / width
        right = max(xs) / width
        x = (min(xs) + max(xs)) / (2 * width)
        y = (min(ys) + max(ys)) / (2 * height)
        line_height = (max(ys) - min(ys)) / height
        if (
            0.18 <= x <= 0.80
            and left < 0.70
            and right > 0.25
            and 0.54 <= y <= 0.96
            and 0.012 <= line_height <= 0.12
        ):
            candidates.append(_Line(text[:120], x, y, left, right, line_height))

    if not candidates:
        return ""
    anchor = min(candidates, key=lambda line: 0.65 * abs(line.x - 0.5) + 0.35 * abs(line.y - 0.84))
    nearby = [
        line for line in candidates
        if abs(line.y - anchor.y) <= 2.4 * max(line.height, anchor.height)
        and (abs(line.x - anchor.x) <= 0.34 or abs(line.left - anchor.left) <= 0.08)
    ]
    nearby.sort(key=lambda line: (line.y, line.x))
    return "\n".join(dict.fromkeys(line.text for line in nearby))[:360]


def _join_reading_lines(lines: list[str]) -> str:
    if not lines:
        return ""
    out = lines[0]
    for nxt in lines[1:]:
        if not nxt:
            continue
        sep = " " if (out[-1].isascii() and nxt[0].isascii()) else ""
        out = f"{out}{sep}{nxt}"
    return out[:220]


def select_cursor_text(rows, *, width: int, height: int) -> str:
    """Select the confident line(s) closest to the cursor center `(0.5, 0.5)` of a local ROI crop."""
    if width <= 0 or height <= 0:
        return ""

    scored: list[tuple[float, float, _Line]] = []
    for box, raw_text, confidence in rows or ():
        text = " ".join(str(raw_text).split())
        if (
            confidence < 0.65
            or len(text) < 2
            or text.casefold() in _CURSOR_CHROME_LABELS
            or not any(char.isalnum() for char in text)
        ):
            continue
        xs, ys = zip(*box)
        left = min(xs) / width
        right = max(xs) / width
        top = min(ys) / height
        bottom = max(ys) / height
        x = (left + right) / 2
        y = (top + bottom) / 2
        line_height = max(0.02, bottom - top)
        dy = 0.0 if top <= 0.5 <= bottom else min(abs(0.5 - top), abs(0.5 - bottom))
        dx = 0.0 if left <= 0.5 <= right else min(abs(0.5 - left), abs(0.5 - right))
        score = 0.75 * dy + 0.25 * dx
        scored.append((score, dy, _Line(text[:140], x, y, left, right, line_height)))

    if not scored:
        return ""
    _, anchor_dy, anchor = min(scored, key=lambda item: item[0])
    if anchor_dy > 0.36:
        return ""

    nearby = [
        line
        for _, _, line in scored
        if abs(line.y - anchor.y) <= 1.85 * max(line.height, anchor.height)
        and (abs(line.left - anchor.left) <= 0.16 or abs(line.x - anchor.x) <= 0.28)
    ]
    nearby.sort(key=lambda line: (line.y, line.x))
    unique_lines = list(dict.fromkeys(line.text for line in nearby))[:3]
    return _join_reading_lines(unique_lines)
