from __future__ import annotations

from abc import ABC, abstractmethod


class TTSAdapter(ABC):
    """语音合成适配器接口。"""

    @abstractmethod
    def generate_speech(self, text, file_path=None, **kwargs):
        pass

    @abstractmethod
    def switch_model(self, model_info):
        pass
