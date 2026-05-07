"""
消息处理器调度器 — TtsMessageDispatcher 和 UiOutputMessageDispatcher。

处理器抽象类在 :mod:`sdk.handlers`；具体实现见
:mod:`core.handlers.tts_message_handler` / :mod:`core.handlers.ui_message_handler`。
"""

from __future__ import annotations

from typing import List

from sdk.handlers import MessageHandler, UIOutputMessageHandler
from sdk.messages import LLMDialogMessage, TTSOutputMessage


class TtsMessageDispatcher:
    def __init__(self, handlers: List[MessageHandler]) -> None:
        if not handlers:
            raise ValueError("至少需要一个 TTS handler（末项应为缺省）")
        self._handlers = list(handlers)

    def init_handlers(self) -> None:
        for h in self._handlers:
            h.init()

    def dispatch(self, msg: LLMDialogMessage) -> None:
        for h in self._handlers:
            if h.can_handle(msg):
                h.pre_process(msg)
                h.handle(msg)
                h.post_process(msg)
                return
        raise RuntimeError(f"无 TTS handler 匹配: {msg.name!r}")


class UiOutputMessageDispatcher:
    def __init__(self, handlers: List[UIOutputMessageHandler]) -> None:
        if not handlers:
            raise ValueError("至少需要一个 UI handler（末项应为缺省）")
        self._handlers = list(handlers)

    def init_handlers(self) -> None:
        for h in self._handlers:
            h.init()

    def dispatch(self, out: TTSOutputMessage) -> None:
        for h in self._handlers:
            if h.can_handle(out):
                h.pre_process(out)
                h.handle(out)
                h.post_process(out)
                return
        raise RuntimeError(
            f"无 UI handler 匹配: is_system={out.is_system_message!r} name={out.name!r}"
        )


def default_tts_handler_chain() -> TtsMessageDispatcher:
    """插件 handler 在前，内置链在后（先匹配先处理）。"""
    from core.plugins.plugin_host import get_plugin_tts_handlers
    from core.handlers.tts_message_handler import get_tts_handlers

    chain = list(get_plugin_tts_handlers()) + list(get_tts_handlers())
    return TtsMessageDispatcher(chain)


def default_ui_output_handler_chain() -> UiOutputMessageDispatcher:
    from core.plugins.plugin_host import get_plugin_ui_handlers
    from core.handlers.ui_message_handler import get_ui_output_handlers

    chain = list(get_plugin_ui_handlers()) + list(get_ui_output_handlers())
    return UiOutputMessageDispatcher(chain)
