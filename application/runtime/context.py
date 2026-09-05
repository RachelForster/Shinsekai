"""
应用运行期共享上下文：在 main 中 set_app_runtime 后，各模块通过 get_app_runtime() 访问
配置、管理器、队列、繁简转换、展示消息发送等。Handler 不依赖 worker 类型。
"""

from __future__ import annotations

import json
import secrets
import threading
from dataclasses import dataclass, field
from typing import Any, List, Optional

from core.messaging.chat_turn_service import ChatTurnService
from sdk.llm_runtime import set_llm_host_runtime


@dataclass
class UiPlaybackBridge:
    """由 presentation worker 写入，供输出 handler 做对话音轨与跳过。"""

    task_done_requested: Any = None
    dialog_channel: Any = None
    current_audio_path: Any = None
    playback_controller: Any = None


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
    dialog_queue: Any
    presentation_queue: Any
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


def emit_presentation_message(
    character_name: str,
    speech: str,
    sprite: str,
    audio_path: str,
    *,
    is_system_message: bool = False,
    effect: str = "",
) -> None:
    """Emit one presentation-ready dialog media message."""
    from sdk.messages import PresentationMessage

    rt = get_app_runtime()
    audio_path = audio_path or ""
    out = PresentationMessage(
        audio_path=audio_path,
        name=character_name,
        asset_id=sprite,
        text=speech,
        is_system_message=is_system_message,
        effect=effect,
    )
    rt.presentation_queue.put(out)


def is_generating() -> bool:
    """Compatibility query delegated to the chat turn service."""
    rt = try_get_app_runtime()
    return rt is not None and rt.chat_turn_service.is_active()


class _ApplicationLLMHostRuntime:
    """Application-owned implementation of the SDK LLM host contract."""

    def notify_tool_call(self, tool_name: str) -> None:
        rt = try_get_app_runtime()
        if rt is None:
            return
        try:
            from i18n import tr

            rt.ui_update_manager.post_busy_bar(
                tr("main.notify_tool_calling", name=tool_name),
                4.0,
            )
        except Exception:
            pass

    def confirm_risky_tool(
        self,
        tool_name: str,
        risk: str,
        args_text: str,
    ) -> bool:
        rt = try_get_app_runtime()
        if rt is None:
            return str(risk or "").casefold() != "high"
        ui = rt.ui_update_manager
        detail = ""
        try:
            args_obj = (
                json.loads(args_text)
                if isinstance(args_text, str)
                else args_text
            )
            if isinstance(args_obj, dict):
                parts = []
                for key, value in args_obj.items():
                    if key in {"content", "keyword"}:
                        parts.append(f"{key}={str(value)[:60]}")
                    else:
                        parts.append(f"{key}={value}")
                detail = " · ".join(parts[:6])
        except Exception:
            detail = args_text[:120] if args_text else ""

        controller = get_tool_confirmation_controller()
        prompt = controller.create(tool_name)
        try:
            if hasattr(ui, "post_tool_confirmation"):
                ui.post_tool_confirmation(
                    confirmation_id=prompt.confirmation_id,
                    tool_name=tool_name,
                    detail=detail,
                    risk=risk,
                )
            else:
                from i18n import tr

                confirm_label = tr(
                    "tool_confirmation.confirm",
                    tool=tool_name,
                )
                if detail:
                    confirm_label = f"{confirm_label}\n{detail}"
                ui.post_options(
                    [
                        {
                            "action": "cancel",
                            "confirmationId": prompt.confirmation_id,
                            "kind": "tool-confirmation",
                            "label": tr("common.cancel"),
                        },
                        {
                            "action": "confirm",
                            "confirmationId": prompt.confirmation_id,
                            "kind": "tool-confirmation",
                            "label": confirm_label,
                        },
                    ]
                )
            resolved = prompt.event.wait(timeout=30.0)
        finally:
            controller.discard(prompt.confirmation_id)
            try:
                if hasattr(ui, "clear_tool_confirmation"):
                    ui.clear_tool_confirmation(prompt.confirmation_id)
                else:
                    ui.post_options([])
            except Exception:
                pass
        if not resolved:
            try:
                from i18n import tr

                ui.post_notification(
                    tr("tool_confirmation.timeout", tool=tool_name)
                )
            except Exception:
                pass
            return False
        return prompt.confirmed is True

    def post_context_token_estimate(self, estimate: dict[str, int]) -> None:
        rt = try_get_app_runtime()
        ui = getattr(rt, "ui_update_manager", None) if rt is not None else None
        post = getattr(ui, "post_context_token_estimate", None)
        if post is not None:
            post(estimate)

    def notify_tool_ready(self, group: str, message: str) -> None:
        del group
        if not message or try_get_app_runtime() is None:
            return
        try:
            emit_presentation_message(
                character_name="",
                speech=message,
                sprite="",
                audio_path="",
                is_system_message=True,
            )
        except Exception:
            pass

    def set_user_display_name(self, display_name: str) -> str | None:
        rt = try_get_app_runtime()
        if rt is None:
            return "chat runtime is not ready"
        ui = getattr(rt, "ui_update_manager", None)
        if ui is None or not hasattr(ui, "set_user_display_name"):
            return "chat UI does not support user display name updates"
        ui.set_user_display_name(display_name)
        return None


set_llm_host_runtime(_ApplicationLLMHostRuntime())
