"""
抽象消息处理器基类 — 对话媒体层消费 LLMDialogMessage，UI 消费 PresentationMessage。

具体实现见 :mod:`application.chat.handlers.dialog_media` /
:mod:`application.chat.handlers.presentation`。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from sdk.messages import LLMDialogMessage, PresentationMessage


class MessageHandler(ABC):
    """对话媒体队列中单条消息的处理器。bgm/CG 用原始名，其余可用 OpenCC 繁简。"""

    @abstractmethod
    def can_handle(self, msg: LLMDialogMessage) -> bool: ...

    def pre_process(self, msg: LLMDialogMessage) -> None:
        pass

    def handle(self, msg: LLMDialogMessage) -> None:
        pass

    def post_process(self, msg: LLMDialogMessage) -> None:
        pass

    def init(self) -> None:
        """在 dialog media worker 构建调度器后执行一次，可从 get_app_runtime() 取资源。"""
        pass


class UIOutputMessageHandler(ABC):
    """UI 队列中 PresentationMessage 的处理器。"""

    @abstractmethod
    def can_handle(self, out: PresentationMessage) -> bool: ...

    def pre_process(self, out: PresentationMessage) -> None:
        pass

    def handle(self, out: PresentationMessage) -> None:
        pass

    def post_process(self, out: PresentationMessage) -> None:
        pass

    def init(self) -> None:
        """在 UI worker 构建调度器后执行一次（建议 UI init_channel 之后对 bridge 先赋值，再调 init）。"""
        pass
