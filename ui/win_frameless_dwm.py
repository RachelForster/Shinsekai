"""
Windows 无边框 + 分层/透明 窗口在 DWM 下常见「外围约 1px 发灰线」：通过 DWM 将窗体描边/角风格与
内容底色对齐。旧版 Windows 上部分属性会失败，可忽略。

调用方：**设置窗口**用 `theme` / RGB 边框色；**Chat UI** 使用 ``border_color_none=True``（Win11+）以
按微软文档抑制薄边框，避免黑/灰描边。
"""

from __future__ import annotations

import ctypes
import re
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget


def _rgb_from_theme(theme: str) -> tuple[int, int, int] | None:
    if not theme or not theme.startswith("#"):
        return None
    h = theme.strip().lstrip("#")
    if len(h) == 6 and re.fullmatch(r"[0-9A-Fa-f]+", h):
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b_ = int(h[4:6], 16)
        return (r, g, b_)
    return None


def _colorref_bgr(r: int, g: int, b: int) -> int:
    return (r & 0xFF) | ((g & 0xFF) << 8) | ((b & 0xFF) << 16)


def apply_win_frameless_dwm_hacks(
    w: "QWidget",
    *,
    r: int = 40,
    g: int = 44,
    b: int = 52,
    theme_color: str | None = None,
    apply_border_color: bool = True,
    border_color_none: bool = False,
) -> None:
    """在窗口已有原生 HWND 后调用（例如 showEvent 中）。

    ``border_color_none``: 为 True 时 ``DWMWA_BORDER_COLOR`` 设为 ``DWMWA_COLOR_NONE`` (0xFFFFFFFE)，
    按 Win11 文档抑制窗体细边框；旧版 Windows 上可能无效（忽略即可）。
    """
    if sys.platform != "win32":
        return
    try:
        hwnd = int(w.winId())
    except (TypeError, ValueError, AttributeError):
        return
    if hwnd == 0:
        return
    t = _rgb_from_theme(theme_color) if theme_color else None
    if t is not None:
        r, g, b = t
    _apply_dwm(
        hwnd,
        r,
        g,
        b,
        apply_border_color=apply_border_color,
        border_color_none=border_color_none,
    )


def _apply_dwm(
    hwnd: int,
    r: int,
    g: int,
    b: int,
    *,
    apply_border_color: bool = True,
    border_color_none: bool = False,
) -> None:
    from ctypes import wintypes

    try:
        dwm = ctypes.windll.dwmapi
    except OSError:
        return

    h = wintypes.HWND(hwnd)
    p_nc = wintypes.DWORD(1)  # DWMNCRP_DISABLED
    p_imm = wintypes.BOOL(1)  # TRUE: immersive dark
    # 不再设置 DWMWA_WINDOW_CORNER_PREFERENCE，避免 DWMWCP_DONOTROUND 消掉 Win11 圆角外沿。

    DWMWA_NCRENDERING_POLICY = 2
    DWMWA_USE_IMMERSIVE_DARK_MODE = 20
    DWMWA_BORDER_COLOR = 34
    # Win11 SDK：抑制 DWM 绘制的薄边框（与「设为黑色」不同，可避免明显黑边）
    DWMWA_COLOR_NONE = 0xFFFFFFFE

    attrs: list[tuple[int, object]] = [
        (DWMWA_NCRENDERING_POLICY, p_nc),
        (DWMWA_USE_IMMERSIVE_DARK_MODE, p_imm),
    ]
    if border_color_none:
        attrs.append((DWMWA_BORDER_COLOR, wintypes.DWORD(DWMWA_COLOR_NONE)))
    elif apply_border_color:
        attrs.append(
            (DWMWA_BORDER_COLOR, wintypes.DWORD(_colorref_bgr(r, g, b)))
        )
    for attr, ref in attrs:
        try:
            dwm.DwmSetWindowAttribute(h, attr, ctypes.byref(ref), ctypes.sizeof(ref))
        except (OSError, ValueError, ctypes.ArgumentError):
            pass
