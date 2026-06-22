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
    effect_keyword_map: dict = field(default_factory=dict)  # keyword → audio_path
    ui_playback: UiPlaybackBridge = field(default_factory=UiPlaybackBridge)


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
