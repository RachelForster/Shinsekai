"""Windows cursor-adjacent & highlighted text reader (`高亮 > 识别字幕 > 识别手边文字`)."""

from __future__ import annotations

from collections.abc import Callable
import base64
from dataclasses import dataclass
import io
import logging
import math
import os
import re
import sys
import time
from typing import Any, Literal, Protocol

from application.perception.reflex_policy import comparison_text
from core.perception.models import PerceptionFrame, ScreenOcrScope
from core.perception.policy import PerceptionMemoryPolicy

logger = logging.getLogger(__name__)

CURSOR_PATCH_HALF_WIDTH = 260
CURSOR_PATCH_HALF_HEIGHT = 80
_WHITESPACE_RE = re.compile(r"\s+")


def _clean_text(raw: str, *, max_chars: int = 320) -> str:
    text = _WHITESPACE_RE.sub(" ", str(raw or "").strip())
    return text[:max_chars].strip()


def _luma_mean_diff(left: bytes, right: bytes) -> float:
    if not left or len(left) != len(right):
        return 255.0
    return sum(abs(a - b) for a, b in zip(left, right)) / len(left)


def _drag_bbox(x0: int, y0: int, x1: int, y1: int) -> tuple[int, int, int, int]:
    cx = round((x0 + x1) / 2)
    cy = round((y0 + y1) / 2)
    half_w = min(360, max(90, round(abs(x1 - x0) / 2) + 22))
    half_h = min(110, max(28, round(abs(y1 - y0) / 2) + 24))
    return (cx - half_w, cy - half_h, cx + half_w, cy + half_h)


@dataclass(frozen=True, slots=True)
class CursorSample:
    """Instantaneous pointer position and button state in physical screen pixels."""

    x: int
    y: int
    left_down: bool
    over_self_window: bool = False


@dataclass(frozen=True, slots=True)
class CursorPatch:
    """Small native-DPI screen patch plus a `16×8` luma thumbnail for scroll detection."""

    frame: PerceptionFrame
    luma_thumb: bytes


@dataclass(frozen=True, slots=True)
class CursorObservation:
    """Recognized text produced by either explicit highlight or passive cursor hover."""

    text: str
    source: Literal["highlight", "cursor"]
    captured_at: float


class CursorProbe(Protocol):
    """OS boundary for pointer state, UIA text selection, and small-ROI capture."""

    def prepare_thread(self) -> None: ...
    def sample(self) -> CursorSample | None: ...
    def read_selected_text(self, x: int, y: int) -> str: ...
    def capture_patch(
        self,
        bbox: tuple[int, int, int, int],
        *,
        mode: Literal["cursor", "full"] = "cursor",
        captured_at: float | None = None,
    ) -> CursorPatch | None: ...
    def close(self) -> None: ...


class CursorReadingTracker:
    """Deterministic state machine enforcing `高亮 > 识别字幕 > 识别手边文字`."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._was_left_down: bool = False
        self._press_x: int = 0
        self._press_y: int = 0
        self._press_mono: float = 0.0
        self._press_over_self: bool = False
        self._last_click_up_mono: float = 0.0
        self._last_click_x: int = 0
        self._last_click_y: int = 0

        self._last_uia_key: str = ""
        self._last_highlight_mono: float = 0.0

        self._dwell_pos: tuple[int, int] | None = None
        self._dwell_since: float = 0.0
        self._last_probed_pos: tuple[int, int] | None = None
        self._last_patch_thumb: bytes | None = None
        self._last_patch_check_mono: float = 0.0
        self._last_ocr_call_mono: float = 0.0
        self._last_cursor_key: str = ""

    def step(
        self,
        *,
        sample: CursorSample | None,
        probe: CursorProbe,
        ocr_fn: Callable[[PerceptionFrame], str] | None,
        use_local_ocr: bool,
        subtitles_active: bool,
        policy: PerceptionMemoryPolicy,
        ocr_interval_sec: float = 1.0,
        now_mono: float,
        now_wall: float,
    ) -> CursorObservation | None:
        if sample is None:
            return None

        # ------------------------------------------------------------------
        # Tier 1: Explicit Highlight (`高亮`) — Highest priority, always active
        # ------------------------------------------------------------------
        if sample.left_down:
            if not self._was_left_down:
                self._was_left_down = True
                self._press_x = sample.x
                self._press_y = sample.y
                self._press_mono = now_mono
                self._press_over_self = sample.over_self_window
            self._dwell_pos = (sample.x, sample.y)
            self._dwell_since = now_mono
            return None

        if self._was_left_down:
            self._was_left_down = False
            self._dwell_pos = (sample.x, sample.y)
            self._dwell_since = now_mono

            dx = sample.x - self._press_x
            dy = sample.y - self._press_y
            drag_dist = math.hypot(dx, dy)
            press_dur = now_mono - self._press_mono
            is_multiclick = (
                drag_dist <= 8.0
                and self._last_click_up_mono > 0.0
                and (now_mono - self._last_click_up_mono) <= 0.45
                and math.hypot(sample.x - self._last_click_x, sample.y - self._last_click_y) <= 8.0
            )
            self._last_click_up_mono = now_mono
            self._last_click_x = sample.x
            self._last_click_y = sample.y

            if not self._press_over_self and not sample.over_self_window:
                is_drag_select = drag_dist >= 10.0 and 0.03 <= press_dur <= 20.0
                if is_drag_select or is_multiclick:
                    selected = _clean_text(probe.read_selected_text(sample.x, sample.y))
                    sel_key = comparison_text(selected)
                    if sel_key and len(selected) >= 2 and sel_key != self._last_uia_key:
                        self._last_uia_key = sel_key
                        self._last_highlight_mono = now_mono
                        return CursorObservation(
                            text=selected,
                            source="highlight",
                            captured_at=now_wall,
                        )
                    if (
                        not sel_key
                        and is_drag_select
                        and abs(dx) >= 24
                        and abs(dy) <= 200
                        and use_local_ocr
                        and ocr_fn is not None
                    ):
                        bbox = _drag_bbox(self._press_x, self._press_y, sample.x, sample.y)
                        patch = probe.capture_patch(bbox, mode="full", captured_at=now_wall)
                        if patch is not None:
                            self._last_ocr_call_mono = now_mono
                            ocr_text = _clean_text(ocr_fn(patch.frame))
                            if len(ocr_text) >= 2 and comparison_text(ocr_text):
                                self._last_highlight_mono = now_mono
                                return CursorObservation(
                                    text=ocr_text,
                                    source="highlight",
                                    captured_at=now_wall,
                                )
                else:
                    # Plain single click likely cleared any prior text selection
                    self._last_uia_key = ""
            return None

        # ------------------------------------------------------------------
        # Tier 2 Gate: Subtitles (`识别字幕`) & recent Highlight suppress Tier 3
        # ------------------------------------------------------------------
        if sample.over_self_window or not use_local_ocr or ocr_fn is None:
            return None
        if subtitles_active:
            return None
        if (
            self._last_highlight_mono > 0.0
            and (now_mono - self._last_highlight_mono) < policy.cursor_suppress_after_highlight_sec
        ):
            return None

        # ------------------------------------------------------------------
        # Tier 3: Cursor-Adjacent Text (`识别手边文字`) — Passive dwell fallback
        # ------------------------------------------------------------------
        if (
            self._dwell_pos is None
            or math.hypot(sample.x - self._dwell_pos[0], sample.y - self._dwell_pos[1]) > 14.0
        ):
            self._dwell_pos = (sample.x, sample.y)
            self._dwell_since = now_mono
            return None

        if (now_mono - self._dwell_since) < policy.cursor_hover_dwell_sec:
            return None

        moved_to_new_spot = (
            self._last_probed_pos is None
            or math.hypot(sample.x - self._last_probed_pos[0], sample.y - self._last_probed_pos[1]) >= 28.0
        )
        recheck_interval = max(1.2, ocr_interval_sec)
        if not moved_to_new_spot and (now_mono - self._last_patch_check_mono) < recheck_interval:
            return None

        min_ocr_gap = max(0.45, ocr_interval_sec * 0.5)
        if self._last_ocr_call_mono > 0.0 and (now_mono - self._last_ocr_call_mono) < min_ocr_gap:
            return None

        bbox = (
            sample.x - CURSOR_PATCH_HALF_WIDTH,
            sample.y - CURSOR_PATCH_HALF_HEIGHT,
            sample.x + CURSOR_PATCH_HALF_WIDTH,
            sample.y + CURSOR_PATCH_HALF_HEIGHT,
        )
        patch = probe.capture_patch(bbox, mode="cursor", captured_at=now_wall)
        self._last_patch_check_mono = now_mono
        if patch is None:
            self._last_probed_pos = (sample.x, sample.y)
            return None

        if (
            not moved_to_new_spot
            and self._last_patch_thumb is not None
            and _luma_mean_diff(self._last_patch_thumb, patch.luma_thumb) < 3.0
        ):
            return None

        self._last_probed_pos = (sample.x, sample.y)
        self._last_patch_thumb = patch.luma_thumb
        self._last_ocr_call_mono = now_mono

        text = _clean_text(ocr_fn(patch.frame))
        key = comparison_text(text)
        if key and len(text) >= 2 and key != self._last_cursor_key:
            self._last_cursor_key = key
            return CursorObservation(text=text, source="cursor", captured_at=now_wall)
        return None


# ---------------------------------------------------------------------------
# Windows Native Implementation (`ctypes` + `IUIAutomation` + `PIL.ImageGrab`)
# ---------------------------------------------------------------------------

if sys.platform == "win32":
    import ctypes
    import ctypes.wintypes as wt

    _VK_LBUTTON = 0x01
    _GA_ROOT = 2
    _TH32CS_SNAPPROCESS = 0x00000002
    _UIA_TEXT_PATTERN_ID = 10014
    _UIA_TEXT_PATTERN2_ID = 10024

    class _GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wt.DWORD),
            ("Data2", wt.WORD),
            ("Data3", wt.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

        @classmethod
        def from_str(cls, text: str) -> "_GUID":
            guid = cls()
            ctypes.windll.ole32.IIDFromString(ctypes.c_wchar_p(text), ctypes.byref(guid))
            return guid

    class _PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wt.DWORD),
            ("cntUsage", wt.DWORD),
            ("th32ProcessID", wt.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wt.DWORD),
            ("cntThreads", wt.DWORD),
            ("th32ParentProcessID", wt.DWORD),
            ("pcPriClassBase", wt.LONG),
            ("dwFlags", wt.DWORD),
            ("szExeFile", wt.WCHAR * 260),
        ]

    def _discover_self_pids() -> frozenset[int]:
        own_pid = os.getpid()
        pids = {own_pid}
        try:
            kernel32 = ctypes.windll.kernel32
            snap = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
            if snap in (-1, ctypes.c_void_p(-1).value, 0):
                return frozenset(pids)
            try:
                table: dict[int, tuple[int, str]] = {}
                entry = _PROCESSENTRY32W()
                entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
                ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
                while ok:
                    table[int(entry.th32ProcessID)] = (
                        int(entry.th32ParentProcessID),
                        str(entry.szExeFile or "").casefold(),
                    )
                    ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
                cur = own_pid
                for _ in range(3):
                    info = table.get(cur)
                    if info is None:
                        break
                    ppid, _ = info
                    parent_info = table.get(ppid)
                    if parent_info is None:
                        break
                    _, parent_exe = parent_info
                    if "shinsekai" in parent_exe:
                        pids.add(ppid)
                    cur = ppid
            finally:
                kernel32.CloseHandle(snap)
        except Exception:
            pass
        return frozenset(pids)

    def _vcall(ptr: ctypes.c_void_p, idx: int, restype: Any, *argtypes: Any) -> Any:
        vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtbl[idx])

    def _com_release(ptr: ctypes.c_void_p | None) -> None:
        if ptr is not None and ptr.value:
            try:
                _vcall(ptr, 2, ctypes.c_ulong)(ptr)
            except Exception:
                pass
            ptr.value = None

    class WindowsCursorProbe:
        """Low-latency Windows cursor tracker, UIA selection reader, and native-DPI patch grabber."""

        def __init__(self) -> None:
            self._user32 = ctypes.windll.user32
            self._ole32 = ctypes.windll.ole32
            self._oleaut32 = ctypes.windll.oleaut32
            self._ignored_pids = _discover_self_pids()
            self._uia: ctypes.c_void_p | None = None
            self._walker: ctypes.c_void_p | None = None
            self._uia_failed: bool = False
            self._cached_hwnd: int = 0
            self._cached_is_self: bool = False

            try:
                self._user32.WindowFromPoint.argtypes = [wt.POINT]
                self._user32.WindowFromPoint.restype = wt.HWND
                self._user32.GetAncestor.argtypes = [wt.HWND, wt.UINT]
                self._user32.GetAncestor.restype = wt.HWND
            except Exception:
                pass

        def prepare_thread(self) -> None:
            try:
                set_dpi = self._user32.SetThreadDpiAwarenessContext
                set_dpi.argtypes = [ctypes.c_void_p]
                set_dpi.restype = ctypes.c_void_p
                set_dpi(ctypes.c_void_p(-4))  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            except Exception:
                pass
            try:
                self._ole32.CoInitializeEx(None, 0)
            except Exception:
                pass

        def _is_self_window(self, x: int, y: int) -> bool:
            try:
                hwnd = self._user32.WindowFromPoint(wt.POINT(x, y))
                if not hwnd:
                    return False
                root = self._user32.GetAncestor(hwnd, _GA_ROOT) or hwnd
                root_id = int(root)
                if root_id == self._cached_hwnd:
                    return self._cached_is_self
                pid = wt.DWORD(0)
                self._user32.GetWindowThreadProcessId(root, ctypes.byref(pid))
                is_self = int(pid.value) in self._ignored_pids
                if not is_self:
                    buf = ctypes.create_unicode_buffer(96)
                    if self._user32.GetWindowTextW(root, buf, 96) > 0:
                        is_self = buf.value.strip().casefold() == "shinsekai"
                self._cached_hwnd = root_id
                self._cached_is_self = is_self
                return is_self
            except Exception:
                return False

        def sample(self) -> CursorSample | None:
            pt = wt.POINT()
            ok = bool(self._user32.GetCursorPos(ctypes.byref(pt)))
            if not ok:
                try:
                    ok = bool(self._user32.GetPhysicalCursorPos(ctypes.byref(pt)))
                except Exception:
                    ok = False
            if not ok:
                return None
            left_down = (self._user32.GetAsyncKeyState(_VK_LBUTTON) & 0x8000) != 0
            over_self = self._is_self_window(int(pt.x), int(pt.y))
            return CursorSample(
                x=int(pt.x),
                y=int(pt.y),
                left_down=left_down,
                over_self_window=over_self,
            )

        def _ensure_uia(self) -> bool:
            if self._uia is not None and self._uia.value:
                return True
            if self._uia_failed:
                return False
            try:
                clsid = _GUID.from_str("{FF48DBA4-60EF-4201-AA87-54103EEF594E}")
                iid = _GUID.from_str("{30CBE57D-D9D0-452A-AB13-7AC5AC4825EE}")
                uia = ctypes.c_void_p()
                hr = self._ole32.CoCreateInstance(
                    ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(uia)
                )
                if hr != 0 or not uia.value:
                    self._uia_failed = True
                    return False
                walker = ctypes.c_void_p()
                _vcall(uia, 14, ctypes.c_long, ctypes.POINTER(ctypes.c_void_p))(
                    uia, ctypes.byref(walker)
                )
                self._uia = uia
                self._walker = walker if walker.value else None
                return True
            except Exception:
                self._uia_failed = True
                return False

        def _extract_selection_from_pattern(self, pat: ctypes.c_void_p) -> str:
            arr = ctypes.c_void_p()
            try:
                hr = _vcall(pat, 5, ctypes.c_long, ctypes.POINTER(ctypes.c_void_p))(
                    pat, ctypes.byref(arr)
                )
                if hr != 0 or not arr.value:
                    return ""
                count = ctypes.c_int(0)
                _vcall(arr, 3, ctypes.c_long, ctypes.POINTER(ctypes.c_int))(
                    arr, ctypes.byref(count)
                )
                pieces: list[str] = []
                for idx in range(min(max(0, int(count.value)), 3)):
                    rng = ctypes.c_void_p()
                    bstr = ctypes.c_void_p()
                    try:
                        hr_el = _vcall(
                            arr, 4, ctypes.c_long, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)
                        )(arr, idx, ctypes.byref(rng))
                        if hr_el != 0 or not rng.value:
                            continue
                        hr_txt = _vcall(
                            rng, 12, ctypes.c_long, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)
                        )(rng, 320, ctypes.byref(bstr))
                        if hr_txt == 0 and bstr.value:
                            pieces.append(ctypes.wstring_at(bstr.value))
                    finally:
                        if bstr.value:
                            self._oleaut32.SysFreeString(bstr)
                        _com_release(rng)
                return _clean_text(" ".join(pieces))
            finally:
                _com_release(arr)

        def _read_element_chain_selection(self, start_elem: ctypes.c_void_p) -> str:
            current = start_elem
            owns_current = False
            try:
                pid = ctypes.c_int(0)
                if (
                    _vcall(current, 20, ctypes.c_long, ctypes.POINTER(ctypes.c_int))(
                        current, ctypes.byref(pid)
                    ) == 0
                    and int(pid.value) in self._ignored_pids
                ):
                    return ""

                for _ in range(5):
                    for pattern_id in (_UIA_TEXT_PATTERN_ID, _UIA_TEXT_PATTERN2_ID):
                        pat = ctypes.c_void_p()
                        try:
                            hr = _vcall(
                                current,
                                16,
                                ctypes.c_long,
                                ctypes.c_int,
                                ctypes.POINTER(ctypes.c_void_p),
                            )(current, pattern_id, ctypes.byref(pat))
                            if hr == 0 and pat.value:
                                text = self._extract_selection_from_pattern(pat)
                                if len(text) >= 2:
                                    return text
                        finally:
                            _com_release(pat)

                    if self._walker is None or not self._walker.value:
                        break
                    parent = ctypes.c_void_p()
                    hr_p = _vcall(
                        self._walker,
                        3,
                        ctypes.c_long,
                        ctypes.c_void_p,
                        ctypes.POINTER(ctypes.c_void_p),
                    )(self._walker, current, ctypes.byref(parent))
                    if owns_current:
                        _com_release(current)
                        owns_current = False
                    if hr_p != 0 or not parent.value:
                        break
                    current = parent
                    owns_current = True
                return ""
            finally:
                if owns_current:
                    _com_release(current)

        def read_selected_text(self, x: int, y: int) -> str:
            if not self._ensure_uia() or self._uia is None:
                return ""
            try:
                focused = ctypes.c_void_p()
                try:
                    hr = _vcall(
                        self._uia, 8, ctypes.c_long, ctypes.POINTER(ctypes.c_void_p)
                    )(self._uia, ctypes.byref(focused))
                    if hr == 0 and focused.value:
                        text = self._read_element_chain_selection(focused)
                        if len(text) >= 2:
                            return text
                finally:
                    _com_release(focused)

                pointed = ctypes.c_void_p()
                try:
                    hr_pt = _vcall(
                        self._uia,
                        7,
                        ctypes.c_long,
                        wt.POINT,
                        ctypes.POINTER(ctypes.c_void_p),
                    )(self._uia, wt.POINT(x, y), ctypes.byref(pointed))
                    if hr_pt == 0 and pointed.value:
                        return self._read_element_chain_selection(pointed)
                finally:
                    _com_release(pointed)
            except Exception:
                logger.debug("UIA selection lookup failed", exc_info=True)
            return ""

        def capture_patch(
            self,
            bbox: tuple[int, int, int, int],
            *,
            mode: Literal["cursor", "full"] = "cursor",
            captured_at: float | None = None,
        ) -> CursorPatch | None:
            left, top, right, bottom = bbox
            if right - left < 24 or bottom - top < 16:
                return None
            try:
                from PIL import Image, ImageGrab

                img = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True).convert("RGB")
                if img.width < 16 or img.height < 12:
                    return None
                luma_thumb = img.convert("L").resize((16, 8), Image.Resampling.BILINEAR).tobytes()
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=88, subsampling=0)
                encoded = base64.b64encode(buf.getvalue()).decode("ascii")
                frame = PerceptionFrame(
                    image_base64=encoded,
                    mime_type="image/jpeg",
                    width=img.width,
                    height=img.height,
                    source="cursor_ocr",
                    captured_at=time.time() if captured_at is None else float(captured_at),
                    ocr_scope=ScreenOcrScope(mode=mode),
                )
                return CursorPatch(frame=frame, luma_thumb=luma_thumb)
            except Exception:
                return None

        def close(self) -> None:
            _com_release(self._walker)
            _com_release(self._uia)
            self._walker = None
            self._uia = None


def create_default_cursor_probe() -> CursorProbe | None:
    """Return the platform cursor/selection probe (`WindowsCursorProbe` on Windows)."""
    if sys.platform == "win32":
        return WindowsCursorProbe()
    return None


__all__ = [
    "CursorObservation",
    "CursorPatch",
    "CursorProbe",
    "CursorReadingTracker",
    "CursorSample",
    "create_default_cursor_probe",
]
