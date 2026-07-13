from __future__ import annotations

from abc import ABC, abstractmethod


class VisionAdapter(ABC):
    """Provider-neutral interface for understanding a single image."""

    @abstractmethod
    def describe(self, image_bytes: bytes, prompt: str) -> str:
        """Return a textual answer for ``prompt`` about ``image_bytes``."""

