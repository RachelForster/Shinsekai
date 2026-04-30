from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass, field

from PIL import Image

from plugins.moondream_vision.capture_infer import (
    monitor_max_side_pixels,
    thumbnail_change_ratio,
)
from plugins.moondream_vision.config_model import MoondreamVisionConfig


@dataclass
class _WinApi:
    user32: ctypes.WinDLL | None = None

    def __post_init__(self) -> None:
        if sys.platform != "win32":
            return
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)


_win = _WinApi()


def _cursor_pos_win() -> tuple[int, int] | None:
    if _win.user32 is None:
        return None

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    pt = POINT()
    if not _win.user32.GetCursorPos(ctypes.byref(pt)):
        return None
    return int(pt.x), int(pt.y)


def _cursor_pos_any() -> tuple[int, int] | None:
    p = _cursor_pos_win()
    if p is not None:
        return p
    try:
        from PyQt6.QtGui import QCursor

        q = QCursor.globalPosition()
        return int(q.x()), int(q.y())
    except Exception:
        return None


def _enum_top_level_hwnds_win() -> frozenset[int]:
    user32 = _win.user32
    if user32 is None:
        return frozenset()

    hwnds: set[int] = set()
    try:
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        IsWindowVisible = user32.IsWindowVisible
        IsWindowVisible.argtypes = [ctypes.c_void_p]
        IsWindowVisible.restype = ctypes.c_bool

        @WNDENUMPROC
        def _enum_proc(hwnd: ctypes.c_void_p, _lp: ctypes.c_void_p) -> bool:
            if IsWindowVisible(hwnd):
                hwnds.add(int(hwnd))
            return True

        user32.EnumWindows(_enum_proc, 0)
    except OSError:
        return frozenset()
    return frozenset(hwnds)


def _foreground_hwnd_win() -> int:
    if _win.user32 is None:
        return 0
    try:
        return int(_win.user32.GetForegroundWindow() or 0)
    except OSError:
        return 0


def _dist2(ax: int, ay: int, bx: int, by: int) -> int:
    dx = ax - bx
    dy = ay - by
    return dx * dx + dy * dy


@dataclass
class MoondreamTriggerState:
    """差分屏幕、鼠标位移、（Windows）新顶层窗口与前台切换。"""

    _primed: bool = False
    _last_thumb_ref: Image.Image | None = None
    _last_mouse: tuple[int, int] | None = None
    _last_hwnds: frozenset[int] | None = None
    _last_fg: int | None = None
    _reasons: list[str] = field(default_factory=list)

    def reset_after_config_hot_reload(self) -> None:
        self._primed = False
        self._last_thumb_ref = None
        self._last_mouse = None
        self._last_hwnds = None
        self._last_fg = None

    def evaluate(
        self, cfg: MoondreamVisionConfig, thumb: Image.Image
    ) -> tuple[bool, list[str]]:
        """本采样是否应尝试推理（仍需外部冷却）。"""
        reasons: list[str] = []
        thr = float(cfg.diff_threshold)
        max_side = monitor_max_side_pixels(cfg.monitor_index)
        pct = float(cfg.mouse_move_percent)
        mouse_px = max(1, int(max_side * pct / 100.0))

        diff_ratio = 0.0
        if self._last_thumb_ref is not None:
            diff_ratio = thumbnail_change_ratio(self._last_thumb_ref, thumb)

        cur = _cursor_pos_any()
        if cur is not None:
            if self._last_mouse is None:
                self._last_mouse = cur
            else:
                lim2 = mouse_px * mouse_px
                if _dist2(cur[0], cur[1], self._last_mouse[0], self._last_mouse[1]) > lim2:
                    reasons.append("mouse")
                    self._last_mouse = cur

        if self._primed and self._last_thumb_ref is not None and diff_ratio >= thr:
            reasons.append("screen_diff")

        if sys.platform == "win32":
            hwnds = _enum_top_level_hwnds_win()
            fg = _foreground_hwnd_win()
            if self._primed:
                if self._last_hwnds is not None and (hwnds - self._last_hwnds):
                    reasons.append("new_window")
                if self._last_fg is not None and fg != 0 and fg != self._last_fg:
                    reasons.append("foreground")
            self._last_hwnds = hwnds
            if fg != 0:
                self._last_fg = fg

        if not self._primed:
            self._primed = True
            self._last_thumb_ref = thumb.copy()
            return False, []

        fired = bool(reasons)
        self._reasons = reasons
        return fired, list(reasons)

    def on_infer_done(self, thumb_at_infer: Image.Image) -> None:
        """成功送模型后刷新参考帧，避免同一画面反复差分触发。"""
        self._last_thumb_ref = thumb_at_infer.copy()
