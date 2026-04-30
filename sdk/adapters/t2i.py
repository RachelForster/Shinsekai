from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class T2IAdapter(ABC):
    """文生图（T2I）适配器接口。"""

    @abstractmethod
    def generate_image(
        self, prompt: str, file_path: Optional[str] = None, **kwargs
    ) -> Optional[str]:
        pass

    @abstractmethod
    def switch_model(self, model_info: Dict[str, Any]) -> None:
        pass
