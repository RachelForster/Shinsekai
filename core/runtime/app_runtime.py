"""
应用运行期共享上下文：在 main 中 set_app_runtime 后，各模块通过 get_app_runtime() 访问
配置、管理器、队列、繁简转换、TTS 入 UI 队列等。Handler 不依赖 worker 类型。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass
class UiPlaybackBridge:
    """由 UIWorker 在 init_channel 后写入，供 UI 消息 handler 做对话音轨与跳过。"""

    task_done_requested: Any = None
    dialog_channel: Any = None
    current_audio_path: Any = None


@dataclass
class AppRuntime:
    config: Any  # ConfigManager
    ui_update_manager: Any  # UIUpdateManager
    llm_manager: Any  # LLMManager
    tts_manager: Optional[Any]  # TTSManager | None
    t2i_manager: Optional[Any]  # T2IManager | None
    bgm_list: List[Any]
    user_input_queue: Any
    tts_queue: Any
    audio_path_queue: Any
    text_processor: Any  # TextProcessor
    opencc: Any  # OpenCC
    ui_playback: UiPlaybackBridge = field(default_factory=UiPlaybackBridge)
    cancellation_requested: Any = field(default_factory=lambda: __import__('threading').Event())
    generating: Any = field(default_factory=lambda: __import__('threading').Event())
    ui_worker: Any = None


_runtime: Optional[AppRuntime] = None


def set_app_runtime(rt: AppRuntime) -> None:
    global _runtime
    _runtime = rt


def get_app_runtime() -> AppRuntime:
    if _runtime is None:
        raise RuntimeError("尚未调用 set_app_runtime：请在创建 Worker 之前完成应用上下文注册")
    return _runtime


def try_get_app_runtime() -> Optional[AppRuntime]:
    return _runtime


def tts_emit_to_ui_queue(
    character_name: str,
    speech: str,
    sprite: str,
    audio_path: str,
    *,
    is_system_message: bool = False,
    effect: str = "",
) -> None:
    """Emit one TTS result to the UI queue."""
    from sdk.messages import TTSOutputMessage

    rt = get_app_runtime()
    audio_path = audio_path or ""
    out = TTSOutputMessage(
        audio_path=audio_path,
        name=character_name,
        asset_id=sprite,
        text=speech,
        is_system_message=is_system_message,
        effect=effect,
    )
    rt.audio_path_queue.put(out)


def is_generating() -> bool:
    """Return True when LLM is actively generating a response."""
    rt = try_get_app_runtime()
    return rt is not None and rt.generating.is_set()


def is_anything_running() -> bool:
    """Return True when **any** part of the pipeline is active — LLM, TTS, or UI
    playback. Use this to decide whether an interrupt is worth performing."""
    rt = try_get_app_runtime()
    if rt is None:
        return False
    if rt.generating.is_set():
        return True
    # Check if TTS is producing audio or UI is still displaying/playing
    if rt.tts_queue is not None and not rt.tts_queue.empty():
        return True
    if rt.audio_path_queue is not None and not rt.audio_path_queue.empty():
        return True
    return False


def request_interrupt() -> None:
    """Cancel the current LLM generation and flush all downstream queues.

    This is the central interrupt orchestrator.  It:
    1. Signals cancellation so the LLM stream loop exits early.
    2. Aborts the in-flight HTTP request via the adapter.
    3. Clears the TTS queue (parsed dialog messages not yet synthesized).
    4. Stops currently-playing TTS audio.
    5. Clears the UI queue (synthesized audio not yet displayed).
    6. Hides the busy bar and resets the generating flag.
    """
    rt = get_app_runtime()

    # 1. Signal cancellation — LLMWorker stream loop will break on this
    rt.cancellation_requested.set()

    # 2. Abort the in-flight LLM API request
    if rt.llm_manager is not None:
        try:
            rt.llm_manager.cancel_current_chat()
        except Exception:
            pass

    # 3. Discard pending TTS synthesis items
    if rt.tts_queue is not None:
        try:
            rt.tts_queue.clear()
        except Exception:
            pass

    # 4. Stop currently-playing audio
    if rt.ui_worker is not None:
        try:
            rt.ui_worker.skip_speech()
        except Exception:
            pass

    # 5. Discard pending UI display items
    if rt.audio_path_queue is not None:
        try:
            rt.audio_path_queue.clear()
        except Exception:
            pass

    # 6. Hide busy bar
    if rt.ui_update_manager is not None:
        try:
            rt.ui_update_manager.hide_busy_bar()
        except Exception:
            pass

    # 7. Reset generating flag
    rt.generating.clear()
