"""
聊天主窗（Chat UI）可选外观补丁：单文件 JSON，仅允许「美化」相关 QSS 片段。

禁止写入会影响布局/尺寸的声明（width/height、font-size 等），具体见 :func:`sanitize_chrome_declarations`。

桌面助手进程（``main_sprite`` / ``start_qt_app``）会使用 Fusion 风格以便 QSS 圆角等在 Windows 上可靠生效，见 :mod:`ui.chat_ui.qss_fusion`。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ui/chat_ui/theme_chrome.py -> 项目根
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_cached_key: tuple[str, str, float] | None = None
_cached_theme: ChatChromeTheme | None = None

# 设置 UI 等可指向临时 JSON，便于不覆盖 ``data/chat_ui_theme.json`` 的实时预览。
_preview_path: Path | None = None


def set_chat_chrome_theme_preview_path(path: str | Path | None) -> None:
    """
    指定聊天外观预览用 JSON 路径；``None`` 表示恢复为配置中的正式路径。
    调用会清空主题缓存。
    """
    global _preview_path, _cached_key, _cached_theme
    if path is None or str(path).strip() == "":
        _preview_path = None
    else:
        _preview_path = Path(path).expanduser().resolve()
    _cached_key = None
    _cached_theme = None


def clear_chat_chrome_theme_cache() -> None:
    """丢弃内存缓存，下次 :func:`get_chat_chrome_theme` 会从磁盘重新读取 JSON。"""
    global _cached_key, _cached_theme
    _cached_key = None
    _cached_theme = None


@dataclass
class ChatChromeTheme:
    """各段 ``extra_qss`` 为分号分隔的 QSS 声明，会合并进内置样式（不替换整块样式）。"""

    numeric_label_extra: str = ""
    dialog_label_extra: str = ""
    input_bar_extra: str = ""
    busy_bar_label_extra: str = ""
    option_row_extra: str = ""
    option_row_hover_extra: str = ""
    options_container_extra: str = ""
    send_button_extra: str = ""
    mic_inactive_background: str | None = None
    mic_active_background: str | None = None
    mic_extra_qss: str = ""


def project_root() -> Path:
    return _PROJECT_ROOT


_FORBIDDEN_DECL = re.compile(
    r"(?i)\s*(width|height|min-width|max-width|min-height|max-height|"
    r"min-size|max-size|position|left|right|top|bottom|font-size)\s*:"
)


def _normalize_file_urls_in_qss_fragment(fragment: str) -> str:
    """
    Qt 在 Windows 上解析 ``url("file:///C:/...")`` 常会失败并打出
    ``Could not create pixmap from file:\\\\C:\\...``。
    改为 ``url("C:/...")``（仅盘符路径）。
    """
    if "file:" not in fragment.lower():
        return fragment

    def repl(m: re.Match[str]) -> str:
        inner = m.group(1).strip()
        if len(inner) >= 2 and inner[0] in "\"'":
            if inner[-1] == inner[0]:
                inner = inner[1:-1]
        if not inner.lower().startswith("file:"):
            return m.group(0)
        path_part = re.sub(r"(?i)^file:///+", "", inner)
        path_part = path_part.lstrip("/")
        if not re.match(r"^[a-zA-Z]:", path_part):
            return m.group(0)
        posix = path_part.replace("\\", "/")
        return f'url("{posix}")'

    return re.sub(r"(?i)url\s*\(\s*([^)]+)\)", repl, fragment)


def sanitize_chrome_declarations(fragment: str) -> str:
    """
    从用户提供的 QSS 片段中剔除禁止属性，返回可安全拼接的声明串（无外层花括号）。
    """
    if not fragment or not str(fragment).strip():
        return ""
    fragment = _normalize_file_urls_in_qss_fragment(str(fragment))
    parts: list[str] = []
    for raw in str(fragment).split(";"):
        piece = raw.strip()
        if not piece or _FORBIDDEN_DECL.match(piece):
            continue
        parts.append(piece)
    if not parts:
        return ""
    return "; ".join(parts) + ";"


_RADIUS_DECL = re.compile(
    r"(?i)^border-radius\s*:\s*(.+)$",
)


def extract_border_radius_from_chrome(sanitized_fragment: str) -> tuple[str, str]:
    """
    从已 sanitize 的片段中移除 ``border-radius`` 声明，保证可在整条 QSS 规则末尾再写圆角
    （避免 ``border`` 画在最后一轮圆角之后导致直角）。

    返回 ``(其余声明串联, 半径值)``；未写圆角时半径为空串，由调用方用默认值。
    """
    if not (sanitized_fragment or "").strip():
        return "", ""
    kept: list[str] = []
    last_radius = ""
    for raw in str(sanitized_fragment).split(";"):
        piece = raw.strip()
        if not piece:
            continue
        m = _RADIUS_DECL.match(piece)
        if m:
            last_radius = m.group(1).strip()
            continue
        kept.append(piece)
    rest = "; ".join(kept) + ";" if kept else ""
    return rest, last_radius


def _suffix(chrome_extra: str) -> str:
    s = sanitize_chrome_declarations(chrome_extra)
    return f"\n                {s}" if s else ""


def resolve_theme_path(system_chat_ui_theme_path: str) -> Path:
    """``system_config.chat_ui_theme_path`` 为空时用 ``data/chat_ui_theme.json``。"""
    raw = (system_chat_ui_theme_path or "").strip()
    if raw:
        p = Path(raw)
        if not p.is_absolute():
            p = _PROJECT_ROOT / p
        return p
    return _PROJECT_ROOT / "data" / "chat_ui_theme.json"


def _pick_extra(blob: dict[str, Any] | None, key: str) -> str:
    if not blob or not isinstance(blob, dict):
        return ""
    block = blob.get(key)
    if not isinstance(block, dict):
        return ""
    return str(block.get("extra_qss") or "").strip()


def _pick_hover_extra(blob: dict[str, Any] | None, key: str) -> str:
    if not blob or not isinstance(blob, dict):
        return ""
    block = blob.get(key)
    if not isinstance(block, dict):
        return ""
    return str(block.get("hover_extra_qss") or "").strip()


def _mic_from_raw(raw: dict[str, Any] | None) -> tuple[str | None, str | None, str]:
    if not raw or not isinstance(raw, dict):
        return None, None, ""
    m = raw.get("microphone_button")
    if not isinstance(m, dict):
        return None, None, ""
    ia = m.get("inactive_background")
    aa = m.get("active_background")
    ex = str(m.get("extra_qss") or "").strip()
    return (
        str(ia).strip() if ia is not None and str(ia).strip() else None,
        str(aa).strip() if aa is not None and str(aa).strip() else None,
        ex,
    )


def _parse_theme_file(path: Path) -> ChatChromeTheme:
    with path.open(encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        return ChatChromeTheme()
    mic_i, mic_a, mic_x = _mic_from_raw(raw)
    return ChatChromeTheme(
        numeric_label_extra=_pick_extra(raw, "numeric_label"),
        dialog_label_extra=_pick_extra(raw, "dialog_label"),
        input_bar_extra=_pick_extra(raw, "input_bar"),
        busy_bar_label_extra=_pick_extra(raw, "busy_bar_label"),
        option_row_extra=_pick_extra(raw, "option_row"),
        option_row_hover_extra=_pick_hover_extra(raw, "option_row"),
        options_container_extra=_pick_extra(raw, "options_container"),
        send_button_extra=_pick_extra(raw, "send_button"),
        mic_inactive_background=mic_i,
        mic_active_background=mic_a,
        mic_extra_qss=mic_x,
    )


def get_chat_chrome_theme(system_chat_ui_theme_path: str = "") -> ChatChromeTheme:
    """
    读取主题 JSON（带缓存：路径 + mtime）。文件不存在则返回空主题。
    若已设置 :func:`set_chat_chrome_theme_preview_path` 且该文件存在，则优先读预览文件。
    """
    global _cached_key, _cached_theme
    path: Path
    cache_tag: str
    if _preview_path is not None and _preview_path.is_file():
        path = _preview_path
        cache_tag = "preview"
    else:
        path = resolve_theme_path(system_chat_ui_theme_path)
        cache_tag = "normal"
    if not path.is_file():
        return ChatChromeTheme()
    mtime = path.stat().st_mtime
    key = (cache_tag, str(path.resolve()), mtime)
    if _cached_theme is not None and _cached_key == key:
        return _cached_theme
    try:
        theme = _parse_theme_file(path)
    except Exception:
        theme = ChatChromeTheme()
    _cached_key = key
    _cached_theme = theme
    return theme
