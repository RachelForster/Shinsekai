from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

from plugins.moondream_vision.capture_infer import grab_screen_png, grab_screen_thumbnail
from plugins.moondream_vision.config_model import (
    default_config_path,
    load_config,
)
from plugins.moondream_vision.local_infer import infer_screen_png, unload_model
from plugins.moondream_vision.prompts import question_for_triggers
from plugins.moondream_vision.trigger_state import MoondreamTriggerState
from plugins.moondream_vision.ui_busy import moondream_busy

logger = logging.getLogger(__name__)

_emit_user_text: Callable[[str], None] | None = None
_worker_thread: threading.Thread | None = None
_stop_event: threading.Event | None = None
_lock = threading.Lock()
_plugin_root: Path | None = None

_POLL_IDLE_SEC = 2.0


def set_plugin_root(root: Path) -> None:
    global _plugin_root
    _plugin_root = root


def plugin_config_path() -> Path:
    """插件 ``config.json`` 路径；供识屏后台与 LLM 工具共用。"""
    if _plugin_root is None:
        raise RuntimeError("moondream_vision: plugin root not set")
    return default_config_path(_plugin_root)


def _config_file() -> Path:
    return plugin_config_path()


def bind_emit(emit: Callable[[str], None]) -> None:
    """由 host 在 wire_user_input 时调用。"""
    global _emit_user_text
    with _lock:
        _emit_user_text = emit
    _restart_worker()


def shutdown() -> None:
    _stop_worker()
    unload_model()


def _stop_worker() -> None:
    global _worker_thread, _stop_event
    with _lock:
        if _stop_event is not None:
            _stop_event.set()
        t = _worker_thread
        _worker_thread = None
        _stop_event = None
    if t is not None and t.is_alive():
        t.join(timeout=5.0)


def _restart_worker() -> None:
    _stop_worker()
    with _lock:
        emit = _emit_user_text
    if emit is None:
        return

    stop = threading.Event()
    state = MoondreamTriggerState()
    last_infer_monotonic = 0.0
    last_monitor_index: int | None = None

    def _run() -> None:
        nonlocal last_infer_monotonic, last_monitor_index
        while not stop.is_set():
            try:
                c = load_config(_config_file())
                if not c.enabled:
                    if stop.wait(_POLL_IDLE_SEC):
                        break
                    continue

                if last_monitor_index is not None and last_monitor_index != c.monitor_index:
                    state.reset_after_config_hot_reload()
                last_monitor_index = c.monitor_index

                poll = float(c.motion_poll_sec)
                if stop.wait(poll):
                    break

                c = load_config(_config_file())
                if not c.enabled:
                    continue

                thumb = grab_screen_thumbnail(c.monitor_index)
                fired, reasons = state.evaluate(c, thumb)
                if not fired:
                    continue

                now = time.monotonic()
                if now - last_infer_monotonic < float(c.interval_sec):
                    continue

                with moondream_busy():
                    png = grab_screen_png(c.monitor_index)
                    q = question_for_triggers(c, reasons)
                    text = infer_screen_png(png, q, c)
                    msg = f"{c.message_prefix}{text}".strip()
                    if msg:
                        emit(msg)
                    state.on_infer_done(thumb)
                    last_infer_monotonic = time.monotonic()
                logger.info(
                    "Moondream 已触发识屏（%s）",
                    ",".join(reasons) if reasons else "?",
                )
            except Exception:
                logger.exception("Moondream 屏幕识别轮询失败")

    global _worker_thread, _stop_event
    with _lock:
        _stop_event = stop
        _worker_thread = threading.Thread(
            target=_run,
            name="moondream_vision_loop",
            daemon=True,
        )
        _worker_thread.start()
