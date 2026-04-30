from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

TranscriptionCallback = Callable[[str, bool], None]


class ASRAdapter(ABC):
    """实时语音转文字适配器接口。"""

    def __init__(self, language: str, callback: TranscriptionCallback):
        self.language = language
        self.callback = callback

    @abstractmethod
    def start(self) -> None:
        pass

    @abstractmethod
    def stop(self) -> None:
        pass

    @abstractmethod
    def get_status(self) -> str:
        pass

    @abstractmethod
    def pause(self) -> None:
        pass

    @abstractmethod
    def resume(self) -> None:
        pass
