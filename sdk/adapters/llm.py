from __future__ import annotations

from abc import ABC, abstractmethod


class LLMAdapter(ABC):
    """LLM 服务适配器接口。"""

    def __init__(self, **kwargs) -> None:
        self.user_template = ""

    @abstractmethod
    def chat(self, messages: list, stream: bool = False, **kwargs):
        pass

    def set_user_template(self, template: str) -> None:
        self.user_template = template
