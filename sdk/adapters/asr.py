from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

TranscriptionCallback = Callable[[str, bool], None]


class ASRAdapter(ABC):
    """Abstract streaming speech-to-text adapter.

    Base defaults and conventions:
        - ``__init__(language, callback)``: Both required; no defaults at this ABC level.
        - ``get_config_schema()``: Returns ``{}`` by default; non-empty schema follows
          ``LLMAdapter.get_config_schema`` meta keys.
        - Shared fields such as language live in ``system_config`` / the main API tab form;
          schema holds backend-only extras.
    """

    def __init__(self, language: str, callback: TranscriptionCallback):
        self.language = language
        self.callback = callback

    @classmethod
    def get_config_schema(cls) -> dict[str, dict]:
        """Metadata for adapter-specific options; empty ``{}`` means none."""
        return {}

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
