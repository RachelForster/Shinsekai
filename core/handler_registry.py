"""
消息处理器抽象与调度。TTS 消费 LLMDialogMessage，UI 消费 TTSOutputMessage。
实现类通过 get_app_runtime() 取共享依赖，不依赖 worker 类型。
具体实现见 tts_message_handler / ui_message_handler 模块。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from core.message import LLMDialogMessage, TTSOutputMessage


class MessageHandler(ABC):
    """TTS 队列中 LLM 单条 dialog 的处理器。bgm/CG 等用原始名，其馀可用 opencc 繁简。"""

    @abstractmethod
    def can_handle(self, msg: LLMDialogMessage) -> bool:
        ...

    def pre_process(self, msg: LLMDialogMessage) -> None:
        pass

    def handle(self, msg: LLMDialogMessage) -> None:
        pass

    def post_process(self, msg: LLMDialogMessage) -> None:
        pass

    def init(self) -> None:
        """在 TTS worker 构建调度器后执行一次，可从 get_app_runtime() 取资源。"""
        pass


class UIOutputMessageHandler(ABC):
    """UI 队列中 TTSOutputMessage 的处理器。"""

    @abstractmethod
    def can_handle(self, out: TTSOutputMessage) -> bool:
        ...

    def pre_process(self, out: TTSOutputMessage) -> None:
        pass

    def handle(self, out: TTSOutputMessage) -> None:
        pass

    def post_process(self, out: TTSOutputMessage) -> None:
        pass

    def init(self) -> None:
        """在 UI worker 构建调度器后执行一次（建议 UI init_channel 之后对 bridge 先赋值，再调 init）。"""
        pass


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
        raise RuntimeError(f"无 TTS handler 匹配: {msg.character_name!r}")


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
            f"无 UI handler 匹配: is_system={out.is_system_message!r} name={out.character_name!r}"
        )


def default_tts_handler_chain() -> TtsMessageDispatcher:
    """插件 handler 在前，内置链在后（先匹配先处理）。"""
    from core.plugin_host import get_plugin_tts_handlers
    from core.tts_message_handler import get_tts_handlers

    chain = list(get_plugin_tts_handlers()) + list(get_tts_handlers())
    return TtsMessageDispatcher(chain)


def default_ui_output_handler_chain() -> UiOutputMessageDispatcher:
    from core.plugin_host import get_plugin_ui_handlers
    from core.ui_message_handler import get_ui_output_handlers

    chain = list(get_plugin_ui_handlers()) + list(get_ui_output_handlers())
    return UiOutputMessageDispatcher(chain)
