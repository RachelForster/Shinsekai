"""
应用运行期共享上下文：在 main 中 set_app_runtime 后，各模块通过 get_app_runtime() 访问
配置、管理器、队列、繁简转换、TTS 入 UI 队列等。Handler 不依赖 worker 类型。
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from typing import Any, List, Optional

from core.messaging.chat_turn_service import ChatTurnService


@dataclass
class UiPlaybackBridge:
    """由 presentation worker 写入，供输出 handler 做对话音轨与跳过。"""

    task_done_requested: Any = None
    dialog_channel: Any = None
    current_audio_path: Any = None


@dataclass
class PendingToolConfirmation:
    confirmation_id: str
    tool_name: str
    event: threading.Event = field(default_factory=threading.Event)
    confirmed: bool | None = None


class ToolConfirmationController:
    """Correlate one-time user decisions with the risky prompt that created them."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: dict[str, PendingToolConfirmation] = {}

    def create(self, tool_name: str) -> PendingToolConfirmation:
        prompt = PendingToolConfirmation(
            confirmation_id=secrets.token_urlsafe(24),
            tool_name=str(tool_name or ""),
        )
        with self._lock:
            self._pending[prompt.confirmation_id] = prompt
        return prompt

    def resolve(self, confirmation_id: str, action: str) -> bool:
        normalized_id = str(confirmation_id or "").strip()
        normalized_action = str(action or "").strip().casefold()
        if not normalized_id or normalized_action not in {"confirm", "cancel"}:
            return False
        with self._lock:
            prompt = self._pending.pop(normalized_id, None)
        if prompt is None:
            return False
        prompt.confirmed = normalized_action == "confirm"
        prompt.event.set()
        return True

    def discard(self, confirmation_id: str) -> None:
        with self._lock:
            self._pending.pop(str(confirmation_id or "").strip(), None)


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
    chat_turn_service: ChatTurnService = field(default_factory=ChatTurnService)
    tool_confirmations: ToolConfirmationController = field(
        default_factory=ToolConfirmationController
    )


_runtime: Optional[AppRuntime] = None


def set_app_runtime(rt: Optional[AppRuntime]) -> None:
    global _runtime
    _runtime = rt


def get_app_runtime() -> AppRuntime:
    if _runtime is None:
        raise RuntimeError("尚未调用 set_app_runtime：请在创建 Worker 之前完成应用上下文注册")
    return _runtime


def try_get_app_runtime() -> Optional[AppRuntime]:
    return _runtime


def get_tool_confirmation_controller() -> ToolConfirmationController:
    rt = try_get_app_runtime()
    if rt is None:
        raise RuntimeError("application runtime is unavailable")
    controller = getattr(rt, "tool_confirmations", None)
    if not isinstance(controller, ToolConfirmationController):
        controller = ToolConfirmationController()
        rt.tool_confirmations = controller
    return controller


def resolve_pending_tool_confirmation(
    confirmation_id: str,
    action: str,
) -> bool:
    """Resolve exactly one risky-tool prompt using its one-time identifier."""
    rt = try_get_app_runtime()
    if rt is None:
        return False
    return get_tool_confirmation_controller().resolve(confirmation_id, action)


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
    """Compatibility query delegated to the chat turn service."""
    rt = try_get_app_runtime()
    return rt is not None and rt.chat_turn_service.is_active()
