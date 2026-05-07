"""
抽象消息处理器基类 — TTS 消费 LLMDialogMessage，UI 消费 TTSOutputMessage。

具体实现见 :mod:`core.handlers.tts_message_handler` / :mod:`core.handlers.ui_message_handler`。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from sdk.messages import LLMDialogMessage, TTSOutputMessage


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
